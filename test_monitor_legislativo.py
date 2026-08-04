#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pruebas offline del Monitor Legislativo UAF.

No tocan la red: usan fixtures XML que reproducen las respuestas de ambos
servicios, incluida una variante con nomenclatura distinta para comprobar que
el parser tolerante sobrevive a cambios de esquema.

Ejecución:  python test_monitor_legislativo.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta

import monitor_legislativo as m


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Variante A: nomenclatura en minúsculas dentro de <descripcion>.
SENADO_A = """<?xml version="1.0" encoding="ISO-8859-1"?>
<proyectos>
 <proyecto>
  <descripcion>
   <boletin>15975-25</boletin>
   <titulo>Crea el Subsistema de Inteligencia Economica y establece otras medidas para la prevencion y alerta de actividades que digan relacion con el crimen organizado</titulo>
   <fecha_ingreso>31/05/2023</fecha_ingreso>
   <iniciativa>Mensaje</iniciativa>
   <camara_origen>C.Diputados</camara_origen>
   <urgencia_actual>Suma</urgencia_actual>
   <etapa>Segundo tramite constitucional</etapa>
   <subetapa>Discusion particular</subetapa>
   <leynro></leynro>
   <link_mensaje_mocion>http://www.senado.cl/appsenado/index.php?mo=tramitacion&amp;ac=getDocto&amp;iddocto=12345</link_mensaje_mocion>
  </descripcion>
  <autores>
   <autor><PARLAMENTARIO>Ministerio de Hacienda</PARLAMENTARIO></autor>
  </autores>
  <materias>
   <materia><DESCRIPCION>LAVADO DE ACTIVOS</DESCRIPCION></materia>
   <materia><DESCRIPCION>SECRETO BANCARIO</DESCRIPCION></materia>
   <materia><DESCRIPCION>CRIMEN ORGANIZADO</DESCRIPCION></materia>
  </materias>
  <tramitacion>
   <tramite>
    <SESION>34/371</SESION>
    <FECHA>31/05/2023</FECHA>
    <DESCRIPCIONTRAMITE>Ingreso de proyecto</DESCRIPCIONTRAMITE>
    <ETAPDESCRIPCION>Primer tramite constitucional</ETAPDESCRIPCION>
    <CAMARATRAMITE>C.Diputados</CAMARATRAMITE>
   </tramite>
   <tramite>
    <SESION>12/372</SESION>
    <FECHA>18/06/2026</FECHA>
    <DESCRIPCIONTRAMITE>Primer informe de comision de Hacienda</DESCRIPCIONTRAMITE>
    <ETAPDESCRIPCION>Segundo tramite constitucional</ETAPDESCRIPCION>
    <CAMARATRAMITE>Senado</CAMARATRAMITE>
   </tramite>
  </tramitacion>
  <urgencias>
   <urgencia><TIPO>Suma</TIPO><FECHAINGRESO>10/06/2026</FECHAINGRESO></urgencia>
  </urgencias>
  <votaciones>
   <votacion><FECHA>17/06/2026</FECHA><TEMA>En general</TEMA><SI>28</SI><NO>3</NO><ABSTENCION>1</ABSTENCION></votacion>
  </votaciones>
  <comisiones>
   <comision>Comision de Hacienda</comision>
  </comisiones>
 </proyecto>
</proyectos>
"""

# Variante B: mismo contenido con otra nomenclatura y sin <descripcion>.
# Simula un ajuste del proveedor: el motor debe seguir leyendo.
SENADO_B = """<?xml version="1.0" encoding="utf-8"?>
<Proyectos>
 <Proyecto>
   <NroBoletin>18407-25</NroBoletin>
   <Nombre>Modifica diversos cuerpos legales, con el objeto de agravar las sanciones aplicables en materia de lavado de activos</Nombre>
   <FechaIngreso>2026-06-24T00:00:00</FechaIngreso>
   <TipoIniciativa>Mocion</TipoIniciativa>
   <Origen>Senado</Origen>
   <Urgencia>Sin urgencia</Urgencia>
   <EtapaActual>Primer tramite constitucional</EtapaActual>
   <SubEtapa>Primer informe de comision</SubEtapa>
   <Tramites>
     <Tramite>
       <Fecha>2026-06-24T00:00:00</Fecha>
       <Descripcion>Cuenta de proyecto. Pasa a Comision de Seguridad Publica</Descripcion>
       <Etapa>Primer tramite constitucional</Etapa>
       <Camara>Senado</Camara>
     </Tramite>
   </Tramites>
 </Proyecto>
</Proyectos>
"""

