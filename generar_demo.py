#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Genera un ``datos.json`` de demostración sin tocar la red.

Sirve para revisar el tablero antes de la primera corrida real y para
comprobar que el formato de salida y el dashboard están acoplados.
Los boletines y títulos son reales; los estados procesales son ilustrativos
y NO deben usarse como información oficial.

Uso:  python generar_demo.py
"""

from __future__ import annotations

import json
from datetime import timedelta

import monitor_legislativo as m

HOY = m.ahora_cl()


def dias(n: int) -> str:
    return (HOY - timedelta(days=n)).isoformat()


CASOS = [
    {
        "boletin": "15975-25",
        "titulo": "Crea el Subsistema de Inteligencia Económica y establece otras medidas para la "
                  "prevención y alerta de actividades que digan relación con el crimen organizado",
        "fecha_ingreso": dias(1160), "iniciativa": "Mensaje", "camara_origen": "C.Diputados",
        "urgencia": "Suma", "etapa": "Segundo trámite constitucional",
        "subetapa": "Discusión particular", "camara_id": "16123",
        "materias": ["LAVADO DE ACTIVOS", "SECRETO BANCARIO", "CRIMEN ORGANIZADO",
                     "UNIDAD DE ANALISIS FINANCIERO"],
        "ministerios": ["Ministerio de Hacienda", "Ministerio del Interior y Seguridad Pública"],
        "comisiones": ["Comisión de Hacienda", "Comisión de Seguridad Pública"],
        "tramitacion": [
            {"fecha": dias(1160), "descripcion": "Ingreso de proyecto",
             "etapa": "Primer trámite constitucional", "camara": "C.Diputados"},
            {"fecha": dias(210), "descripcion": "Aprobado en general y particular. Pasa al Senado",
             "etapa": "Primer trámite constitucional", "camara": "C.Diputados"},
            {"fecha": dias(4), "descripcion": "Primer informe de Comisión de Hacienda",
             "etapa": "Segundo trámite constitucional", "camara": "Senado"},
        ],
        "votaciones": [{"fecha": dias(210), "tema": "En general", "si": "112", "no": "8", "abstencion": "3"}],
    },
    {
        "boletin": "18407-25",
        "titulo": "Modifica diversos cuerpos legales, con el objeto de agravar las sanciones "
                  "aplicables en materia de lavado de activos",
        "fecha_ingreso": dias(40), "iniciativa": "Moción", "camara_origen": "Senado",
        "urgencia": "", "etapa": "Primer trámite constitucional",
        "subetapa": "Primer informe de comisión",
        "materias": ["LAVADO DE ACTIVOS", "DELITOS BASE"],
        "comisiones": ["Comisión de Seguridad Pública"],
        "tramitacion": [
            {"fecha": dias(40), "descripcion": "Cuenta de proyecto. Pasa a Comisión de Seguridad Pública",
             "etapa": "Primer trámite constitucional", "camara": "Senado"},
        ],
    },
    {
        "boletin": "18373-07",
        "titulo": "Modifica la legislación para agilizar el levantamiento del secreto bancario "
                  "con control judicial previo en investigaciones por lavado de dinero",
        "fecha_ingreso": dias(95), "iniciativa": "Moción", "camara_origen": "C.Diputados",
        "urgencia": "Simple", "etapa": "Primer trámite constitucional",
        "subetapa": "Comisión de Constitución",
        "materias": ["SECRETO BANCARIO", "LAVADO DE ACTIVOS"],
        "comisiones": ["Comisión de Constitución, Legislación y Justicia"],
        "tramitacion": [
            {"fecha": dias(95), "descripcion": "Ingreso de proyecto",
             "etapa": "Primer trámite constitucional", "camara": "C.Diputados"},
            {"fecha": dias(12), "descripcion": "Informe de Comisión de Constitución",
             "etapa": "Primer trámite constitucional", "camara": "C.Diputados"},
        ],
    },
    {
        "boletin": "16764-03",
        "titulo": "Establece un monto máximo permitido para las transacciones en dinero en efectivo "
                  "y modifica la ley N° 19.913",
        "fecha_ingreso": dias(420), "iniciativa": "Moción", "camara_origen": "Senado",
        "urgencia": "", "etapa": "Primer trámite constitucional",
        "subetapa": "Comisión de Economía",
        "materias": ["DINERO EN EFECTIVO", "BANCARIZACION", "LAVADO DE ACTIVOS"],
        "comisiones": ["Comisión de Economía"],
        "tramitacion": [
            {"fecha": dias(420), "descripcion": "Ingreso de proyecto",
             "etapa": "Primer trámite constitucional", "camara": "Senado"},
            {"fecha": dias(245), "descripcion": "Refundido con boletín 15462-03",
             "etapa": "Primer trámite constitucional", "camara": "Senado"},
        ],
    },
    {
        "boletin": "18080-03",
        "titulo": "Modifica diversos cuerpos legales, con el objeto de fortalecer la transparencia "
                  "y trazabilidad financiera en las operaciones prendarias",
        "fecha_ingreso": dias(189), "iniciativa": "Moción", "camara_origen": "Senado",
        "urgencia": "", "etapa": "Primer trámite constitucional",
        "materias": ["OPERACIONES PRENDARIAS", "TRAZABILIDAD FINANCIERA"],
        "tramitacion": [
            {"fecha": dias(189), "descripcion": "Ingreso de proyecto",
             "etapa": "Primer trámite constitucional", "camara": "Senado"},
        ],
    },
    {
        "boletin": "18488-07",
        "titulo": "Modifica diversos cuerpos legales en materia de persecución penal y patrimonial, "
                  "y tipifica nuevos delitos para combatir el crimen organizado",
        "fecha_ingreso": dias(13), "iniciativa": "Mensaje", "camara_origen": "C.Diputados",
        "urgencia": "Discusión inmediata", "etapa": "Primer trámite constitucional",
        "subetapa": "Comisión de Seguridad Ciudadana",
        "materias": ["CRIMEN ORGANIZADO", "DECOMISO", "LAVADO DE ACTIVOS"],
        "ministerios": ["Ministerio del Interior y Seguridad Pública"],
        "tramitacion": [
            {"fecha": dias(13), "descripcion": "Ingreso de proyecto. Pasa a Comisión de Seguridad Ciudadana",
             "etapa": "Primer trámite constitucional", "camara": "C.Diputados"},
            {"fecha": dias(2), "descripcion": "Hace presente la urgencia calificada de discusión inmediata",
             "etapa": "Primer trámite constitucional", "camara": "C.Diputados"},
        ],
    },
    {
        "boletin": "12234-02",
        "titulo": "Fortalece y moderniza el sistema de inteligencia del Estado",
        "fecha_ingreso": dias(2820), "iniciativa": "Mensaje", "camara_origen": "Senado",
        "urgencia": "", "etapa": "Tramitación terminada", "subetapa": "Publicado",
        "ley_numero": "21.821", "estado": "Publicado",
        "materias": ["INTELIGENCIA DEL ESTADO"],
        "tramitacion": [
            {"fecha": dias(2820), "descripcion": "Ingreso de proyecto",
             "etapa": "Primer trámite constitucional", "camara": "Senado"},
            {"fecha": dias(300), "descripcion": "Publicada la Ley N° 21.821",
             "etapa": "Tramitación terminada", "camara": ""},
        ],
    },
    {
        "boletin": "18369-07",
        "titulo": "Modifica la Ordenanza de Aduanas, con el objeto de aumentar las penas asignadas "
                  "al delito de contrabando de tabaco y sus derivados",
        "fecha_ingreso": dias(48), "iniciativa": "Moción", "camara_origen": "Senado",
        "urgencia": "", "etapa": "Primer trámite constitucional",
        "materias": ["CONTRABANDO", "DELITOS ADUANEROS"],
        "tramitacion": [
            {"fecha": dias(48), "descripcion": "Ingreso de proyecto",
             "etapa": "Primer trámite constitucional", "camara": "Senado"},
        ],
    },
    {
        "boletin": "17700-05",
        "titulo": "Regula a los proveedores de servicios de activos virtuales e incorpora "
                  "obligaciones de debida diligencia y reporte de operaciones sospechosas",
        "fecha_ingreso": dias(330), "iniciativa": "Mensaje", "camara_origen": "C.Diputados",
        "urgencia": "Suma", "etapa": "Tercer trámite constitucional",
        "subetapa": "Discusión de modificaciones",
        "materias": ["ACTIVOS VIRTUALES", "CRIPTOACTIVOS", "SUJETOS OBLIGADOS"],
        "ministerios": ["Ministerio de Hacienda"],
        "tramitacion": [
            {"fecha": dias(330), "descripcion": "Ingreso de proyecto",
             "etapa": "Primer trámite constitucional", "camara": "C.Diputados"},
            {"fecha": dias(120), "descripcion": "Aprobado. Pasa al Senado",
             "etapa": "Segundo trámite constitucional", "camara": "Senado"},
            {"fecha": dias(9), "descripcion": "Oficio con modificaciones a Cámara de origen",
             "etapa": "Tercer trámite constitucional", "camara": "C.Diputados"},
        ],
    },
    {
        "boletin": "16808-25",
        "titulo": "Introduce reformas para perseguir el lavado de activos asociado al comercio "
                  "ilegal y al contrabando urbano",
        "fecha_ingreso": dias(560), "iniciativa": "Moción", "camara_origen": "C.Diputados",
        "urgencia": "", "etapa": "Primer trámite constitucional",
        "subetapa": "Comisión de Gobierno Interior",
        "materias": ["LAVADO DE ACTIVOS", "COMERCIO ILEGAL"],
        "tramitacion": [
            {"fecha": dias(560), "descripcion": "Ingreso de proyecto",
             "etapa": "Primer trámite constitucional", "camara": "C.Diputados"},
            {"fecha": dias(430), "descripcion": "Cuenta de proyecto. Pasa a Comisión de Gobierno Interior",
             "etapa": "Primer trámite constitucional", "camara": "C.Diputados"},
        ],
    },
]

NOVEDADES = {"15975-25": "movimiento", "18488-07": "urgencia", "18407-25": "nuevo"}


def main() -> None:
    registros = []
    for caso in CASOS:
        datos = dict(caso)
        for t in datos.get("tramitacion", []):
            f = m.parsea_fecha(t.get("fecha"))
            t["fecha_legible"] = m.fecha_legible(f)
        for v in datos.get("votaciones", []):
            f = m.parsea_fecha(v.get("fecha"))
            v["fecha_legible"] = m.fecha_legible(f)
        datos.setdefault("autores", [])
        datos.setdefault("fuentes", ["senado", "camara"])
        reg = m.construye_registro(datos)
        reg["novedad"] = NOVEDADES.get(reg["boletin"], "")
        if reg["novedad"]:
            reg["novedad_detectada"] = HOY.isoformat()
        registros.append(reg)

    registros.sort(key=lambda r: -(r.get("prioridad") or 0))
    metricas = m.calcula_metricas(registros, HOY)

    salida = {
        "generado": HOY.isoformat(),
        "generado_legible": HOY.strftime("%d/%m/%Y %H:%M"),
        "version_motor": m.VERSION_MONITOR + " · DEMOSTRACIÓN",
        "modo_ejecucion": "demo",
        "metricas": metricas,
        "proyectos": registros,
        "descartados": [
            {"boletin": "18437-37", "titulo": "Declara el 8 de octubre como el Día Nacional de Punta Angamos",
             "puntaje_pertinencia": 0.0, "motivo": "bajo umbral de pertinencia"},
            {"boletin": "18272-37", "titulo": "Declara el trabajo de las mujeres descoladoras como patrimonio cultural",
             "puntaje_pertinencia": 0.0, "motivo": "bajo umbral de pertinencia"},
        ],
        "novedades": sum(1 for r in registros if r.get("novedad")),
        "catalogos": {
            "ejes": m.ETIQUETAS_EJES, "sectores": m.ETIQUETAS_SECTORES,
            "impacto": m.ETIQUETAS_IMPACTO, "urgencia": m.ETIQUETAS_URGENCIA,
        },
        "auditoria": {
            "modo": "demo (datos ilustrativos, sin consulta a los servicios)",
            "candidatos_descubiertos": len(CASOS), "boletines_consultados": len(CASOS),
            "fichas_obtenidas": len(CASOS), "consultas_fallidas": 0,
            "registros_publicados": len(registros),
            "descartados_por_pertinencia": 2,
            "novedades_corrida": sum(1 for r in registros if r.get("novedad")),
            "nuevos_en_cartera": 1, "con_movimiento": 1, "cambios_urgencia": 1,
            "segundos_corrida": 0.0,
        },
    }

    salida_path = m.BASE / "datos.json"
    salida_path.write_text(
        json.dumps(salida, ensure_ascii=False, indent=1, default=m.json_default),
        encoding="utf-8")
    print(f"Generado {salida_path} con {len(registros)} proyectos de demostración.")
    for r in registros[:6]:
        print(f"  {r['boletin']:>10}  {r['banda_prioridad']:<8} "
              f"prio={r['prioridad']:<6} {r['nivel_impacto']:<12} {r['titulo'][:58]}")


if __name__ == "__main__":
    main()
