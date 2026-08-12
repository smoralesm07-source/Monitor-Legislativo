#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extensiones del Monitor Legislativo UAF.

Capa aditiva sobre ``monitor_legislativo.py`` para:

1. Conciliar diariamente el universo reciente de la Cámara de Diputadas y
   Diputados sin reemplazar el barrido incremental del Senado.
2. Aumentar el recall sobre proyectos nuevos cuyo título no revela su impacto
   LA/FT, revisando una muestra acotada de iniciativas recientes de Cámara.
3. Incorporar el texto completo que entrega el XML individual de Cámara como
   campo analizable por el motor de pertinencia.
4. Robustecer los ejes ``beneficiario_final`` y
   ``proliferacion_uso_dual``.

No altera la configuración ni las reglas de correo. El workflow mantiene
``MONITOR_NIVEL_AVISO`` exactamente como estaba.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

import monitor_legislativo as m

VERSION_EXTENSION = "1.1.0-camara-bf-uso-dual"

# Conservamos referencias a las implementaciones base antes del monkey patch.
_ORIG_CAMPOS_ANALIZABLES = m.campos_analizables
_ORIG_DESCUBRE = m.descubre
_ORIG_PRESELECCIONA = m.preselecciona
_APLICADO = False


def _env_int(nombre: str, defecto: int, minimo: int, maximo: int) -> int:
    try:
        valor = int(os.getenv(nombre, str(defecto)) or defecto)
    except ValueError:
        valor = defecto
    return max(minimo, min(maximo, valor))


ANNOS_CAMARA_DIARIO = _env_int("MONITOR_ANNOS_CAMARA_DIARIO", 2, 1, 4)
DIAS_REVISION_NUEVOS = _env_int("MONITOR_CAMARA_REVISION_NUEVOS_DIAS", 60, 15, 180)
DIAS_REVISION_CONCILIACION = _env_int(
    "MONITOR_CAMARA_REVISION_CONCILIACION_DIAS", 540, 180, 1100
)
MAX_REVISION_CAMARA_RAPIDO = _env_int("MONITOR_MAX_CAMARA_REVISION_RAPIDO", 90, 20, 180)
MAX_REVISION_CAMARA_CONCILIACION = _env_int(
    "MONITOR_MAX_CAMARA_REVISION_CONCILIACION", 260, 60, 500
)
MAX_TOTAL_RAPIDO = _env_int("MONITOR_MAX_TOTAL_RAPIDO_EXT", 320, 100, 500)
MAX_TOTAL_CONCILIACION = _env_int("MONITOR_MAX_TOTAL_CONCILIACION_EXT", 980, 300, 1400)
MAX_TEXTO_CAMARA = _env_int("MONITOR_MAX_TEXTO_CAMARA", 120_000, 20_000, 250_000)


TERMINOS_BENEFICIARIO_FINAL = [
    "beneficiario final",
    "beneficiarios finales",
    "beneficiario efectivo",
    "beneficiarios efectivos",
    "titular real",
    "titulares reales",
    "titular efectivo",
    "titulares efectivos",
    "propietario efectivo",
    "propietarios efectivos",
    "controlante final",
    "controlantes finales",
    "registro de beneficiarios finales",
    "registro de beneficiario final",
    "declaracion de beneficiario final",
    "informacion de beneficiario final",
    "transparencia de la propiedad",
    "transparencia societaria",
    "cadena de propiedad",
    "cadena de control",
    "estructura de propiedad y control",
    "persona natural que ejerce el control",
    "propiedad o control final",
]

TERMINOS_PROLIFERACION_USO_DUAL = [
    "financiamiento de la proliferacion",
    "financiacion de la proliferacion",
    "proliferacion de armas de destruccion masiva",
    "armas de destruccion masiva",
    "bienes de uso dual",
    "bienes de doble uso",
    "productos de uso dual",
    "productos de doble uso",
    "tecnologias de uso dual",
    "tecnologias de doble uso",
    "materiales de uso dual",
    "materiales de doble uso",
    "uso dual",
    "doble uso",
    "control de exportaciones estrategicas",
    "control de exportaciones",
    "control del comercio estrategico",
    "comercio estrategico",
    "bienes estrategicos",
    "materiales estrategicos",
    "tecnologia sensible",
    "transferencia de tecnologia sensible",
    "no proliferacion",
    "resolucion 1540",
    "resolucion 1718",
    "sanciones financieras dirigidas relativas a la proliferacion",
]