# Proyecto sin relación con el perímetro UAF: debe quedar descartado.
SENADO_IRRELEVANTE = """<?xml version="1.0" encoding="utf-8"?>
<proyectos>
 <proyecto>
  <descripcion>
   <boletin>18437-37</boletin>
   <titulo>Declara el 8 de octubre de cada anio como el Dia Nacional de Punta Angamos</titulo>
   <fecha_ingreso>07/07/2026</fecha_ingreso>
   <iniciativa>Mocion</iniciativa>
   <etapa>Primer tramite constitucional</etapa>
  </descripcion>
  <tramitacion>
   <tramite><FECHA>07/07/2026</FECHA><DESCRIPCIONTRAMITE>Ingreso de proyecto</DESCRIPCIONTRAMITE></tramite>
  </tramitacion>
 </proyecto>
</proyectos>
"""

# Respuesta de la Cámara, con namespace, tal como la documenta el WSDL.
CAMARA = """<?xml version="1.0" encoding="utf-8"?>
<ProyectoLey xmlns="http://opendata.camara.cl/camaradiputados/v1">
  <Id>16123</Id>
  <NumeroBoletin>15975-25</NumeroBoletin>
  <Nombre>Crea el Subsistema de Inteligencia Economica</Nombre>
  <FechaIngreso>2023-05-31T00:00:00</FechaIngreso>
  <TipoIniciativa>Mensaje</TipoIniciativa>
  <CamaraOrigen>Camara de Diputados</CamaraOrigen>
  <Autores />
  <MinisteriosPatrocinantes>
    <Ministerio><Id>7</Id><Nombre>Ministerio de Hacienda</Nombre></Ministerio>
    <Ministerio><Id>3</Id><Nombre>Ministerio del Interior y Seguridad Publica</Nombre></Ministerio>
  </MinisteriosPatrocinantes>
  <Materias>
    <Materia><Id>901</Id><Nombre>LAVADO DE ACTIVOS</Nombre></Materia>
    <Materia><Id>902</Id><Nombre>UNIDAD DE ANALISIS FINANCIERO</Nombre></Materia>
  </Materias>
  <Admisible>true</Admisible>
</ProyectoLey>
"""

# XML malformado con entidad suelta: el parser debe recuperarlo.
SENADO_SUCIO = """<?xml version="1.0"?>
<proyectos><proyecto><descripcion>
<boletin>16764-03</boletin>
<titulo>Fija un monto maximo para transacciones en dinero en efectivo & modifica la ley 19.913</titulo>
<etapa>Primer tramite constitucional</etapa>
<fecha_ingreso>05/06/2024</fecha_ingreso>
</descripcion></proyecto></proyectos>
"""


# ---------------------------------------------------------------------------
# Utilidades de prueba
# ---------------------------------------------------------------------------

FALLAS: list[str] = []
PRUEBAS = 0


def check(condicion: bool, descripcion: str, detalle: str = "") -> None:
    global PRUEBAS
    PRUEBAS += 1
    if condicion:
        print(f"  ok   {descripcion}")
    else:
        print(f"  FALLA {descripcion}" + (f"  ->  {detalle}" if detalle else ""))
        FALLAS.append(descripcion)


def lee_senado(xml: str) -> dict:
    raiz = m.parsea_xml(xml.encode("utf-8"))
    assert raiz is not None, "XML no parseable"
    nodo = m.nodos(raiz, "proyecto")[0]
    return m.parsea_proyecto_senado(nodo)


def lee_camara(xml: str) -> dict:
    raiz = m.parsea_xml(xml.encode("utf-8"))
    assert raiz is not None, "XML no parseable"
    return m.parsea_proyecto_camara(raiz)


