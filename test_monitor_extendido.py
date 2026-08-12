#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pruebas offline de las extensiones de pertinencia y Cámara."""

from __future__ import annotations

from datetime import timedelta

import monitor_extendido as ext

m = ext.m

FALLAS: list[str] = []
PRUEBAS = 0


def check(condicion: bool, descripcion: str, detalle: str = "") -> None:
    global PRUEBAS
    PRUEBAS += 1
    if condicion:
        print(f"  ok   {descripcion}")
    else:
        print(f"  FALLA {descripcion}" + (f" -> {detalle}" if detalle else ""))
        FALLAS.append(descripcion)


def prueba_beneficiario_final() -> None:
    print("\n1. Beneficiario final")
    casos = [
        "Crea un registro de beneficiarios finales de sociedades",
        "Obliga a informar al titular real de las personas juridicas",
        "Establece transparencia societaria y cadena de propiedad",
        "Exige identificar a la persona natural que ejerce el control final",
    ]
    for texto in casos:
        pert = m.evalua_pertinencia({"titulo": texto})
        ejes = m.clasifica_ejes({"titulo": texto})
        check(pert["nivel"] != "descartado", f"detecta pertinencia: {texto}", str(pert))
        check("beneficiario_final" in ejes, f"clasifica eje beneficiario final: {texto}", str(ejes))


def prueba_uso_dual() -> None:
    print("\n2. Uso dual y proliferación")
    casos = [
        "Regula la exportacion de bienes y tecnologias de uso dual",
        "Establece controles para prevenir el financiamiento de la proliferacion de armas de destruccion masiva",
        "Crea un sistema de control del comercio estrategico de bienes de doble uso",
        "Fortalece las sanciones financieras dirigidas relativas a la proliferacion",
        "Crea la Comision de Comercio Estrategico y regula la exportacion de material de uso dual y de defensa",
    ]
    for texto in casos:
        pert = m.evalua_pertinencia({"titulo": texto})
        ejes = m.clasifica_ejes({"titulo": texto})
        check(pert["nivel"] != "descartado", f"detecta pertinencia: {texto}", str(pert))
        check("proliferacion_uso_dual" in ejes, f"clasifica eje uso dual: {texto}", str(ejes))


def prueba_texto_camara_oculto() -> None:
    print("\n3. Señales ocultas en texto Cámara")
    proyecto = {
        "titulo": "Moderniza diversas disposiciones societarias",
        "texto_camara_completo": "La sociedad debera identificar e informar a su beneficiario final.",
    }
    check(m.evalua_pertinencia(proyecto)["nivel"] != "descartado",
          "beneficiario final se detecta fuera del título")
    check("beneficiario_final" in m.clasifica_ejes(proyecto),
          "beneficiario final oculto alimenta su eje")

    proyecto2 = {
        "titulo": "Moderniza el regimen de comercio exterior",
        "texto_camara_completo": "Se someten a licencia los bienes de uso dual y el control del comercio estrategico.",
    }
    check(m.evalua_pertinencia(proyecto2)["nivel"] != "descartado",
          "uso dual se detecta fuera del título")
    check("proliferacion_uso_dual" in m.clasifica_ejes(proyecto2),
          "uso dual oculto alimenta su eje")


def prueba_conciliacion_diaria() -> None:
    print("\n4. Control de conciliación diaria Cámara")
    hoy = m.ahora_cl()
    check(ext._ultima_conciliacion_camara_hoy({"ultima_conciliacion_camara": hoy.isoformat()}),
          "no repite conciliación el mismo día")
    ayer = hoy - timedelta(days=1)
    check(not ext._ultima_conciliacion_camara_hoy({"ultima_conciliacion_camara": ayer.isoformat()}),
          "vuelve a conciliar al cambiar de día")


def prueba_reglas_correo_intactas() -> None:
    print("\n5. Correo")
    check(m.envia_correo.__module__ == "monitor_legislativo",
          "la función de correo sigue siendo la original", m.envia_correo.__module__)
    check(m.nivel_cartera.__module__ == "monitor_legislativo",
          "las reglas de nivel de cartera siguen siendo las originales", m.nivel_cartera.__module__)


def prueba_casos_control_descubrimiento() -> None:
    print("\n6. Casos de control temático")
    semillas = {s.get("boletin"): s for s in m.carga_semillas()}
    check("14773-02" in semillas,
          "14773-02 queda en seguimiento permanente para uso dual", str(sorted(semillas)))
    check("16135-07" in semillas,
          "16135-07 queda en seguimiento permanente para beneficiario final", str(sorted(semillas)))

    uso_dual = {
        "titulo": "Crea la Comisión de Comercio Estratégico y regula la exportación de material de uso dual y de defensa"
    }
    bf = {
        "titulo": "Modifica la Carta Fundamental, con el objeto de crear el Registro de Beneficiarios Finales de Fondos Públicos"
    }
    check("proliferacion_uso_dual" in m.clasifica_ejes(uso_dual),
          "14773-02 activa el eje de proliferación y uso dual")
    check(m.evalua_pertinencia(uso_dual)["nivel"] != "descartado",
          "14773-02 supera el umbral de pertinencia")
    check("beneficiario_final" in m.clasifica_ejes(bf),
          "16135-07 activa el eje de beneficiario final")
    check(m.evalua_pertinencia(bf)["nivel"] != "descartado",
          "16135-07 supera el umbral de pertinencia")


if __name__ == "__main__":
    prueba_beneficiario_final()
    prueba_uso_dual()
    prueba_texto_camara_oculto()
    prueba_conciliacion_diaria()
    prueba_reglas_correo_intactas()
    prueba_casos_control_descubrimiento()
    print(f"\n{PRUEBAS} comprobaciones · {len(FALLAS)} fallas")
    if FALLAS:
        raise SystemExit(1)