def consulta_camara_boletin_extendida(boletin: str) -> dict[str, Any] | None:
    """Ficha individual de Cámara con texto XML completo para pertinencia.

    La implementación base extrae campos estructurados. Esta versión conserva
    además todo el texto visible del nodo ``ProyectoLey``. Así una señal que no
    esté en el título pero sí en materias, descriptores u otros campos del XML
    puede participar en la clasificación.
    """
    b = m.normaliza_boletin(boletin)
    if not b or "-" not in b:
        return None
    url = m.url_camara("retornarProyectoLey", prmNumeroBoletin=b)
    try:
        raw, _, _ = m.descarga(url)
    except Exception as exc:
        m.cobertura("camara_boletin", error=f"{b}: {type(exc).__name__}: {exc}")
        return None
    raiz = m.parsea_xml(raw)
    if raiz is None:
        m.cobertura("camara_boletin", error=f"{b}: XML ilegible")
        return None
    nodo = raiz if m._tag(raiz) == "proyectoley" else (m.nodos(raiz, "proyectoley") or [None])[0]
    if nodo is None:
        m.cobertura("camara_boletin", error=f"{b}: sin nodo ProyectoLey")
        return None
    datos = m.parsea_proyecto_camara(nodo)
    if not datos.get("boletin"):
        datos["boletin"] = b
    texto_completo = m.texto_nodo(nodo)
    if texto_completo:
        datos["texto_camara_completo"] = texto_completo[:MAX_TEXTO_CAMARA]
    datos["fuente_texto_camara"] = url
    m.cobertura("camara_boletin", resultados=1)
    return datos


def campos_analizables_extendido(proy: dict[str, Any]) -> list[tuple[str, str]]:
    campos = list(_ORIG_CAMPOS_ANALIZABLES(proy))
    texto_camara = proy.get("texto_camara_completo") or ""
    if texto_camara:
        campos.append(("texto_camara", texto_camara))
    texto_documental = proy.get("texto_documental") or ""
    if texto_documental:
        campos.append(("documentos", texto_documental))
    return campos


def _fecha_candidata(datos: dict[str, Any]) -> datetime | None:
    return m.parsea_fecha(datos.get("fecha_ingreso"))


def _es_reciente(datos: dict[str, Any], dias: int) -> bool:
    fecha = _fecha_candidata(datos)
    if not fecha:
        return False
    return (m.ahora_cl().date() - fecha.date()).days <= dias


def preselecciona_extendido(
    candidatos: dict[str, dict[str, Any]], modo: str
) -> list[str]:
    """Añade una muestra de Cámara para detectar señales ocultas en títulos.

    El motor base preselecciona por título para proteger los servicios del
    Congreso. Esta capa suma proyectos recientes de Cámara aunque el título no
    puntúe, con límites explícitos. En conciliación también prioriza boletines
    de materias históricamente sensibles para la UAF.
    """
    seleccion = list(_ORIG_PRESELECCIONA(candidatos, modo))
    ya = set(seleccion)
    dias = DIAS_REVISION_NUEVOS if modo == "rapido" else DIAS_REVISION_CONCILIACION
    max_extra = (
        MAX_REVISION_CAMARA_RAPIDO
        if modo == "rapido"
        else MAX_REVISION_CAMARA_CONCILIACION
    )
    max_total = MAX_TOTAL_RAPIDO if modo == "rapido" else MAX_TOTAL_CONCILIACION

    extras: list[tuple[int, datetime, str]] = []
    for boletin, datos in candidatos.items():
        if boletin in ya:
            continue
        canales = set(datos.get("canales") or [])
        if "camara_anno" not in canales:
            continue
        fecha = _fecha_candidata(datos)
        if not fecha:
            continue
        reciente = _es_reciente(datos, dias)
        sensible = m.materia_boletin(boletin) in m.MATERIAS_SENSIBLES
        if not reciente and not (modo == "conciliacion" and sensible):
            continue
        # 0: reciente + sensible; 1: reciente; 2: sensible en conciliación.
        nivel = 0 if reciente and sensible else (1 if reciente else 2)
        extras.append((nivel, fecha, boletin))

    extras.sort(key=lambda x: (x[0], -x[1].timestamp()))
    cupo = max(0, min(max_extra, max_total - len(seleccion)))
    seleccion.extend(b for _, _, b in extras[:cupo])
    return seleccion[:max_total]