# ---------------------------------------------------------------------------
# 1. Normalización de boletines
# ---------------------------------------------------------------------------

def prueba_boletines() -> None:
    print("\n1. Normalizacion de boletines")
    casos = [
        ("15975-25", "15975-25"), ("15975 - 25", "15975-25"),
        ("Boletin N° 15975-25", "15975-25"), ("15975–25", "15975-25"),
        ("16764-3", "16764-03"), ("8575-05", "8575-05"),
        ("sin numero", ""), ("", ""),
    ]
    for entrada, esperado in casos:
        obtenido = m.normaliza_boletin(entrada)
        check(obtenido == esperado, f"normaliza_boletin({entrada!r}) = {esperado!r}", obtenido)
    check(m.numero_boletin("15975-25") == "15975", "numero_boletin quita la materia")
    check(m.materia_boletin("15975-25") == "25", "materia_boletin extrae la materia")
    check(m.id_registro("15975-25") == m.id_registro("15975 - 25"),
          "el id es estable ante variaciones de formato")


# ---------------------------------------------------------------------------
# 2. Parser tolerante al esquema
# ---------------------------------------------------------------------------

def prueba_parser() -> None:
    print("\n2. Parser XML tolerante")
    a = lee_senado(SENADO_A)
    check(a["boletin"] == "15975-25", "variante A: boletin", a["boletin"])
    check("Inteligencia Economica" in a["titulo"], "variante A: titulo")
    check(a["urgencia"] == "Suma", "variante A: urgencia", a["urgencia"])
    check(a["etapa"].startswith("Segundo"), "variante A: etapa", a["etapa"])
    check(len(a["tramitacion"]) == 2, "variante A: dos tramites", str(len(a["tramitacion"])))
    check(a["tramitacion"][-1]["fecha"].startswith("2026-06-18"),
          "variante A: tramites ordenados por fecha", a["tramitacion"][-1]["fecha"])
    check(len(a["materias"]) == 3, "variante A: materias", str(a["materias"]))
    check(len(a["votaciones"]) == 1, "variante A: votaciones")
    check(a["comisiones"] and "Hacienda" in a["comisiones"][0], "variante A: comisiones")

    b = lee_senado(SENADO_B)
    check(b["boletin"] == "18407-25", "variante B (otra nomenclatura): boletin", b["boletin"])
    check("lavado de activos" in b["titulo"].lower(), "variante B: titulo")
    check(b["etapa"].startswith("Primer"), "variante B: etapa", b["etapa"])
    check(len(b["tramitacion"]) == 1, "variante B: tramite leido")
    check(b["fecha_ingreso"].startswith("2026-06-24"), "variante B: fecha ISO", b["fecha_ingreso"])

    c = lee_camara(CAMARA)
    check(c["boletin"] == "15975-25", "camara: boletin con namespace", c["boletin"])
    check(c["camara_id"] == "16123", "camara: id del proyecto", c["camara_id"])
    check(len(c["ministerios"]) == 2, "camara: ministerios patrocinantes")
    check("LAVADO DE ACTIVOS" in c["materias"], "camara: materias")

    sucio = m.parsea_xml(SENADO_SUCIO.encode("utf-8"))
    check(sucio is not None, "XML con ampersand suelto se recupera")
    if sucio is not None:
        d = m.parsea_proyecto_senado(m.nodos(sucio, "proyecto")[0])
        check(d["boletin"] == "16764-03", "XML sucio: boletin", d["boletin"])

    check(m.parsea_xml(b"no es xml") is None, "basura devuelve None sin excepcion")
    check(m.parsea_xml(b"") is None, "entrada vacia devuelve None")


# ---------------------------------------------------------------------------
# 3. Fechas
# ---------------------------------------------------------------------------

def prueba_fechas() -> None:
    print("\n3. Interpretacion de fechas")
    casos = [
        ("31/05/2023", (2023, 5, 31)),
        ("2026-06-24T00:00:00", (2026, 6, 24)),
        ("2026-06-24", (2026, 6, 24)),
        ("24 de junio de 2026", (2026, 6, 24)),
        ("7-7-2026", (2026, 7, 7)),
    ]
    for entrada, esperado in casos:
        dt = m.parsea_fecha(entrada)
        ok = dt is not None and (dt.year, dt.month, dt.day) == esperado
        check(ok, f"parsea_fecha({entrada!r})", str(dt))
    check(m.parsea_fecha("") is None, "fecha vacia devuelve None")
    check(m.parsea_fecha("32/13/2026") is None, "fecha imposible devuelve None")


# ---------------------------------------------------------------------------
# 4. Motor de pertinencia
# ---------------------------------------------------------------------------

def prueba_pertinencia() -> None:
    print("\n4. Motor de pertinencia")

    directo = m.evalua_pertinencia({
        "titulo": "Modifica la ley N 19.913 que crea la Unidad de Analisis Financiero",
    })
    check(directo["nivel"] == "directo", "mencion explicita de la 19.913 -> directo",
          directo["nivel"])

    estructural = m.evalua_pertinencia({
        "titulo": "Modifica diversos cuerpos legales, con el objeto de agravar las sanciones "
                  "aplicables en materia de lavado de activos",
        "materias": ["LAVADO DE ACTIVOS", "DELITOS BASE"],
    })
    check(estructural["nivel"] in ("estructural", "directo"),
          "lavado de activos sin nombrar la ley -> estructural", estructural["nivel"])
    check("lavado de activos" in estructural["evidencia"]["nucleo"],
          "evidencia registra el ancla de nucleo")

    secreto = m.evalua_pertinencia({
        "titulo": "Agiliza el levantamiento del secreto bancario con control judicial previo",
    })
    check(secreto["nivel"] in ("estructural", "sectorial"),
          "secreto bancario es pertinente", secreto["nivel"])

    sectorial = m.evalua_pertinencia({
        "titulo": "Regula el corretaje de propiedades y su ejercicio mediante plataformas digitales",
    })
    check(sectorial["nivel"] in ("sectorial", "seguimiento", "descartado"),
          "sector obligado sin ALA/CFT no escala a directo", sectorial["nivel"])
    check("inmobiliario" in sectorial["sectores"], "detecta el sector inmobiliario",
          str(sectorial["sectores"]))

    irrelevante = m.evalua_pertinencia({
        "titulo": "Declara el 8 de octubre de cada anio como el Dia Nacional de Punta Angamos",
    })
    check(irrelevante["nivel"] == "descartado", "efemeride descartada", irrelevante["nivel"])

    monumento = m.evalua_pertinencia({
        "titulo": "Autoriza erigir un monumento en memoria del ex Presidente de la Republica",
    })
    check(monumento["nivel"] == "descartado", "monumento descartado", monumento["nivel"])

    # Falso amigo: "UAF" como sigla suelta sin contexto financiero.
    falso = m.evalua_pertinencia({"titulo": "Reconoce a la agrupacion UAF de artesanos locales"})
    check(falso["nivel"] == "descartado", "sigla UAF sin contexto financiero no basta",
          falso["nivel"])

    # Coincidencia lexica estricta: no debe activarse por subcadena.
    subcadena = m.evalua_pertinencia({"titulo": "Regula el uso de bancos de plaza y mobiliario urbano"})
    check("banca_financiero" not in subcadena["sectores"] or subcadena["nivel"] == "descartado",
          "'bancos de plaza' no dispara el sector bancario", str(subcadena["sectores"]))

    efectivo = m.evalua_pertinencia({
        "titulo": "Establece un monto maximo permitido para transacciones en dinero en efectivo "
                  "y modifica la ley 19.913",
    })
    check(efectivo["nivel"] == "directo", "limite al efectivo con mencion a la ley -> directo",
          efectivo["nivel"])


# ---------------------------------------------------------------------------
# 5. Ejes de impacto
# ---------------------------------------------------------------------------