def _ultima_conciliacion_camara_hoy(estado: dict[str, Any]) -> bool:
    ultima = m.parsea_fecha(estado.get("ultima_conciliacion_camara"))
    return bool(ultima and ultima.date() == m.ahora_cl().date())


def _incorpora_candidato(
    candidatos: dict[str, dict[str, Any]], datos: dict[str, Any], canal: str
) -> None:
    b = m.normaliza_boletin(datos.get("boletin"))
    if not b or "-" not in b:
        return
    actual = candidatos.setdefault(b, {"boletin": b, "canales": []})
    if canal not in actual["canales"]:
        actual["canales"].append(canal)
    for clave, valor in datos.items():
        if clave in ("canales", "canal_descubrimiento") or valor in ("", None, [], {}):
            continue
        # La Cámara anual aporta fecha, título, autores y materias útiles para
        # preseleccionar; no pisa información ya obtenida por otro canal.
        actual.setdefault(clave, valor)


def descubre_extendido(
    modo: str, estado: dict[str, Any]
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    candidatos, resumen = _ORIG_DESCUBRE(modo, estado)

    if modo == "conciliacion":
        cobertura = m._COBERTURA.get("camara_anno") or {}
        if cobertura.get("resultados", 0) > 0:
            estado["ultima_conciliacion_camara"] = m.ahora_cl().isoformat()
        resumen["camara_conciliacion_diaria"] = "incluida_en_conciliacion_profunda"
        return candidatos, resumen

    if not m.CONSULTA_CAMARA or _ultima_conciliacion_camara_hoy(estado):
        resumen["camara_conciliacion_diaria"] = "ya_ejecutada_hoy"
        return candidatos, resumen
    if m.tiempo_agotado(240):
        resumen["camara_conciliacion_diaria"] = "omitida_por_presupuesto"
        return candidatos, resumen

    anno_actual = m.ahora_cl().year
    total = 0
    annos_consultados: list[int] = []
    for anno in range(anno_actual, anno_actual - ANNOS_CAMARA_DIARIO, -1):
        if m.tiempo_agotado(180):
            break
        resultados = m.consulta_camara_anno(anno)
        annos_consultados.append(anno)
        for datos in resultados:
            _incorpora_candidato(candidatos, datos, "camara_anno")
            total += 1

    if total > 0:
        estado["ultima_conciliacion_camara"] = m.ahora_cl().isoformat()
        resumen["camara_conciliacion_diaria"] = "ok"
    else:
        # No marcar como realizada: el siguiente barrido rápido vuelve a
        # intentarlo si el servicio estaba temporalmente indisponible.
        resumen["camara_conciliacion_diaria"] = "sin_resultados_reintentar"
    resumen["camara_diaria_resultados"] = total
    resumen["camara_diaria_annos"] = annos_consultados
    return candidatos, resumen


def aplica_extensiones() -> None:
    global _APLICADO
    if _APLICADO:
        return
    _APLICADO = True

    m.VERSION_MONITOR = VERSION_EXTENSION

    # Robustecer el eje ya existente de beneficiario final.
    bf = m.EJES_REGLAS.setdefault("beneficiario_final", [])
    m.EJES_REGLAS["beneficiario_final"] = list(dict.fromkeys([*bf, *TERMINOS_BENEFICIARIO_FINAL]))

    # Nuevo eje explícito de proliferación y uso dual.
    m.EJES_REGLAS["proliferacion_uso_dual"] = list(TERMINOS_PROLIFERACION_USO_DUAL)
    m.ETIQUETAS_EJES["proliferacion_uso_dual"] = (
        "Financiamiento de la proliferación y bienes de uso dual"
    )

    # Las ampliaciones de lexico_uaf.json se recargan en cada proceso.
    m._LEXICO_CACHE = None

    # Sustituir funciones mediante una capa aditiva; el resto del motor queda
    # intacto, incluida la lógica de correo.
    m.consulta_camara_boletin = consulta_camara_boletin_extendida
    m.campos_analizables = campos_analizables_extendido
    m.preselecciona = preselecciona_extendido
    m.descubre = descubre_extendido


aplica_extensiones()


if __name__ == "__main__":
    m.main()