def prueba_ejes() -> None:
    print("\n5. Ejes de impacto institucional")
    casos = [
        ("Agiliza el levantamiento del secreto bancario", "secreto_bancario"),
        ("Incorpora delitos contra la propiedad industrial como delito base del lavado de activos",
         "delitos_base"),
        ("Regula a los proveedores de servicios de activos virtuales", "activos_virtuales"),
        ("Fija un limite a las operaciones en efectivo", "efectivo_bancarizacion"),
        ("Crea un registro de beneficiarios finales de sociedades", "beneficiario_final"),
        ("Fortalece la persecucion del crimen organizado", "crimen_organizado"),
        ("Perfecciona el decomiso y la recuperacion de activos", "decomiso_activos"),
    ]
    for titulo, eje in casos:
        ejes = m.clasifica_ejes({"titulo": titulo})
        check(eje in ejes, f"'{titulo[:45]}...' -> {eje}", str(ejes))


# ---------------------------------------------------------------------------
# 6. Estado procesal, urgencia y prioridad
# ---------------------------------------------------------------------------

def prueba_estado_procesal() -> None:
    print("\n6. Estado procesal y prioridad")
    check(m.normaliza_urgencia("Discusion inmediata") == "discusion inmediata", "urgencia inmediata")
    check(m.normaliza_urgencia("Suma") == "suma", "urgencia suma")
    check(m.normaliza_urgencia("SIMPLE URGENCIA") == "simple", "urgencia simple")
    check(m.normaliza_urgencia("") == "sin urgencia", "urgencia vacia")

    check(m.etapa_ordinal("Primer tramite constitucional") == 1, "ordinal primer tramite")
    check(m.etapa_ordinal("Segundo tramite constitucional") == 2, "ordinal segundo tramite")
    check(m.etapa_ordinal("Comision Mixta") == 4, "ordinal comision mixta")
    check(m.etapa_ordinal("Tramitacion terminada") == 7, "ordinal terminado")
    check(m.etapa_ordinal("Archivado") == 0, "ordinal archivado")

    check(m.esta_vigente({"etapa": "Primer tramite constitucional"}), "proyecto en tramite vigente")
    check(not m.esta_vigente({"etapa": "Publicado", "estado": "Publicado"}), "publicado no vigente")
    check(not m.esta_vigente({"etapa": "Archivado"}), "archivado no vigente")

    alto = m.calcula_prioridad({"nivel_impacto": "directo", "urgencia": "Discusion inmediata",
                                "etapa_ordinal": 3, "dias_sin_movimiento": 2, "vigente": True})
    bajo = m.calcula_prioridad({"nivel_impacto": "sectorial", "urgencia": "",
                                "etapa_ordinal": 1, "dias_sin_movimiento": 600, "vigente": True})
    check(alto["prioridad"] > bajo["prioridad"], "prioridad ordena por impacto y urgencia",
          f"{alto['prioridad']} vs {bajo['prioridad']}")
    check(alto["banda_prioridad"] in ("critica", "alta"), "banda alta para impacto directo urgente",
          alto["banda_prioridad"])

    cerrado = m.calcula_prioridad({"nivel_impacto": "directo", "urgencia": "Suma",
                                   "etapa_ordinal": 8, "dias_sin_movimiento": 10, "vigente": False})
    check(cerrado["prioridad"] < alto["prioridad"], "proyecto cerrado pierde prioridad")


# ---------------------------------------------------------------------------
# 7. Fusion de fuentes
# ---------------------------------------------------------------------------

def prueba_fusion() -> None:
    print("\n7. Fusion Senado + Camara")
    senado = lee_senado(SENADO_A)
    camara = lee_camara(CAMARA)
    fus = m.fusiona(senado, camara)
    check(fus["boletin"] == "15975-25", "boletin unificado")
    check(len(fus["tramitacion"]) == 2, "tramitacion viene del Senado",
          str(len(fus["tramitacion"])))
    check("Ministerio de Hacienda" in fus["ministerios"], "ministerios vienen de la Camara")
    check("UNIDAD DE ANALISIS FINANCIERO" in fus["materias"], "materias combinadas")
    check(fus["camara_id"] == "16123", "id de camara conservado")
    check(set(fus["fuentes"]) == {"senado", "camara"}, "trazabilidad de fuentes",
          str(fus["fuentes"]))

    solo_senado = m.fusiona(senado, None)
    check(solo_senado["fuentes"] == ["senado"], "funciona con una sola fuente")
    solo_camara = m.fusiona(None, camara)
    check(solo_camara["boletin"] == "15975-25", "funciona solo con Camara")


# ---------------------------------------------------------------------------
# 8. Deteccion de cambios
# ---------------------------------------------------------------------------

def prueba_huella() -> None:
    print("\n8. Deteccion de movimiento")
    base = lee_senado(SENADO_A)
    h1 = m.huella_tramitacion(base)

    igual = lee_senado(SENADO_A)
    igual["autores"] = ["orden distinto", "no importa"]
    igual["informes"] = [{"fecha": "2026-01-01"}]
    check(m.huella_tramitacion(igual) == h1,
          "cambios irrelevantes no producen falso movimiento")

    con_urgencia = lee_senado(SENADO_A)
    con_urgencia["urgencia"] = "Discusion inmediata"
    check(m.huella_tramitacion(con_urgencia) != h1, "cambio de urgencia se detecta")

    con_tramite = lee_senado(SENADO_A)
    con_tramite["tramitacion"] = con_tramite["tramitacion"] + [
        {"fecha": "2026-07-01T00:00:00", "descripcion": "Aprobado en particular"}]
    check(m.huella_tramitacion(con_tramite) != h1, "nuevo tramite se detecta")

    cambio_etapa = lee_senado(SENADO_A)
    cambio_etapa["etapa"] = "Tercer tramite constitucional"
    check(m.huella_tramitacion(cambio_etapa) != h1, "cambio de etapa se detecta")

    ultimo = m.ultimo_movimiento(base)
    check(ultimo is not None and ultimo.year == 2026 and ultimo.month == 6,
          "ultimo_movimiento toma la fecha mas reciente", str(ultimo))


# ---------------------------------------------------------------------------
# 9. Registro completo
# ---------------------------------------------------------------------------

def prueba_registro() -> None:
    print("\n9. Construccion del registro publicable")
    reg = m.construye_registro(m.fusiona(lee_senado(SENADO_A), lee_camara(CAMARA)))
    check(reg["nivel_impacto"] == "directo", "proyecto de inteligencia economica -> directo",
          reg["nivel_impacto"])
    check(reg["urgencia_clave"] == "suma", "urgencia normalizada", reg["urgencia_clave"])
    check(reg["etapa_ordinal"] == 2, "ordinal de etapa", str(reg["etapa_ordinal"]))
    check(reg["vigente"] is True, "proyecto vigente")
    check(reg["prioridad"] > 0, "prioridad calculada", str(reg["prioridad"]))
    check(reg["link_senado"].endswith("15975-25"), "enlace a la ficha del Senado",
          reg["link_senado"])
    check("prmBOLETIN=15975-25" in reg["link_camara"], "enlace a la ficha de la Camara",
          reg["link_camara"])
    check(reg["total_tramites"] == 2, "total de tramites")
    check(reg["sintesis"], "sintesis operativa generada", reg["sintesis"])
    check(len(reg["ejes"]) >= 2, "clasifica en varios ejes", str(reg["ejes_legibles"]))

    irrelevante = m.construye_registro(m.fusiona(lee_senado(SENADO_IRRELEVANTE), None))
    check(irrelevante["nivel_impacto"] == "descartado", "efemeride descartada en el registro",
          irrelevante["nivel_impacto"])


# ---------------------------------------------------------------------------
# 10. Preseleccion y metricas
# ---------------------------------------------------------------------------

def prueba_preseleccion() -> None:
    print("\n10. Preseleccion y metricas")
    candidatos = {
        "15975-25": {"boletin": "15975-25", "canales": ["senado_movimiento"],
                     "titulo": "Crea el Subsistema de Inteligencia Economica contra el crimen organizado y el lavado de activos"},
        "18437-37": {"boletin": "18437-37", "canales": ["senado_movimiento"],
                     "titulo": "Declara el Dia Nacional de Punta Angamos"},
        "99999-99": {"boletin": "99999-99", "canales": ["semilla"], "es_semilla": True},
        "18488-07": {"boletin": "18488-07", "canales": ["cartera"]},
        "17000-13": {"boletin": "17000-13", "canales": ["camara_anno"], "titulo": ""},
    }
    sel = m.preselecciona(candidatos, "rapido")
    check("15975-25" in sel, "proyecto pertinente preseleccionado")
    check("18437-37" not in sel, "efemeride filtrada antes de gastar red")
    check("99999-99" in sel, "semilla siempre consultada")
    check("18488-07" in sel, "cartera siempre reconsultada")
    check("17000-13" in sel, "sin titulo conocido no se descarta a ciegas")
    check(sel.index("99999-99") < 2 or sel.index("18488-07") < 2,
          "semillas y cartera encabezan el orden", str(sel[:3]))

    ahora = m.ahora_cl()
    proyectos = [
        m.construye_registro(m.fusiona(lee_senado(SENADO_A), lee_camara(CAMARA))),
        m.construye_registro(m.fusiona(lee_senado(SENADO_B), None)),
    ]
    met = m.calcula_metricas(proyectos, ahora)
    check(met["total"] == 2, "metrica total")
    check(met["vigentes"] == 2, "metrica vigentes")
    check(met["impacto_directo"] >= 1, "metrica impacto directo", str(met["impacto_directo"]))
    check(met["con_urgencia"] == 1, "metrica con urgencia", str(met["con_urgencia"]))
    check(any(p["ordinal"] == 2 for p in met["pipeline"]), "pipeline por etapa",
          str(met["pipeline"]))
    check(met["por_eje"] and met["por_eje"][0]["etiqueta"], "ranking de ejes etiquetado")


# ---------------------------------------------------------------------------
# 11. Construccion de URLs
# ---------------------------------------------------------------------------

def prueba_urls() -> None:
    print("\n11. Construccion de URLs de servicio")
    u = m.url_senado_boletin("15975-25")
    check(u.endswith("boletin=15975"), "el Senado exige el correlativo sin materia", u)
    f = m.url_senado_fecha(datetime(2026, 7, 1))
    check("fecha=01%2F07%2F2026" in f, "fecha del Senado en DD/MM/AAAA codificada", f)
    c = m.url_camara("retornarProyectoLey", prmNumeroBoletin="15975-25")
    check(c.endswith("retornarProyectoLey?prmNumeroBoletin=15975-25"),
          "la Camara exige el boletin completo", c)
    check(m.url_camara("retornarMocionesXAnno", prmAnno=2026).endswith("prmAnno=2026"),
          "consulta anual de mociones")


# ---------------------------------------------------------------------------
# 12. Seguridad de red
# ---------------------------------------------------------------------------

def prueba_seguridad() -> None:
    print("\n12. Barreras de red")
    check(not m.url_publica("http://127.0.0.1/x"), "bloquea loopback")
    check(not m.url_publica("http://192.168.0.1/x"), "bloquea red privada")
    check(not m.url_publica("file:///etc/passwd"), "bloquea esquema no http")
    check(not m.url_publica("http://localhost/x"), "bloquea localhost")
    check(m.dominio_url("https://www.senado.cl/x") == "senado.cl", "normaliza dominio con www")


# ---------------------------------------------------------------------------
# 13. Proyectos ómnibus: el caso 18216-05
# ---------------------------------------------------------------------------

def prueba_omnibus() -> None:
    print("\n13. Proyectos omnibus y revision manual")

    OMNIBUS = "Para la reconstruccion nacional y el desarrollo economico y social"

    # El titulo no da ninguna senal: el motor NO debe pretender clasificarlo.
    pert = m.evalua_pertinencia({"titulo": OMNIBUS})
    check(pert["nivel"] == "descartado", "el titulo omnibus no puntua por si solo",
          pert["nivel"])

    # Pero debe reconocerse como contenedor, no como descripcion de contenido.
    check(m.titulo_generico(OMNIBUS), "detecta el titulo omnibus")
    check(m.titulo_generico("Modifica diversos cuerpos legales"), "detecta encabezado vacio")
    check(m.titulo_generico("Ley de Presupuestos para el sector publico"), "detecta ley de presupuestos")
    check(m.titulo_generico("Reforma tributaria"), "detecta titulo corto")
    check(not m.titulo_generico(
        "Modifica diversos cuerpos legales, con el objeto de agravar las sanciones "
        "aplicables en materia de lavado de activos"),
        "un titulo informativo NO es generico")
    check(not m.titulo_generico(
        "Declara el 8 de octubre de cada anio como el Dia Nacional de Punta Angamos"),
        "una efemeride con titulo descriptivo NO es generica")

    # Antes de la correccion, este boletin se descartaba sin consultarlo nunca.
    candidatos = {
        "18216-05": {"boletin": "18216-05", "canales": ["senado_movimiento"], "titulo": OMNIBUS},
        "18437-37": {"boletin": "18437-37", "canales": ["senado_movimiento"],
                     "titulo": "Declara el 8 de octubre de cada anio como el Dia Nacional de Punta Angamos"},
        "15975-25": {"boletin": "15975-25", "canales": ["senado_movimiento"],
                     "titulo": "Crea el Subsistema de Inteligencia Economica contra el lavado de activos"},
    }
    sel = m.preselecciona(candidatos, "rapido")
    check("18216-05" in sel, "el omnibus llega a consulta pese a puntuar cero")
    check("18437-37" not in sel, "la efemeride sigue descartada sin gastar red")
    check(sel.index("15975-25") < sel.index("18216-05"),
          "lo pertinente por titulo se consulta antes que el omnibus", str(sel))

    # El registro queda marcado para revision, no clasificado a la fuerza.
    reg = m.construye_registro({
        "boletin": "18216-05", "titulo": OMNIBUS, "iniciativa": "Mensaje",
        "urgencia": "Suma", "etapa": "Comision Mixta",
        "fecha_ingreso": "22/04/2026",
        "tramitacion": [{"fecha": "2026-07-21", "descripcion": "Pasa a comision mixta"}],
    })
    check(reg["requiere_revision_manual"] is True,
          "el omnibus se marca para revision manual")
    check(reg["etapa_ordinal"] == 4, "ordinal de comision mixta", str(reg["etapa_ordinal"]))

    # Un proyecto claramente pertinente no debe quedar marcado como dudoso.
    claro = m.construye_registro({
        "boletin": "15975-25",
        "titulo": "Crea el Subsistema de Inteligencia Economica y establece medidas "
                  "contra el lavado de activos y el crimen organizado",
        "etapa": "Segundo tramite constitucional", "urgencia": "Suma",
    })
    check(claro["requiere_revision_manual"] is False,
          "un proyecto de impacto directo no requiere revision manual")

    # La metrica expone cuantos quedaron pendientes de criterio humano.
    met = m.calcula_metricas([reg, claro], m.ahora_cl())
    check(met["requieren_revision_manual"] == 1, "metrica de revision manual",
          str(met["requieren_revision_manual"]))


# ---------------------------------------------------------------------------

def main() -> int:
    print("=" * 72)
    print("PRUEBAS OFFLINE · Monitor Legislativo UAF", m.VERSION_MONITOR)
    print("=" * 72)
    for fn in (prueba_boletines, prueba_parser, prueba_fechas, prueba_pertinencia,
               prueba_ejes, prueba_estado_procesal, prueba_fusion, prueba_huella,
               prueba_registro, prueba_preseleccion, prueba_urls, prueba_seguridad,
               prueba_omnibus):
        fn()
    print("\n" + "=" * 72)
    if FALLAS:
        print(f"RESULTADO: {PRUEBAS - len(FALLAS)}/{PRUEBAS} pruebas correctas · {len(FALLAS)} FALLAS")
        for f in FALLAS:
            print(f"  - {f}")
        return 1
    print(f"RESULTADO: {PRUEBAS}/{PRUEBAS} pruebas correctas")
    return 0


if __name__ == "__main__":
    sys.exit(main())
