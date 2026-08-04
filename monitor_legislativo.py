#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Monitor Legislativo UAF Chile · motor v1.0

Vigila la tramitación de proyectos de ley en el Congreso Nacional que pueden
impactar las competencias de la Unidad de Análisis Financiero (Ley N° 19.913).

A diferencia del Monitor de prensa, aquí las "fuentes" no son medios sino los
servicios de datos abiertos oficiales del Congreso:

  · Senado    https://tramitacion.senado.cl/wspublico/tramitacion.php
              ?fecha=DD/MM/AAAA   -> boletines con movimiento desde esa fecha
              ?boletin=NNNNN      -> ficha completa de tramitación
  · Cámara    https://opendata.camara.cl/camaradiputados/WServices/WSLegislativo.asmx
              /retornarProyectoLey?prmNumeroBoletin=NNNNN-NN
              /retornarMocionesXAnno?prmAnno=AAAA
              /retornarMensajesXAnno?prmAnno=AAAA

Modos:
  rapido         Barrido incremental para ejecutar cada 1-6 horas.
  conciliacion   Barrido profundo del año legislativo y de la cartera completa.

Solo biblioteca estándar de Python. Genera ``datos.json`` para el dashboard.

Comandos principales:
  python monitor_legislativo.py --modo rapido
  python monitor_legislativo.py --modo conciliacion
  python monitor_legislativo.py --probar-boletin 15975-25
  python monitor_legislativo.py --probar-pertinencia "texto del proyecto"
  python monitor_legislativo.py --validar-fuentes
  python monitor_legislativo.py --diagnostico
"""

from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import html as html_mod
import ipaddress
import json
import os
import re
import socket
import smtplib
import ssl
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
import xml.etree.ElementTree as ET
import zlib
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None


# ---------------------------------------------------------------------------
# Serialización JSON segura
# ---------------------------------------------------------------------------


def json_default(obj: Any) -> Any:
    """Convierte tipos Python no nativos de JSON a valores persistibles."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, set):
        return sorted(obj)
    raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")


# ---------------------------------------------------------------------------
# Rutas y configuración
# ---------------------------------------------------------------------------

BASE = Path(__file__).resolve().parent
SALIDA = BASE / "datos.json"
ESTADO = BASE / ".monitor_estado.json"
BITACORA = BASE / "monitor.log"
CONFIG = BASE / "config.json"
FUENTES_ARCHIVO = BASE / "fuentes_legislativas.json"
LEXICO_ARCHIVO = BASE / "lexico_uaf.json"
SEMILLAS_ARCHIVO = BASE / "boletines_semilla.json"
EXCLUSIONES_ARCHIVO = BASE / "exclusiones_boletines.json"

VERSION_MONITOR = "1.0.0-tramitacion-legislativa"
ESQUEMA_ESTADO = 1
TZ_CL = ZoneInfo("America/Santiago") if ZoneInfo else timezone(timedelta(hours=-4))
UA = "Mozilla/5.0 (compatible; MonitorLegislativoUAF/1.0; +https://github.com/)"
UA_ROBOTS = "MonitorLegislativoUAF"

CONFIG_EJEMPLO = {
    "correo": {
        "activo": False,
        "servidor": "smtp.gmail.com",
        "puerto": 587,
        "seguridad": "starttls",
        "usuario": "tu.correo@gmail.com",
        "clave": "clave-de-aplicacion",
        "remitente_nombre": "Monitor Legislativo UAF",
        "destinatarios": ["tu.correo@gmail.com"],
        "minimo_para_avisar": 1,
        "silencio_minutos": 0,
        "solo_impacto_directo": False,
        "avisar_solo_con_urgencia": False,
    }
}


def env_bool(nombre: str, defecto: bool = False) -> bool:
    valor = os.getenv(nombre)
    if valor is None or not valor.strip():
        return defecto
    return valor.strip().lower() in {"1", "true", "si", "sí", "yes", "on"}


def env_int(nombre: str, defecto: int) -> int:
    valor = os.getenv(nombre)
    if valor is None or not valor.strip():
        return defecto
    try:
        return int(valor)
    except ValueError:
        return defecto


# El servicio del Senado limita la consulta por fecha a un mes hacia atrás.
VENTANA_MOVIMIENTO_RAPIDO = min(30, env_int("MONITOR_VENTANA_RAPIDO", 7))
VENTANA_MOVIMIENTO_CONCILIACION = min(30, env_int("MONITOR_VENTANA_CONCILIACION", 30))
RETENCION_HISTORIAL_DIAS = env_int("MONITOR_RETENCION_DIAS", 900)
TIMEOUT = env_int("MONITOR_TIMEOUT", 25)
MAX_BYTES = env_int("MONITOR_MAX_BYTES", 12_000_000)
HILOS = max(1, min(8, env_int("MONITOR_HILOS", 4)))
RESPETA_ROBOTS = env_bool("MONITOR_RESPETA_ROBOTS", True)
INTERVALO_HOST = float(os.getenv("MONITOR_INTERVALO_HOST", "1.1") or 1.1)
PRESUPUESTO_SEGUNDOS = env_int("MONITOR_PRESUPUESTO_SEG", 900)
MAX_ENRIQUECER_RAPIDO = env_int("MONITOR_MAX_ENRIQUECER", 260)
MAX_ENRIQUECER_CONCILIACION = env_int("MONITOR_MAX_ENRIQUECER_CONCILIACION", 900)
MAX_CANDIDATOS = env_int("MONITOR_MAX_CANDIDATOS", 6_000)
ANNOS_CONCILIACION = max(1, min(6, env_int("MONITOR_ANNOS_CONCILIACION", 3)))
UMBRAL_PERTINENCIA = env_int("MONITOR_UMBRAL_PERTINENCIA", 30)
MODO_ENV = os.getenv("MONITOR_MODO", "rapido").strip().lower()
# Consultar la Cámara duplica las llamadas de red pero aporta materias, autores
# y ministerios patrocinantes que el Senado no entrega.
CONSULTA_CAMARA = env_bool("MONITOR_CONSULTA_CAMARA", True)

INICIO = time.monotonic()


def tiempo_agotado(reserva: int = 0) -> bool:
    return time.monotonic() - INICIO >= max(30, PRESUPUESTO_SEGUNDOS - reserva)


# ---------------------------------------------------------------------------
# Bitácora y normalización de texto
# ---------------------------------------------------------------------------


def log(mensaje: str) -> None:
    marca = datetime.now(TZ_CL).strftime("%Y-%m-%d %H:%M:%S")
    linea = f"[{marca}] {mensaje}"
    print(linea, flush=True)
    try:
        with BITACORA.open("a", encoding="utf-8") as fh:
            fh.write(linea + "\n")
    except OSError:
        pass


def normaliza(texto: Any) -> str:
    """Minúsculas sin tildes y con espacios colapsados, para comparación léxica."""
    texto = html_mod.unescape(str(texto or ""))
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = texto.lower().replace("\u00a0", " ")
    return re.sub(r"\s+", " ", texto).strip()


def limpia_texto(texto: Any) -> str:
    texto = html_mod.unescape(str(texto or ""))
    texto = re.sub(r"<[^>]+>", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def ahora_cl() -> datetime:
    return datetime.now(TZ_CL)


# ---------------------------------------------------------------------------
# Boletines: normalización y validación
# ---------------------------------------------------------------------------

# Un boletín chileno es NNNNN-NN: correlativo y código de materia.
RE_BOLETIN = re.compile(r"\b(\d{3,6})\s*[-–]\s*(\d{1,2})\b")
RE_BOLETIN_SUELTO = re.compile(r"^\s*(\d{3,6})\s*$")


def normaliza_boletin(valor: Any) -> str:
    """Devuelve el boletín en formato canónico ``NNNNN-NN`` o cadena vacía.

    El Senado y la Cámara escriben el boletín de formas distintas (con y sin
    guion, con espacios, con sufijo de refundido). Unificarlo es la condición
    para poder cruzar ambas fuentes sobre el mismo proyecto.
    """
    texto = limpia_texto(valor)
    if not texto:
        return ""
    m = RE_BOLETIN.search(texto)
    if m:
        return f"{int(m.group(1))}-{int(m.group(2)):02d}"
    m = RE_BOLETIN_SUELTO.match(texto)
    if m:
        return str(int(m.group(1)))
    return ""


def numero_boletin(boletin: str) -> str:
    """Correlativo sin materia: lo que exige el servicio del Senado."""
    b = normaliza_boletin(boletin)
    return b.split("-")[0] if b else ""


def materia_boletin(boletin: str) -> str:
    b = normaliza_boletin(boletin)
    partes = b.split("-")
    return partes[1] if len(partes) > 1 else ""


def id_registro(boletin: str) -> str:
    return hashlib.sha1(normaliza_boletin(boletin).encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Fechas
# ---------------------------------------------------------------------------

MESES_ES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}


def parsea_fecha(valor: Any) -> datetime | None:
    """Interpreta los formatos de fecha que emiten ambos servicios."""
    if isinstance(valor, datetime):
        return valor if valor.tzinfo else valor.replace(tzinfo=TZ_CL)
    if isinstance(valor, date):
        return datetime(valor.year, valor.month, valor.day, tzinfo=TZ_CL)
    texto = limpia_texto(valor)
    if not texto:
        return None

    # ISO / dateTime de la Cámara: 2026-06-24T00:00:00
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2}))?)?", texto)
    if m:
        try:
            return datetime(
                int(m.group(1)), int(m.group(2)), int(m.group(3)),
                int(m.group(4) or 0), int(m.group(5) or 0), int(m.group(6) or 0),
                tzinfo=TZ_CL,
            )
        except ValueError:
            return None

    # DD/MM/AAAA o DD-MM-AAAA del Senado
    m = re.match(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{4})(?:\s+(\d{1,2}):(\d{2}))?", texto)
    if m:
        try:
            return datetime(
                int(m.group(3)), int(m.group(2)), int(m.group(1)),
                int(m.group(4) or 0), int(m.group(5) or 0), tzinfo=TZ_CL,
            )
        except ValueError:
            return None

    # "24 de junio de 2026"
    m = re.match(r"^(\d{1,2})\s+de\s+([a-zñáéíóú]+)\s+de\s+(\d{4})", normaliza(texto))
    if m and m.group(2) in MESES_ES:
        try:
            return datetime(int(m.group(3)), MESES_ES[m.group(2)], int(m.group(1)), tzinfo=TZ_CL)
        except ValueError:
            return None
    return None


def fecha_legible(dt: datetime | None) -> str:
    return dt.strftime("%d/%m/%Y") if dt else ""


def dias_desde(dt: datetime | None, referencia: datetime | None = None) -> int | None:
    if not dt:
        return None
    ref = referencia or ahora_cl()
    return max(0, (ref.date() - dt.date()).days)


# ---------------------------------------------------------------------------
# Red segura y control por dominio
# ---------------------------------------------------------------------------

_HOST_LOCKS: defaultdict[str, threading.Lock] = defaultdict(threading.Lock)
_ULTIMO_HOST: dict[str, float] = {}
_ROBOTS_CACHE: dict[str, tuple[float, urllib.robotparser.RobotFileParser]] = {}


def normaliza_dominio(host: str) -> str:
    host = (host or "").strip().lower().rstrip(".")
    return host[4:] if host.startswith("www.") else host


def dominio_url(url: str) -> str:
    try:
        return normaliza_dominio(urllib.parse.urlsplit(url).hostname or "")
    except Exception:
        return ""


def ip_publica(ip: str) -> bool:
    try:
        obj = ipaddress.ip_address(ip)
        return not (obj.is_private or obj.is_loopback or obj.is_link_local
                    or obj.is_reserved or obj.is_multicast)
    except ValueError:
        return False


@lru_cache(maxsize=512)
def host_publico(host: str) -> bool:
    host = normaliza_dominio(host)
    if not host or host in {"localhost", "localhost.localdomain"}:
        return False
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return False
    ips = {info[4][0] for info in infos}
    return bool(ips) and all(ip_publica(ip) for ip in ips)


def url_publica(url: str) -> bool:
    try:
        p = urllib.parse.urlsplit(url)
        return p.scheme in {"http", "https"} and bool(p.hostname) and host_publico(p.hostname)
    except Exception:
        return False


def robots_permite(url: str) -> bool:
    if not RESPETA_ROBOTS:
        return True
    p = urllib.parse.urlsplit(url)
    raiz = f"{p.scheme}://{p.netloc}"
    ahora = time.time()
    cached = _ROBOTS_CACHE.get(raiz)
    if cached and ahora - cached[0] < 12 * 3600:
        return cached[1].can_fetch(UA_ROBOTS, url)
    rp = urllib.robotparser.RobotFileParser()
    rp.set_url(raiz + "/robots.txt")
    try:
        req = urllib.request.Request(rp.url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=min(10, TIMEOUT)) as resp:
            texto = resp.read(300_000).decode("utf-8", "ignore")
        rp.parse(texto.splitlines())
    except Exception:
        rp.parse([])  # ante fallo, no bloquea todo el dominio
    _ROBOTS_CACHE[raiz] = (ahora, rp)
    return rp.can_fetch(UA_ROBOTS, url)


def descomprime(datos: bytes, encoding: str) -> bytes:
    e = (encoding or "").lower()
    if "gzip" in e:
        return gzip.decompress(datos)
    if "deflate" in e:
        try:
            return zlib.decompress(datos)
        except zlib.error:
            return zlib.decompress(datos, -zlib.MAX_WBITS)
    return datos


def descarga(url: str, *, permite_robots: bool = True, max_bytes: int = MAX_BYTES) -> tuple[bytes, str, dict[str, str]]:
    """Descarga con validación de destino público, robots.txt y espaciado por host."""
    if not url_publica(url):
        raise ValueError("URL no pública o no resoluble")
    if permite_robots and not robots_permite(url):
        raise PermissionError("bloqueado por robots.txt")
    host = dominio_url(url)
    lock = _HOST_LOCKS[host]
    with lock:
        espera = INTERVALO_HOST - (time.monotonic() - _ULTIMO_HOST.get(host, 0.0))
        if espera > 0:
            time.sleep(espera)
        _ULTIMO_HOST[host] = time.monotonic()
    headers = {
        "User-Agent": UA,
        "Accept": "application/xml,text/xml;q=0.9,text/html;q=0.8,*/*;q=0.5",
        "Accept-Encoding": "gzip, deflate",
        "Accept-Language": "es-CL,es;q=0.9",
        "Connection": "close",
    }
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        final = resp.geturl()
        if not url_publica(final):
            raise ValueError("redirección no pública")
        raw = resp.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise ValueError("respuesta excede límite")
        raw = descomprime(raw, resp.headers.get("Content-Encoding", ""))
        return raw, final, {k.lower(): v for k, v in resp.headers.items()}


# ---------------------------------------------------------------------------
# Parser XML tolerante al esquema
# ---------------------------------------------------------------------------
#
# Los servicios del Congreso no publican un contrato estable: el Senado usa
# etiquetas en minúscula y mayúscula según el bloque, y la Cámara las emite con
# namespace. Amarrar el motor a nombres literales lo vuelve frágil ante
# cualquier ajuste del proveedor. Por eso el acceso a campos se hace por nombre
# normalizado y por listas de alias, no por ruta exacta.


def _tag(elem: ET.Element) -> str:
    """Nombre de etiqueta sin namespace y normalizado."""
    t = elem.tag
    if isinstance(t, str) and "}" in t:
        t = t.split("}", 1)[1]
    return normaliza(t).replace(" ", "")


def texto_nodo(elem: ET.Element | None) -> str:
    if elem is None:
        return ""
    return limpia_texto("".join(elem.itertext()))


def hijos_por_nombre(elem: ET.Element | None) -> dict[str, list[ET.Element]]:
    indice: dict[str, list[ET.Element]] = defaultdict(list)
    if elem is None:
        return indice
    for hijo in list(elem):
        indice[_tag(hijo)].append(hijo)
    return indice


def campo(elem: ET.Element | None, *alias: str, profundo: bool = True) -> str:
    """Primer valor de texto no vacío entre los alias dados.

    Busca primero entre los hijos directos y, si ``profundo``, luego en todo el
    subárbol. Devuelve cadena vacía si ninguno existe: nunca lanza excepción,
    porque un campo faltante no debe abortar la lectura del proyecto completo.
    """
    if elem is None:
        return ""
    objetivos = {normaliza(a).replace(" ", "") for a in alias}
    for hijo in list(elem):
        if _tag(hijo) in objetivos:
            valor = texto_nodo(hijo)
            if valor:
                return valor
    # Atributos (la Cámara expone Id como atributo en varios nodos)
    for clave, valor in (elem.attrib or {}).items():
        if normaliza(clave).replace(" ", "") in objetivos and limpia_texto(valor):
            return limpia_texto(valor)
    if not profundo:
        return ""
    for hijo in elem.iter():
        if hijo is elem:
            continue
        if _tag(hijo) in objetivos:
            valor = texto_nodo(hijo)
            if valor:
                return valor
    return ""


def nodos(elem: ET.Element | None, *alias: str) -> list[ET.Element]:
    """Todos los nodos del subárbol cuyo nombre coincida con algún alias."""
    if elem is None:
        return []
    objetivos = {normaliza(a).replace(" ", "") for a in alias}
    return [n for n in elem.iter() if n is not elem and _tag(n) in objetivos]


def parsea_xml(raw: bytes) -> ET.Element | None:
    """Parsea XML tolerando BOM, encabezados mal declarados y basura al inicio."""
    if not raw:
        return None
    texto = None
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            texto = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if texto is None:
        return None
    texto = texto.strip()
    inicio = texto.find("<")
    if inicio > 0:
        texto = texto[inicio:]
    # Entidades HTML sueltas rompen el parser XML estricto.
    texto = re.sub(r"&(?!#?\w+;)", "&amp;", texto)
    for intento in (texto, texto.replace("&nbsp;", " ")):
        try:
            return ET.fromstring(intento)
        except ET.ParseError:
            continue
    return None


# ---------------------------------------------------------------------------
# Léxico de pertinencia UAF (Ley N° 19.913)
# ---------------------------------------------------------------------------
#
# El monitor de prensa preguntaba "¿este texto menciona a la UAF?". Aquí la
# pregunta es distinta y más difícil: "¿este proyecto de ley puede alterar el
# marco en que la UAF opera?". Muchos proyectos relevantes nunca escriben la
# sigla UAF: modifican el art. 27 de la Ley 19.913 por la vía de agregar
# delitos base, tocan el secreto bancario, o crean obligaciones para un sector
# que ya es sujeto obligado. Por eso la detección es por capas.

# Capa 1 · Impacto directo: el proyecto nombra la ley o el organismo.
ANCLAS_DIRECTAS = [
    "ley n 19.913", "ley 19.913", "ley no 19.913", "19.913", "19913",
    "unidad de analisis financiero",
    "reporte de operacion sospechosa", "reportes de operaciones sospechosas",
    "reporte de operaciones sospechosas", "operacion sospechosa",
    "operaciones sospechosas", "sujeto obligado", "sujetos obligados",
    "entidades obligadas", "reporte de operaciones en efectivo",
]

# La sigla se trata aparte: "UAF" aislada aparece en otros contextos.
RE_SIGLA_UAF = re.compile(r"\bu\.?\s?a\.?\s?f\.?\b", re.I)

# Capa 2 · Núcleo ALA/CFT: el proyecto opera sobre el sistema antilavado.
ANCLAS_NUCLEO = [
    "lavado de activos", "lavado de dinero", "blanqueo de capitales",
    "financiamiento del terrorismo", "financiamiento al terrorismo",
    "delito base", "delitos base", "delito precedente", "delitos precedentes",
    "delito previo", "gafi", "gafilat", "grupo de accion financiera",
    "debida diligencia", "conocimiento del cliente", "diligencia debida",
    "beneficiario final", "beneficiarios finales", "beneficiario efectivo",
    "secreto bancario", "reserva bancaria", "levantamiento del secreto bancario",
    "decomiso", "comiso", "comiso por equivalencia", "extincion de dominio",
    "recuperacion de activos", "incautacion de bienes",
    "inteligencia financiera", "inteligencia economica",
    "subsistema de inteligencia economica",
    "sanciones financieras dirigidas", "listas de sanciones",
    "prevencion del lavado", "sistema antilavado", "antilavado de activos",
]

# Capa 3 · Estructural: instituciones y figuras que arrastran a la UAF.
ANCLAS_ESTRUCTURALES = [
    "crimen organizado", "criminalidad organizada", "asociacion delictiva",
    "asociacion criminal", "asociacion ilicita", "delincuencia economica",
    "delitos economicos", "ley 20.393", "20.393", "20393",
    "responsabilidad penal de las personas juridicas",
    "activos virtuales", "criptoactivos", "criptomonedas", "monedas virtuales",
    "proveedores de servicios de activos virtuales",
    "dinero en efectivo", "pago en efectivo", "transacciones en efectivo",
    "bancarizacion", "trazabilidad financiera", "trazabilidad de las operaciones",
    "flujos financieros ilicitos", "testaferro", "testaferros",
    "sociedades de papel", "sociedades instrumentales",
    "registro de beneficiarios", "cooperacion internacional",
    "unidades de inteligencia financiera", "grupo egmont",
    "corrupcion", "cohecho", "soborno", "malversacion", "fraude al fisco",
    "delitos tributarios", "delitos aduaneros", "contrabando",
    "trafico ilicito de migrantes", "trata de personas",
    "trafico de estupefacientes", "trafico ilicito de drogas",
    "propiedad industrial", "falsificacion de marcas", "comercio ilegal",
    "comercio ambulante ilegal", "receptacion", "usura",
    "financiamiento de la actividad politica", "aportes de campana",
]

# Capa 4 · Sectorial: sujetos obligados del art. 3 de la Ley 19.913.
# Un proyecto que regula a un sujeto obligado puede alterar la base de reporte
# aunque no mencione lavado de activos.
ANCLAS_SECTORIALES = {
    "banca_financiero": ["banco", "bancos", "bancaria", "entidades bancarias",
                         "instituciones financieras", "cooperativas de ahorro",
                         "cajas de compensacion", "emisores de tarjetas",
                         "operadores de tarjetas", "medios de pago"],
    "valores_seguros": ["corredores de bolsa", "agentes de valores", "bolsa de valores",
                        "administradoras de fondos", "fondos de inversion",
                        "companias de seguros", "corredores de seguros",
                        "securitizadoras", "custodios de valores"],
    "notarial_registral": ["notarios", "notarias", "conservadores de bienes raices",
                           "archiveros judiciales", "servicio de registro civil"],
    "juegos_azar": ["casinos de juego", "casinos", "juegos de azar",
                    "apuestas en linea", "apuestas deportivas", "hipodromos",
                    "loteria", "polla chilena"],
    "cambio_remesas": ["casas de cambio", "cambio de moneda", "remesas",
                       "transferencia de fondos", "corredores de cambio"],
    "credito_no_bancario": ["factoring", "leasing", "mutuarias",
                            "casas de prestamo", "operaciones prendarias",
                            "prendarias", "agencias de prestamo",
                            "cooperativas de credito", "crowdfunding",
                            "plataformas de financiamiento colectivo",
                            "financieras no bancarias"],
    "bienes_alto_valor": ["metales preciosos", "piedras preciosas", "joyas",
                          "obras de arte", "antiguedades", "casas de remate",
                          "martilleros", "vehiculos usados", "automotoras",
                          "naves y aeronaves", "yates"],
    "inmobiliario": ["corredores de propiedades", "empresas inmobiliarias",
                     "gestion inmobiliaria", "corretaje de propiedades"],
    "comercio_exterior": ["agentes de aduana", "zona franca", "zonas francas",
                          "despachadores de aduana", "operadores logisticos"],
    "sin_fines_de_lucro": ["organizaciones sin fines de lucro", "fundaciones",
                           "corporaciones sin fines de lucro", "ong",
                           "organizaciones no gubernamentales",
                           "clubes deportivos", "sociedades anonimas deportivas"],
    "profesiones_liberales": ["abogados", "contadores", "auditores externos",
                              "asesores tributarios", "empresas de auditoria"],
    "otros_obligados": ["empresas de transporte de valores", "blindaje de valores",
                        "agencias de viaje", "generadores de facturas",
                        "sociedades administradoras", "trust", "fideicomiso"],
}

# Términos que, presentes en solitario, suelen indicar falso positivo.
# No descartan por sí solos: bajan el puntaje del bloque sectorial.
ANCLAS_NEGATIVAS = [
    "dia nacional", "declara el dia", "monumento", "erigir un monumento",
    "patrimonio cultural inmaterial", "feriado", "denominacion de la comuna",
    "rehabilita la nacionalidad", "concede la nacionalidad",
    "nacionalidad por gracia", "cambio de nombre de la calle",
]

# Ejes de impacto institucional: reemplazan a los "tópicos" del monitor de prensa.
EJES_REGLAS: dict[str, list[str]] = {
    "facultades_uaf": [
        "unidad de analisis financiero", "19.913", "19913",
        "reporte de operacion sospechosa", "reportes de operaciones sospechosas",
        "operaciones sospechosas", "facultades de la unidad",
        "inteligencia financiera", "subsistema de inteligencia economica",
        "acceso a informacion financiera",
    ],
    "delitos_base": [
        "delito base", "delitos base", "delito precedente", "delitos precedentes",
        "articulo 27", "catalogo de delitos", "lavado de activos",
    ],
    "sujetos_obligados": [
        "sujeto obligado", "sujetos obligados", "entidades obligadas",
        "obligacion de informar", "deber de informar", "debida diligencia",
        "conocimiento del cliente", "registro de operaciones",
    ],
    "secreto_bancario": [
        "secreto bancario", "reserva bancaria", "levantamiento del secreto",
        "informacion sujeta a reserva", "cuentas bancarias", "acceso a cuentas",
    ],
    "decomiso_activos": [
        "decomiso", "comiso", "extincion de dominio", "recuperacion de activos",
        "incautacion", "administracion de bienes incautados", "bienes decomisados",
    ],
    "beneficiario_final": [
        "beneficiario final", "beneficiarios finales", "beneficiario efectivo",
        "registro de beneficiarios", "estructura de propiedad",
        "sociedades instrumentales", "testaferro",
    ],
    "activos_virtuales": [
        "activos virtuales", "criptoactivos", "criptomonedas", "monedas virtuales",
        "billeteras digitales", "exchange", "finanzas descentralizadas",
    ],
    "efectivo_bancarizacion": [
        "dinero en efectivo", "pago en efectivo", "transacciones en efectivo",
        "limite a las operaciones en efectivo", "bancarizacion",
        "monto maximo en efectivo",
    ],
    "financiamiento_terrorismo": [
        "financiamiento del terrorismo", "financiamiento al terrorismo",
        "conducta terrorista", "sanciones financieras dirigidas",
        "listas de sanciones", "consejo de seguridad",
    ],
    "responsabilidad_penal_pj": [
        "20.393", "responsabilidad penal de las personas juridicas",
        "modelo de prevencion de delitos", "compliance", "cumplimiento normativo",
        "delitos economicos",
    ],
    "crimen_organizado": [
        "crimen organizado", "criminalidad organizada", "asociacion delictiva",
        "asociacion criminal", "tecnicas especiales de investigacion",
        "agente encubierto", "entrega vigilada",
    ],
    "cooperacion_institucional": [
        "intercambio de informacion", "convenio de colaboracion",
        "cooperacion internacional", "grupo egmont",
        "unidades de inteligencia financiera", "interoperabilidad",
        "acceso a bases de datos",
    ],
}

ETIQUETAS_EJES = {
    "facultades_uaf": "Facultades y competencias UAF",
    "delitos_base": "Catálogo de delitos base",
    "sujetos_obligados": "Régimen de sujetos obligados",
    "secreto_bancario": "Secreto y reserva bancaria",
    "decomiso_activos": "Decomiso y recuperación de activos",
    "beneficiario_final": "Beneficiario final y transparencia societaria",
    "activos_virtuales": "Activos virtuales",
    "efectivo_bancarizacion": "Efectivo y bancarización",
    "financiamiento_terrorismo": "Financiamiento del terrorismo",
    "responsabilidad_penal_pj": "Responsabilidad penal de personas jurídicas",
    "crimen_organizado": "Crimen organizado y persecución penal",
    "cooperacion_institucional": "Cooperación e intercambio de información",
}

ETIQUETAS_SECTORES = {
    "banca_financiero": "Banca y sistema financiero",
    "valores_seguros": "Valores y seguros",
    "notarial_registral": "Notarial y registral",
    "juegos_azar": "Juegos de azar",
    "cambio_remesas": "Cambio de divisas y remesas",
    "credito_no_bancario": "Crédito no bancario",
    "bienes_alto_valor": "Bienes de alto valor",
    "inmobiliario": "Inmobiliario",
    "comercio_exterior": "Comercio exterior y aduanas",
    "sin_fines_de_lucro": "Organizaciones sin fines de lucro",
    "profesiones_liberales": "Profesiones liberales",
    "otros_obligados": "Otros sujetos obligados",
}

ETIQUETAS_IMPACTO = {
    "directo": "Impacto directo en la Ley 19.913",
    "estructural": "Impacto estructural en el sistema ALA/CFT",
    "sectorial": "Impacto sectorial en sujetos obligados",
    "seguimiento": "Seguimiento preventivo",
}

# Peso por campo donde aparece la señal: el título de un proyecto es una
# declaración de propósito; la tramitación es contexto secundario.
PESOS_CAMPO = {
    "titulo": 3.0,
    "materias": 2.0,
    "resumen": 1.6,
    "tramitacion": 1.0,
    "comisiones": 1.2,
}


@lru_cache(maxsize=4096)
def _patron_frase(aguja: str) -> re.Pattern[str] | None:
    """Compila una frase normalizada como patrón con límites de palabra."""
    aguja = normaliza(aguja)
    if not aguja:
        return None
    partes = [re.escape(p) for p in aguja.split(" ") if p]
    if not partes:
        return None
    return re.compile(r"(?<![a-z0-9])" + r"\s+".join(partes) + r"(?![a-z0-9])")


def encuentra_frases(texto: Any, agujas: Iterable[str]) -> list[str]:
    """Frases del listado presentes en el texto, con coincidencia léxica estricta."""
    plano = normaliza(texto)
    if not plano:
        return []
    hallazgos = []
    for aguja in agujas:
        patron = _patron_frase(aguja)
        if patron and patron.search(plano):
            hallazgos.append(aguja)
    return hallazgos


def carga_lexico() -> dict[str, Any]:
    """Permite ampliar el léxico sin tocar el motor.

    El archivo ``lexico_uaf.json`` es aditivo: sus listas se suman a las
    incorporadas. Así el equipo puede incorporar terminología nueva sin
    desplegar código.
    """
    base = {
        "directas": list(ANCLAS_DIRECTAS),
        "nucleo": list(ANCLAS_NUCLEO),
        "estructurales": list(ANCLAS_ESTRUCTURALES),
        "sectoriales": {k: list(v) for k, v in ANCLAS_SECTORIALES.items()},
        "negativas": list(ANCLAS_NEGATIVAS),
    }
    if not LEXICO_ARCHIVO.exists():
        return base
    try:
        extra = json.loads(LEXICO_ARCHIVO.read_text(encoding="utf-8"))
    except Exception as exc:
        log(f"! lexico_uaf.json inválido, se ignora: {type(exc).__name__}: {exc}")
        return base
    for clave in ("directas", "nucleo", "estructurales", "negativas"):
        valores = extra.get(clave) or []
        if isinstance(valores, list):
            base[clave] = list(dict.fromkeys(base[clave] + [str(v) for v in valores]))
    sectoriales = extra.get("sectoriales") or {}
    if isinstance(sectoriales, dict):
        for sector, valores in sectoriales.items():
            if isinstance(valores, list):
                base["sectoriales"].setdefault(sector, [])
                base["sectoriales"][sector] = list(dict.fromkeys(
                    base["sectoriales"][sector] + [str(v) for v in valores]))
    return base


_LEXICO_CACHE: dict[str, Any] | None = None


def lexico() -> dict[str, Any]:
    global _LEXICO_CACHE
    if _LEXICO_CACHE is None:
        _LEXICO_CACHE = carga_lexico()
    return _LEXICO_CACHE


# ---------------------------------------------------------------------------
# Motor de pertinencia
# ---------------------------------------------------------------------------


def campos_analizables(proy: dict[str, Any]) -> list[tuple[str, str]]:
    """Fragmentos del proyecto con su origen, para ponderar dónde aparece la señal."""
    tramites = proy.get("tramitacion") or []
    texto_tramites = " · ".join(
        f"{t.get('descripcion','')} {t.get('etapa','')} {t.get('subetapa','')}"
        for t in tramites[-40:]
    )
    comisiones = " · ".join(proy.get("comisiones") or [])
    materias = " · ".join(proy.get("materias") or [])
    return [
        ("titulo", proy.get("titulo", "")),
        ("materias", materias),
        ("resumen", proy.get("resumen", "")),
        ("tramitacion", texto_tramites),
        ("comisiones", comisiones),
    ]


def evalua_pertinencia(proy: dict[str, Any]) -> dict[str, Any]:
    """Puntúa el proyecto y decide su nivel de impacto para la UAF.

    Devuelve el puntaje, el nivel, la evidencia textual encontrada y el detalle
    por capa. La evidencia es lo que permite que un analista audite por qué el
    monitor incluyó o excluyó un boletín, en lugar de confiar en el número.
    """
    lex = lexico()
    puntaje = 0.0
    evidencia: dict[str, list[str]] = {"directas": [], "nucleo": [], "estructurales": [], "sectoriales": []}
    sectores: set[str] = set()
    origen_directo = ""

    for origen, texto in campos_analizables(proy):
        if not texto:
            continue
        peso = PESOS_CAMPO.get(origen, 1.0)

        directas = encuentra_frases(texto, lex["directas"])
        if directas:
            puntaje += 55 * peso
            evidencia["directas"].extend(directas)
            origen_directo = origen_directo or origen

        # La sigla suelta solo cuenta si el entorno es financiero o penal.
        if RE_SIGLA_UAF.search(texto or ""):
            plano = normaliza(texto)
            if any(x in plano for x in ("financ", "lavado", "activos", "sospechos",
                                        "analisis", "inteligencia", "banc")):
                puntaje += 30 * peso
                evidencia["directas"].append("sigla uaf en contexto financiero")
                origen_directo = origen_directo or origen

        nucleo = encuentra_frases(texto, lex["nucleo"])
        if nucleo:
            # Rendimiento decreciente: tres anclas distintas ya establecen el tema.
            puntaje += min(3, len(nucleo)) * 16 * peso
            evidencia["nucleo"].extend(nucleo)

        estructurales = encuentra_frases(texto, lex["estructurales"])
        if estructurales:
            puntaje += min(3, len(estructurales)) * 8 * peso
            evidencia["estructurales"].extend(estructurales)

        for sector, agujas in lex["sectoriales"].items():
            hallados = encuentra_frases(texto, agujas)
            if hallados:
                sectores.add(sector)
                puntaje += min(2, len(hallados)) * 4 * peso
                evidencia["sectoriales"].extend(hallados)

    negativas = encuentra_frases(proy.get("titulo", ""), lex["negativas"])
    if negativas and not evidencia["directas"] and not evidencia["nucleo"]:
        puntaje *= 0.25

    for clave in evidencia:
        evidencia[clave] = sorted(dict.fromkeys(evidencia[clave]))[:12]

    puntaje = round(puntaje, 1)

    if evidencia["directas"]:
        nivel = "directo"
    elif len(evidencia["nucleo"]) >= 2 or (evidencia["nucleo"] and puntaje >= 70):
        nivel = "estructural"
    elif evidencia["nucleo"] or (evidencia["estructurales"] and puntaje >= UMBRAL_PERTINENCIA):
        nivel = "estructural" if puntaje >= 90 else "sectorial"
    elif sectores and puntaje >= UMBRAL_PERTINENCIA:
        nivel = "sectorial"
    elif puntaje >= UMBRAL_PERTINENCIA:
        nivel = "seguimiento"
    else:
        nivel = "descartado"

    return {
        "puntaje": puntaje,
        "nivel": nivel,
        "evidencia": evidencia,
        "sectores": sorted(sectores),
        "origen_senal": origen_directo,
        "negativas": negativas,
    }


def clasifica_ejes(proy: dict[str, Any]) -> list[str]:
    """Ejes de impacto institucional presentes en el proyecto."""
    texto = " · ".join(t for _, t in campos_analizables(proy) if t)
    encontrados = []
    for eje, agujas in EJES_REGLAS.items():
        if encuentra_frases(texto, agujas):
            encontrados.append(eje)
    return encontrados


# ---------------------------------------------------------------------------
# Estado de tramitación, urgencia y prioridad
# ---------------------------------------------------------------------------

ORDEN_TRAMITE = [
    ("primer tramite", 1), ("1er tramite", 1), ("primer trámite", 1),
    ("segundo tramite", 2), ("2do tramite", 2),
    ("tercer tramite", 3), ("3er tramite", 3),
    ("comision mixta", 4), ("mixta", 4),
    ("veto", 5),
    ("tribunal constitucional", 6),
    ("finalizado", 7), ("tramitacion terminada", 7), ("publicado", 8),
    ("archivado", 0), ("retirado", 0), ("rechazado", 0),
]

PESO_URGENCIA = {
    "discusion inmediata": 3.0,
    "suma urgencia": 2.2,
    "suma": 2.2,
    "simple urgencia": 1.6,
    "simple": 1.6,
    "sin urgencia": 1.0,
    "": 1.0,
}

ETIQUETAS_URGENCIA = {
    "discusion inmediata": "Discusión inmediata",
    "suma": "Suma urgencia",
    "simple": "Simple urgencia",
    "sin urgencia": "Sin urgencia",
}


def normaliza_urgencia(valor: Any) -> str:
    plano = normaliza(valor)
    if not plano:
        return "sin urgencia"
    if "inmediata" in plano:
        return "discusion inmediata"
    if "suma" in plano:
        return "suma"
    if "simple" in plano:
        return "simple"
    return "sin urgencia"


def etapa_ordinal(etapa: Any, subetapa: Any = "") -> int:
    """Posición del proyecto en el itinerario legislativo (0 = cerrado)."""
    plano = normaliza(f"{etapa} {subetapa}")
    for aguja, valor in ORDEN_TRAMITE:
        if normaliza(aguja) in plano:
            return valor
    return 1 if plano else 0


def esta_vigente(proy: dict[str, Any]) -> bool:
    """Distingue proyectos en tramitación de los cerrados o publicados."""
    plano = normaliza(f"{proy.get('etapa','')} {proy.get('subetapa','')} {proy.get('estado','')}")
    cerrados = ("archivad", "retirad", "rechazad", "publicad", "tramitacion terminada",
                "terminada", "ley n", "promulgad")
    if any(x in plano for x in cerrados):
        return False
    return True


def calcula_prioridad(proy: dict[str, Any]) -> dict[str, Any]:
    """Prioridad institucional = pertinencia × urgencia × proximidad × frescura.

    No es un índice de riesgo jurídico sino de atención: qué debe mirar primero
    el analista esta semana. Un proyecto de impacto directo con discusión
    inmediata en tercer trámite pesa mucho más que uno estructural recién
    ingresado sin urgencia.
    """
    base = {"directo": 100.0, "estructural": 62.0, "sectorial": 34.0,
            "seguimiento": 16.0, "descartado": 0.0}.get(proy.get("nivel_impacto", ""), 0.0)
    urgencia = PESO_URGENCIA.get(normaliza_urgencia(proy.get("urgencia")), 1.0)

    ordinal = proy.get("etapa_ordinal", 1)
    # Cuanto más avanzado, menos margen queda para incidir técnicamente.
    proximidad = {0: 0.3, 1: 1.0, 2: 1.25, 3: 1.5, 4: 1.6, 5: 1.4, 6: 1.2,
                  7: 0.6, 8: 0.4}.get(ordinal, 1.0)

    dias = proy.get("dias_sin_movimiento")
    if dias is None:
        frescura = 0.85
    elif dias <= 7:
        frescura = 1.3
    elif dias <= 30:
        frescura = 1.15
    elif dias <= 90:
        frescura = 1.0
    elif dias <= 365:
        frescura = 0.8
    else:
        frescura = 0.55

    valor = base * urgencia * proximidad * frescura
    if not proy.get("vigente", True):
        valor *= 0.35

    # Cortes calibrados sobre los valores neutros de cada nivel: un proyecto
    # estructural sin urgencia recién ingresado vale 62 y debe quedar en
    # "media", no en "baja"; uno directo con suma urgencia supera 200.
    valor = round(min(1000.0, valor), 1)
    if valor >= 200:
        banda = "critica"
    elif valor >= 120:
        banda = "alta"
    elif valor >= 55:
        banda = "media"
    else:
        banda = "baja"
    return {
        "prioridad": valor,
        "banda_prioridad": banda,
        "factor_urgencia": urgencia,
        "factor_proximidad": proximidad,
        "factor_frescura": frescura,
    }


# ---------------------------------------------------------------------------
# Fuentes oficiales
# ---------------------------------------------------------------------------

SENADO_BASE = "https://tramitacion.senado.cl/wspublico/tramitacion.php"
SENADO_FICHA = "https://tramitacion.senado.cl/appsenado/templates/tramitacion/index.php?boletin_ini={}"
CAMARA_WS = "https://opendata.camara.cl/camaradiputados/WServices/WSLegislativo.asmx"
CAMARA_FICHA = "https://www.camara.cl/legislacion/ProyectosDeLey/tramitacion.aspx?prmID={}&prmBOLETIN={}"
BCN_LEY = "https://www.bcn.cl/leychile/navegar?idNorma={}"

_COBERTURA: dict[str, dict[str, Any]] = {}
_COBERTURA_LOCK = threading.Lock()


def cobertura(canal: str, *, resultados: int = 0, error: str = "", llamadas: int = 1) -> None:
    with _COBERTURA_LOCK:
        reg = _COBERTURA.setdefault(canal, {
            "canal": canal, "llamadas": 0, "resultados": 0, "errores": [], "consultado": False,
        })
        reg["consultado"] = True
        reg["llamadas"] += llamadas
        reg["resultados"] += resultados
        if error and len(reg["errores"]) < 6:
            reg["errores"].append(error[:220])


def url_senado_boletin(boletin: str) -> str:
    return f"{SENADO_BASE}?boletin={urllib.parse.quote(numero_boletin(boletin))}"


def url_senado_fecha(dt: datetime) -> str:
    # quote() deja pasar las barras por omisión; el parámetro debe ir codificado.
    return f"{SENADO_BASE}?fecha={urllib.parse.quote(dt.strftime('%d/%m/%Y'), safe='')}"


def url_camara(operacion: str, **params: Any) -> str:
    query = urllib.parse.urlencode({k: str(v) for k, v in params.items()})
    return f"{CAMARA_WS}/{operacion}" + (f"?{query}" if query else "")


# --- Senado -----------------------------------------------------------------


def parsea_proyecto_senado(nodo: ET.Element) -> dict[str, Any]:
    """Convierte un nodo <proyecto> del Senado al modelo interno.

    El acceso a campos usa alias porque el servicio alterna nomenclatura entre
    bloques (``FECHA`` vs ``fecha``, ``DESCRIPCIONTRAMITE`` vs ``descripcion``).
    """
    # El bloque de cabecera se busca solo entre los hijos directos: varios
    # nodos <tramite> tienen su propio campo <Descripcion>, y tomar el primero
    # del subárbol haría que el motor leyera la cabecera desde un trámite.
    desc = None
    for hijo in list(nodo):
        if _tag(hijo) not in {"descripcion", "descripciones"}:
            continue
        marcadores = {_tag(x) for x in hijo}
        if marcadores & {"boletin", "numeroboletin", "nroboletin", "titulo", "nombre"}:
            desc = hijo
            break
    ambito = desc if desc is not None else nodo

    boletin = normaliza_boletin(campo(ambito, "boletin", "numeroboletin", "nroboletin"))
    titulo = campo(ambito, "titulo", "nombre", "materia", "descripcion_titulo")
    if not titulo:
        titulo = campo(nodo, "titulo", "nombre")

    fecha_ingreso = parsea_fecha(campo(ambito, "fecha_ingreso", "fechaingreso", "fecha"))
    etapa = campo(ambito, "etapa", "etapa_actual", "etapadescripcion")
    subetapa = campo(ambito, "subetapa", "sub_etapa", "subetapadescripcion")
    iniciativa = campo(ambito, "iniciativa", "tipo_iniciativa", "tipoiniciativa")
    camara_origen = campo(ambito, "camara_origen", "camaraorigen", "origen")
    urgencia = campo(ambito, "urgencia_actual", "urgenciaactual", "urgencia")
    ley = campo(ambito, "leynro", "ley_nro", "numeroley", "ley")
    refundidos = campo(ambito, "refundidos", "refundido")
    link_texto = campo(ambito, "link_mensaje_mocion", "linkmensajemocion", "link")
    estado = campo(ambito, "estado", "situacion")

    # Tramitación
    tramites: list[dict[str, Any]] = []
    for t in nodos(nodo, "tramite", "tramites_tramite"):
        f = parsea_fecha(campo(t, "fecha", "fechatramite", "fecha_tramite"))
        tramites.append({
            "fecha": f.isoformat() if f else "",
            "fecha_legible": fecha_legible(f),
            "sesion": campo(t, "sesion", "nrosesion", "sesionnro"),
            "descripcion": campo(t, "descripciontramite", "descripcion_tramite",
                                 "descripcion", "tramite"),
            "etapa": campo(t, "etapdescripcion", "etapa_descripcion", "etapa"),
            "camara": campo(t, "camaratramite", "camara_tramite", "camara"),
        })
    tramites = [t for t in tramites if t["descripcion"] or t["fecha"]]
    tramites.sort(key=lambda t: t["fecha"] or "")

    # Urgencias históricas
    urgencias: list[dict[str, Any]] = []
    for u in nodos(nodo, "urgencia"):
        fi = parsea_fecha(campo(u, "fechaingreso", "fecha_ingreso", "fechainicio", "fecha"))
        urgencias.append({
            "tipo": campo(u, "tipo", "tipourgencia", "tipo_urgencia", "descripcion"),
            "fecha_ingreso": fi.isoformat() if fi else "",
            "fecha_retiro": (parsea_fecha(campo(u, "fecharetiro", "fecha_retiro")) or ""),
        })
    urgencias = [u for u in urgencias if u["tipo"]]
    for u in urgencias:
        if isinstance(u.get("fecha_retiro"), datetime):
            u["fecha_retiro"] = u["fecha_retiro"].isoformat()

    # Votaciones
    votaciones: list[dict[str, Any]] = []
    for v in nodos(nodo, "votacion"):
        fv = parsea_fecha(campo(v, "fecha", "fechavotacion"))
        votaciones.append({
            "fecha": fv.isoformat() if fv else "",
            "fecha_legible": fecha_legible(fv),
            "tema": campo(v, "tema", "materia", "descripcion"),
            "si": campo(v, "si", "afavor", "aprueba"),
            "no": campo(v, "no", "encontra", "rechaza"),
            "abstencion": campo(v, "abstencion", "abstenciones"),
            "camara": campo(v, "camara"),
        })
    votaciones = [v for v in votaciones if v["fecha"] or v["tema"]]

    autores = sorted({texto_nodo(a) for a in nodos(nodo, "autor", "parlamentario")
                      if texto_nodo(a)})
    materias = sorted({campo(m, "descripcion", "nombre", "materia") or texto_nodo(m)
                       for m in nodos(nodo, "materia")})
    materias = [m for m in materias if m]

    comisiones = sorted({texto_nodo(c) for c in nodos(nodo, "comision", "comisiones_comision")
                         if texto_nodo(c)})

    informes = []
    for i in nodos(nodo, "informe"):
        fi = parsea_fecha(campo(i, "fecha", "fechainforme"))
        informes.append({
            "fecha": fi.isoformat() if fi else "",
            "tramite": campo(i, "tramite", "tramiteconstitucional"),
            "etapa": campo(i, "etapa", "descripcion"),
            "link": campo(i, "link", "url", "linkinforme"),
        })

    return {
        "boletin": boletin,
        "titulo": limpia_texto(titulo),
        "fecha_ingreso": fecha_ingreso.isoformat() if fecha_ingreso else "",
        "etapa": limpia_texto(etapa),
        "subetapa": limpia_texto(subetapa),
        "iniciativa": limpia_texto(iniciativa),
        "camara_origen": limpia_texto(camara_origen),
        "urgencia": limpia_texto(urgencia),
        "ley_numero": limpia_texto(ley),
        "refundidos": limpia_texto(refundidos),
        "estado": limpia_texto(estado),
        "link_texto_original": limpia_texto(link_texto),
        "tramitacion": tramites,
        "urgencias": urgencias[-12:],
        "votaciones": votaciones[-25:],
        "autores": autores[:40],
        "materias": materias[:40],
        "comisiones": comisiones[:20],
        "informes": informes[-15:],
        "origen_dato": "senado",
    }


def consulta_senado_boletin(boletin: str) -> dict[str, Any] | None:
    """Ficha completa de tramitación de un boletín en el Senado."""
    num = numero_boletin(boletin)
    if not num:
        return None
    url = url_senado_boletin(num)
    try:
        raw, _, _ = descarga(url)
    except Exception as exc:
        cobertura("senado_boletin", error=f"{num}: {type(exc).__name__}: {exc}")
        return None
    raiz = parsea_xml(raw)
    if raiz is None:
        cobertura("senado_boletin", error=f"{num}: XML ilegible")
        return None
    proyectos = nodos(raiz, "proyecto")
    if not proyectos and _tag(raiz) == "proyecto":
        proyectos = [raiz]
    if not proyectos:
        cobertura("senado_boletin", error=f"{num}: sin nodo proyecto")
        return None
    datos = parsea_proyecto_senado(proyectos[0])
    if not datos.get("boletin"):
        # El servicio no siempre repite el boletín dentro del nodo.
        datos["boletin"] = normaliza_boletin(boletin)
    cobertura("senado_boletin", resultados=1)
    return datos


def consulta_senado_movimiento(desde: datetime) -> list[dict[str, Any]]:
    """Boletines con movimiento desde una fecha (ventana máxima de un mes).

    Este es el canal de descubrimiento incremental: equivale al buscador de
    noticias del monitor de prensa, pero con la ventaja de ser exhaustivo y
    oficial en lugar de probabilístico.
    """
    url = url_senado_fecha(desde)
    try:
        raw, _, _ = descarga(url)
    except Exception as exc:
        cobertura("senado_movimiento", error=f"{desde:%d/%m/%Y}: {type(exc).__name__}: {exc}")
        return []
    raiz = parsea_xml(raw)
    if raiz is None:
        cobertura("senado_movimiento", error=f"{desde:%d/%m/%Y}: XML ilegible")
        return []
    resultados = []
    for nodo in nodos(raiz, "proyecto"):
        datos = parsea_proyecto_senado(nodo)
        if datos.get("boletin"):
            datos["canal_descubrimiento"] = "senado_movimiento"
            resultados.append(datos)
    cobertura("senado_movimiento", resultados=len(resultados))
    return resultados


# --- Cámara de Diputadas y Diputados ----------------------------------------


def parsea_proyecto_camara(nodo: ET.Element) -> dict[str, Any]:
    """Convierte un nodo ProyectoLey de la Cámara al modelo interno."""
    boletin = normaliza_boletin(campo(nodo, "numeroboletin", "boletin"))
    fecha = parsea_fecha(campo(nodo, "fechaingreso", "fecha_ingreso"))

    autores = []
    for a in nodos(nodo, "parlamentarioautor"):
        nombre = " ".join(x for x in [
            campo(a, "nombre"), campo(a, "apellidopaterno"), campo(a, "apellidomaterno"),
        ] if x).strip()
        if nombre:
            autores.append(nombre)

    materias = [campo(m, "nombre") or texto_nodo(m) for m in nodos(nodo, "materia")]
    materias = sorted({limpia_texto(m) for m in materias if limpia_texto(m)})

    ministerios = [campo(m, "nombre") for m in nodos(nodo, "ministerio")]
    ministerios = sorted({limpia_texto(m) for m in ministerios if limpia_texto(m)})

    return {
        "boletin": boletin,
        "camara_id": campo(nodo, "id", profundo=False),
        "titulo": limpia_texto(campo(nodo, "nombre", "titulo")),
        "fecha_ingreso": fecha.isoformat() if fecha else "",
        "iniciativa": limpia_texto(campo(nodo, "tipoiniciativa")),
        "camara_origen": limpia_texto(campo(nodo, "camaraorigen")),
        "autores": sorted(dict.fromkeys(autores))[:40],
        "materias": materias[:40],
        "ministerios": ministerios[:15],
        "admisible": campo(nodo, "admisible"),
        "origen_dato": "camara",
    }


def consulta_camara_boletin(boletin: str) -> dict[str, Any] | None:
    """Complementa la ficha con materias, autores y ministerios patrocinantes."""
    b = normaliza_boletin(boletin)
    if not b or "-" not in b:
        return None
    url = url_camara("retornarProyectoLey", prmNumeroBoletin=b)
    try:
        raw, _, _ = descarga(url)
    except Exception as exc:
        cobertura("camara_boletin", error=f"{b}: {type(exc).__name__}: {exc}")
        return None
    raiz = parsea_xml(raw)
    if raiz is None:
        cobertura("camara_boletin", error=f"{b}: XML ilegible")
        return None
    nodo = raiz if _tag(raiz) == "proyectoley" else (nodos(raiz, "proyectoley") or [None])[0]
    if nodo is None:
        cobertura("camara_boletin", error=f"{b}: sin nodo ProyectoLey")
        return None
    datos = parsea_proyecto_camara(nodo)
    if not datos.get("boletin"):
        datos["boletin"] = b
    cobertura("camara_boletin", resultados=1)
    return datos


def consulta_camara_anno(anno: int) -> list[dict[str, Any]]:
    """Universo de mociones y mensajes ingresados en un año legislativo."""
    resultados: list[dict[str, Any]] = []
    for operacion in ("retornarMocionesXAnno", "retornarMensajesXAnno"):
        url = url_camara(operacion, prmAnno=anno)
        try:
            raw, _, _ = descarga(url)
        except Exception as exc:
            cobertura("camara_anno", error=f"{operacion} {anno}: {type(exc).__name__}: {exc}")
            continue
        raiz = parsea_xml(raw)
        if raiz is None:
            cobertura("camara_anno", error=f"{operacion} {anno}: XML ilegible")
            continue
        encontrados = 0
        for nodo in nodos(raiz, "proyectoley"):
            datos = parsea_proyecto_camara(nodo)
            if datos.get("boletin"):
                datos["canal_descubrimiento"] = f"camara_{operacion}"
                resultados.append(datos)
                encontrados += 1
        cobertura("camara_anno", resultados=encontrados)
    return resultados


# ---------------------------------------------------------------------------
# Fusión de fuentes y construcción del registro
# ---------------------------------------------------------------------------


def fusiona(senado: dict[str, Any] | None, camara: dict[str, Any] | None,
            semilla: dict[str, Any] | None = None) -> dict[str, Any]:
    """Combina ambas fuentes privilegiando al Senado en tramitación.

    El Senado entrega el itinerario de trámites y las urgencias; la Cámara
    entrega materias clasificadas, autores completos y ministerios. Ninguna de
    las dos es suficiente por sí sola para evaluar impacto regulatorio.
    """
    base: dict[str, Any] = {
        "boletin": "", "titulo": "", "fecha_ingreso": "", "etapa": "", "subetapa": "",
        "iniciativa": "", "camara_origen": "", "urgencia": "", "ley_numero": "",
        "refundidos": "", "estado": "", "link_texto_original": "",
        "tramitacion": [], "urgencias": [], "votaciones": [], "autores": [],
        "materias": [], "comisiones": [], "informes": [], "ministerios": [],
        "camara_id": "", "resumen": "", "fuentes": [],
    }
    for fuente in (semilla, camara, senado):
        if not fuente:
            continue
        etiqueta = fuente.get("origen_dato") or "semilla"
        if etiqueta not in base["fuentes"]:
            base["fuentes"].append(etiqueta)
        for clave, valor in fuente.items():
            if clave in ("origen_dato", "canal_descubrimiento"):
                continue
            if clave not in base:
                base[clave] = valor
                continue
            if isinstance(valor, list):
                if valor:
                    existente = base.get(clave) or []
                    if clave in ("tramitacion", "urgencias", "votaciones", "informes"):
                        # Estructuras del Senado: se reemplazan completas, no se mezclan.
                        if len(valor) >= len(existente):
                            base[clave] = valor
                    else:
                        base[clave] = sorted(dict.fromkeys([*existente, *valor]))
            elif valor not in ("", None):
                base[clave] = valor

    base["boletin"] = normaliza_boletin(base.get("boletin"))
    return base


def huella_tramitacion(proy: dict[str, Any]) -> str:
    """Firma del estado procesal: cambia solo si el proyecto realmente se movió.

    Comparar la ficha completa produciría falsos movimientos por reordenamientos
    o campos volátiles. La firma se limita a lo que un analista consideraría un
    cambio de estado real.
    """
    tramites = proy.get("tramitacion") or []
    ultimo = tramites[-1] if tramites else {}
    piezas = [
        normaliza(proy.get("etapa")),
        normaliza(proy.get("subetapa")),
        normaliza_urgencia(proy.get("urgencia")),
        normaliza(proy.get("ley_numero")),
        str(len(tramites)),
        normaliza(ultimo.get("fecha")),
        normaliza(ultimo.get("descripcion"))[:120],
        str(len(proy.get("votaciones") or [])),
    ]
    return hashlib.sha1("|".join(piezas).encode("utf-8")).hexdigest()[:20]


def ultimo_movimiento(proy: dict[str, Any]) -> datetime | None:
    fechas = []
    for t in proy.get("tramitacion") or []:
        f = parsea_fecha(t.get("fecha"))
        if f:
            fechas.append(f)
    for v in proy.get("votaciones") or []:
        f = parsea_fecha(v.get("fecha"))
        if f:
            fechas.append(f)
    if not fechas:
        f = parsea_fecha(proy.get("fecha_ingreso"))
        return f
    return max(fechas)


def construye_registro(proy: dict[str, Any]) -> dict[str, Any]:
    """Registro publicable: pertinencia, estado procesal, prioridad y enlaces."""
    boletin = normaliza_boletin(proy.get("boletin"))
    reg = dict(proy)
    reg["boletin"] = boletin
    reg["id"] = id_registro(boletin)

    pert = evalua_pertinencia(reg)
    reg["puntaje_pertinencia"] = pert["puntaje"]
    reg["nivel_impacto"] = pert["nivel"]
    reg["evidencia"] = pert["evidencia"]
    reg["sectores"] = pert["sectores"]
    reg["sectores_legibles"] = [ETIQUETAS_SECTORES.get(s, s) for s in pert["sectores"]]
    reg["ejes"] = clasifica_ejes(reg)
    reg["ejes_legibles"] = [ETIQUETAS_EJES.get(e, e) for e in reg["ejes"]]
    reg["impacto_legible"] = ETIQUETAS_IMPACTO.get(pert["nivel"], pert["nivel"])

    # El motor lee título, materias, comisiones y tramitación, no el articulado.
    # En un proyecto ómnibus eso no alcanza: una norma que alcanza a la UAF puede
    # viajar en el artículo 31 sin dejar rastro en ninguno de esos campos. En vez
    # de fingir una clasificación, el registro se marca para revisión de analista.
    titulo = reg.get("titulo", "")
    ambiguo = titulo_omnibus(titulo) or (
        titulo_poco_informativo(titulo)
        and materia_boletin(boletin) in MATERIAS_SENSIBLES
    )
    reg["requiere_revision_manual"] = bool(
        ambiguo and pert["nivel"] in ("descartado", "seguimiento", "sectorial")
    )

    reg["urgencia_clave"] = normaliza_urgencia(reg.get("urgencia"))
    reg["urgencia_legible"] = ETIQUETAS_URGENCIA.get(reg["urgencia_clave"], "Sin urgencia")
    reg["etapa_ordinal"] = etapa_ordinal(reg.get("etapa"), reg.get("subetapa"))
    reg["vigente"] = esta_vigente(reg)

    mov = ultimo_movimiento(reg)
    reg["ultimo_movimiento"] = mov.isoformat() if mov else ""
    reg["ultimo_movimiento_legible"] = fecha_legible(mov)
    reg["dias_sin_movimiento"] = dias_desde(mov)

    tramites = reg.get("tramitacion") or []
    if tramites:
        reg["ultimo_tramite"] = tramites[-1].get("descripcion", "")
        reg["camara_actual"] = tramites[-1].get("camara", "") or reg.get("camara_origen", "")
    else:
        reg["ultimo_tramite"] = ""
        reg["camara_actual"] = reg.get("camara_origen", "")
    reg["total_tramites"] = len(tramites)

    ingreso = parsea_fecha(reg.get("fecha_ingreso"))
    reg["fecha_ingreso_legible"] = fecha_legible(ingreso)
    reg["antiguedad_dias"] = dias_desde(ingreso)

    reg.update(calcula_prioridad(reg))
    reg["huella"] = huella_tramitacion(reg)

    reg["link_senado"] = SENADO_FICHA.format(urllib.parse.quote(boletin))
    if reg.get("camara_id"):
        reg["link_camara"] = CAMARA_FICHA.format(
            urllib.parse.quote(str(reg["camara_id"])), urllib.parse.quote(boletin))
    else:
        reg["link_camara"] = ""
    reg["link_ws_senado"] = url_senado_boletin(boletin)

    # Resumen operativo de una línea para el correo y el listado.
    partes = []
    if reg["urgencia_clave"] != "sin urgencia":
        partes.append(reg["urgencia_legible"])
    if reg.get("etapa"):
        partes.append(reg["etapa"])
    if reg.get("ultimo_tramite"):
        partes.append(reg["ultimo_tramite"])
    reg["sintesis"] = " · ".join(p for p in partes if p)[:400]
    return reg


# ---------------------------------------------------------------------------
# Semillas y exclusiones
# ---------------------------------------------------------------------------

SEMILLAS_PREDETERMINADAS = [
    {"boletin": "15975-25", "nota": "Crea el Subsistema de Inteligencia Económica"},
    {"boletin": "18407-25", "nota": "Agrava sanciones en materia de lavado de activos"},
    {"boletin": "18373-07", "nota": "Levantamiento del secreto bancario con control judicial"},
    {"boletin": "16808-25", "nota": "Lavado de activos y comercio ilegal"},
    {"boletin": "16764-03", "nota": "Límites a transacciones en dinero efectivo"},
    {"boletin": "18080-03", "nota": "Transparencia y trazabilidad en operaciones prendarias"},
    {"boletin": "18488-07", "nota": "Persecución penal y patrimonial del crimen organizado"},
    {"boletin": "18217-07", "nota": "Criminalidad organizada y terrorismo"},
    {"boletin": "18369-07", "nota": "Contrabando de tabaco"},
    {"boletin": "18420-25", "nota": "Seguridad portuaria frente al crimen organizado"},
    {"boletin": "12234-02", "nota": "Sistema de inteligencia del Estado (Ley 21.821)"},
]


def carga_semillas() -> list[dict[str, Any]]:
    """Boletines de seguimiento permanente, siempre reconsultados.

    Sirven como red de seguridad: si el descubrimiento automático falla o el
    proyecto pasa meses sin movimiento, la cartera crítica sigue vigilada.
    """
    semillas = {normaliza_boletin(s["boletin"]): dict(s) for s in SEMILLAS_PREDETERMINADAS
                if normaliza_boletin(s.get("boletin"))}
    if SEMILLAS_ARCHIVO.exists():
        try:
            data = json.loads(SEMILLAS_ARCHIVO.read_text(encoding="utf-8"))
            items = data.get("boletines", []) if isinstance(data, dict) else data
            for item in items:
                if isinstance(item, str):
                    item = {"boletin": item}
                b = normaliza_boletin(item.get("boletin"))
                if b:
                    semillas[b] = {"boletin": b, "nota": limpia_texto(item.get("nota", ""))}
        except Exception as exc:
            log(f"! boletines_semilla.json inválido: {type(exc).__name__}: {exc}")
    for b, s in semillas.items():
        s["boletin"] = b
        s["semilla"] = True
    return list(semillas.values())


def carga_exclusiones() -> set[str]:
    """Boletines verificados como falsos positivos, excluidos de forma auditable."""
    excluidos: set[str] = set()
    if EXCLUSIONES_ARCHIVO.exists():
        try:
            data = json.loads(EXCLUSIONES_ARCHIVO.read_text(encoding="utf-8"))
            items = data.get("exclusiones", []) if isinstance(data, dict) else data
            for item in items:
                b = normaliza_boletin(item.get("boletin") if isinstance(item, dict) else item)
                if b:
                    excluidos.add(b)
        except Exception as exc:
            log(f"! exclusiones_boletines.json inválido: {type(exc).__name__}: {exc}")
    return excluidos


# ---------------------------------------------------------------------------
# Estado persistente
# ---------------------------------------------------------------------------


def carga_json(ruta: Path, defecto: Any) -> Any:
    try:
        return json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else copy.deepcopy(defecto)
    except Exception:
        return copy.deepcopy(defecto)


def carga_estado() -> dict[str, Any]:
    estado = carga_json(ESTADO, {})
    if estado.get("esquema") != ESQUEMA_ESTADO:
        estado = {
            "esquema": ESQUEMA_ESTADO,
            "huellas": estado.get("huellas", {}),
            "cartera": estado.get("cartera", []),
            "migracion_pendiente": True,
        }
    estado.setdefault("huellas", {})
    estado.setdefault("cartera", [])
    estado.setdefault("esquema", ESQUEMA_ESTADO)
    return estado


def guarda_estado(estado: dict[str, Any]) -> None:
    corte = ahora_cl() - timedelta(days=RETENCION_HISTORIAL_DIAS)
    huellas = {}
    for boletin, dato in (estado.get("huellas") or {}).items():
        visto = parsea_fecha(dato.get("visto"))
        if not visto or visto >= corte:
            huellas[boletin] = dato
    estado["huellas"] = dict(list(huellas.items())[-20_000:])
    estado["cartera"] = list(dict.fromkeys(estado.get("cartera", [])))[-20_000:]
    temporal = ESTADO.with_suffix(".tmp")
    temporal.write_text(json.dumps(estado, ensure_ascii=False, indent=1, default=json_default),
                        encoding="utf-8")
    os.replace(temporal, ESTADO)


def carga_previos() -> dict[str, Any]:
    return carga_json(SALIDA, {"proyectos": [], "descartados": []})


# ---------------------------------------------------------------------------
# Descubrimiento
# ---------------------------------------------------------------------------


def descubre(modo: str, estado: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Reúne boletines candidatos desde todos los canales disponibles.

    Devuelve el mapa boletín -> datos preliminares y un resumen por canal.
    """
    candidatos: dict[str, dict[str, Any]] = {}
    resumen = {"semillas": 0, "cartera": 0, "senado_movimiento": 0, "camara_anno": 0}

    def incorpora(datos: dict[str, Any], canal: str) -> None:
        b = normaliza_boletin(datos.get("boletin"))
        if not b or "-" not in b:
            return
        actual = candidatos.setdefault(b, {"boletin": b, "canales": []})
        if canal not in actual["canales"]:
            actual["canales"].append(canal)
        for clave, valor in datos.items():
            if clave in ("canales", "canal_descubrimiento"):
                continue
            if valor in ("", None, [], {}):
                continue
            actual.setdefault(clave, valor)

    # 1. Semillas: cartera crítica de seguimiento permanente.
    semillas = carga_semillas()
    for s in semillas:
        incorpora({"boletin": s["boletin"], "nota_semilla": s.get("nota", ""),
                   "es_semilla": True}, "semilla")
    resumen["semillas"] = len(semillas)

    # 2. Cartera acumulada: todo lo que ya fue clasificado como pertinente.
    for b in estado.get("cartera", []):
        incorpora({"boletin": b}, "cartera")
        resumen["cartera"] += 1

    # 3. Movimiento reciente en el Senado (canal incremental principal).
    dias = VENTANA_MOVIMIENTO_RAPIDO if modo == "rapido" else VENTANA_MOVIMIENTO_CONCILIACION
    desde = ahora_cl() - timedelta(days=dias)
    for datos in consulta_senado_movimiento(desde):
        incorpora(datos, "senado_movimiento")
        resumen["senado_movimiento"] += 1

    # 4. Universo anual de la Cámara (solo en conciliación: es costoso).
    if modo == "conciliacion" and CONSULTA_CAMARA and not tiempo_agotado(240):
        anno_actual = ahora_cl().year
        for anno in range(anno_actual, anno_actual - ANNOS_CONCILIACION, -1):
            if tiempo_agotado(180):
                break
            for datos in consulta_camara_anno(anno):
                incorpora(datos, "camara_anno")
                resumen["camara_anno"] += 1

    excluidos = carga_exclusiones()
    for b in list(candidatos):
        if b in excluidos:
            candidatos.pop(b, None)

    if len(candidatos) > MAX_CANDIDATOS:
        # Prioriza semillas y cartera cuando el universo se desborda.
        ordenados = sorted(
            candidatos.items(),
            key=lambda kv: (
                0 if kv[1].get("es_semilla") else 1,
                0 if "cartera" in kv[1].get("canales", []) else 1,
            ),
        )
        candidatos = dict(ordenados[:MAX_CANDIDATOS])

    return candidatos, resumen


# Títulos que no describen el contenido, sino el continente. Los proyectos
# ómnibus del Ejecutivo agrupan decenas de materias heterogéneas bajo un
# encabezado genérico: el boletín 18216-05 ("Para la reconstrucción nacional y
# el desarrollo económico y social") reúne 38 artículos permanentes de materia
# tributaria, ambiental, laboral y municipal. Descartarlos por título sería
# perder justamente los proyectos donde una norma que afecta a la UAF viaja
# escondida entre otras cien.
PATRONES_TITULO_GENERICO = [
    r"^para la (?:reconstruccion|reactivacion|modernizacion|reforma)",
    r"^modifica diversos cuerpos legales\s*$",
    r"^modifica (?:los|las|diversas) (?:leyes|normas|disposiciones) que (?:indica|senala)\s*$",
    r"^(?:establece|dicta|aprueba|fija) (?:normas|medidas|disposiciones) (?:que indica|que senala|varias|diversas)",
    r"\bley (?:de|sobre) presupuestos\b",
    r"\bagenda (?:economica|legislativa|de crecimiento|antidelincuencia)\b",
    r"\b(?:miscelanea|misceláneo|misceláneas|omnibus)\b",
    r"^(?:sobre|acerca de) (?:medidas|materias) (?:economicas|tributarias|varias)",
    r"^(?:reforma|reajuste|modernizacion) (?:tributaria|del estado|institucional)",
    r"\bcrecimiento economico\b",
    r"\bdesarrollo economico y social\b",
]

# Códigos de materia del boletín con densidad histórica de normas que alcanzan
# a la UAF: 05 Hacienda, 07 Justicia, 25 Seguridad Pública, 03 Economía,
# 06 Gobierno Interior, 02 Defensa. No basta por sí solo para incluir, pero
# eleva a un título genérico por sobre el resto de la cola.
MATERIAS_SENSIBLES = {"02", "03", "05", "06", "07", "25"}

MAX_GENERICOS = env_int("MONITOR_MAX_GENERICOS", 140)


@lru_cache(maxsize=2048)
def titulo_omnibus(titulo: str) -> bool:
    """El título es un contenedor: agrupa materias que no anuncia.

    Es la condición para retener un proyecto pendiente de criterio humano.
    Un ómnibus reúne decenas de normas heterogéneas, así que la ausencia de
    señales en el título, las materias y los trámites no permite concluir nada.
    """
    plano = normaliza(titulo)
    return bool(plano) and any(re.search(pat, plano) for pat in PATRONES_TITULO_GENERICO)


# Palabras que no aportan contenido al medir cuán informativo es un título.
VACIAS_TITULO = {"ley", "de", "del", "la", "las", "el", "los", "y", "o", "en",
                 "para", "por", "con", "sobre", "que", "un", "una", "al", "a",
                 "sus", "su", "e", "modifica", "establece", "crea", "regula"}


@lru_cache(maxsize=2048)
def titulo_poco_informativo(titulo: str) -> bool:
    """El título es demasiado escueto para descartar el boletín con confianza.

    Distinto de ``titulo_omnibus``: aquí solo se justifica gastar una consulta
    para mirar las materias y comisiones reales. Si con ese material completo
    el proyecto sigue sin señales, se descarta como cualquier otro. Un título
    breve pero descriptivo —"Ley de protección tarifaria eléctrica"— no debe
    quedar retenido de forma indefinida en la cartera.
    """
    plano = normaliza(titulo)
    if not plano:
        return True
    sustantivas = [w for w in plano.split() if w not in VACIAS_TITULO]
    return len(sustantivas) <= 3


def titulo_generico(titulo: str) -> bool:
    """Motivos para no descartar un boletín solo por su título."""
    return titulo_omnibus(titulo) or titulo_poco_informativo(titulo)


def preselecciona(candidatos: dict[str, dict[str, Any]], modo: str) -> list[str]:
    """Decide qué boletines merecen una consulta completa a los servicios.

    Un año legislativo trae más de mil proyectos y solo una fracción toca el
    perímetro de la UAF; descargar la ficha de todos sería lento y descortés
    con el servicio. Pero el descarte por título tiene un riesgo asimétrico:
    un falso positivo cuesta una llamada de red, un falso negativo cuesta que
    un proyecto relevante nunca aparezca en el tablero.

    Por eso se ordena en niveles y solo se descarta el caso claro: título
    informativo que puntúa bajo el umbral. Todo lo ambiguo pasa a consulta.
    """
    # nivel 0 cartera y semillas · 1 pertinente por título · 2 sin título
    # · 3 título genérico en materia sensible · 4 título genérico
    niveles: list[tuple[int, float, str]] = []
    genericos = 0

    for boletin, datos in candidatos.items():
        if datos.get("es_semilla") or "cartera" in (datos.get("canales") or []):
            niveles.append((0, 10_000.0, boletin))
            continue

        titulo = datos.get("titulo") or ""
        if not titulo:
            niveles.append((2, 0.0, boletin))
            continue

        pert = evalua_pertinencia({"titulo": titulo,
                                   "materias": datos.get("materias") or []})
        if pert["nivel"] != "descartado":
            niveles.append((1, pert["puntaje"], boletin))
            continue

        # Puntuó bajo, pero el título no describe el contenido: no se descarta.
        if titulo_generico(titulo):
            sensible = materia_boletin(boletin) in MATERIAS_SENSIBLES
            niveles.append((3 if sensible else 4, pert["puntaje"], boletin))
            genericos += 1

    # Los genéricos se consultan, pero acotados: son una red de seguridad, no
    # una puerta abierta a barrer el Congreso completo en cada corrida.
    niveles.sort(key=lambda x: (x[0], -x[1]))
    seleccion: list[str] = []
    usados_genericos = 0
    for nivel, _, boletin in niveles:
        if nivel >= 3:
            if usados_genericos >= MAX_GENERICOS:
                continue
            usados_genericos += 1
        seleccion.append(boletin)

    limite = MAX_ENRIQUECER_RAPIDO if modo == "rapido" else MAX_ENRIQUECER_CONCILIACION
    return seleccion[:limite]


def enriquece(boletin: str, previo: dict[str, Any]) -> dict[str, Any] | None:
    """Descarga la ficha completa del boletín en ambas cámaras."""
    senado = consulta_senado_boletin(boletin)
    camara = None
    if CONSULTA_CAMARA and not tiempo_agotado(60):
        camara = consulta_camara_boletin(boletin)
    if not senado and not camara:
        return None
    semilla = {k: v for k, v in previo.items()
               if k not in ("canales",) and v not in ("", None, [], {})}
    semilla.pop("origen_dato", None)
    fusionado = fusiona(senado, camara, semilla)
    fusionado["boletin"] = normaliza_boletin(boletin)
    fusionado["canales_descubrimiento"] = previo.get("canales", [])
    return fusionado


# ---------------------------------------------------------------------------
# Métricas
# ---------------------------------------------------------------------------


def ranking(registros: list[dict[str, Any]], clave: str,
            etiquetas: dict[str, str] | None = None) -> list[dict[str, Any]]:
    cuenta: Counter[str] = Counter()
    for r in registros:
        valor = r.get(clave)
        if isinstance(valor, list):
            cuenta.update(v for v in valor if v)
        elif valor:
            cuenta[str(valor)] += 1
    return [{"clave": k, "etiqueta": (etiquetas or {}).get(k, k), "total": v}
            for k, v in cuenta.most_common(20)]


def calcula_metricas(proyectos: list[dict[str, Any]], ahora: datetime) -> dict[str, Any]:
    vigentes = [p for p in proyectos if p.get("vigente")]
    con_urgencia = [p for p in vigentes if p.get("urgencia_clave") != "sin urgencia"]
    directos = [p for p in proyectos if p.get("nivel_impacto") == "directo"]

    def movidos(dias: int) -> list[dict[str, Any]]:
        return [p for p in proyectos
                if p.get("dias_sin_movimiento") is not None
                and p["dias_sin_movimiento"] <= dias]

    etapas: Counter[int] = Counter(p.get("etapa_ordinal", 1) for p in vigentes)
    nombres_etapa = {
        1: "Primer trámite", 2: "Segundo trámite", 3: "Tercer trámite",
        4: "Comisión mixta", 5: "Veto", 6: "Tribunal Constitucional",
        7: "Tramitación terminada", 8: "Publicado", 0: "Cerrado o archivado",
    }

    return {
        "total": len(proyectos),
        "vigentes": len(vigentes),
        "impacto_directo": len(directos),
        "impacto_estructural": sum(1 for p in proyectos if p.get("nivel_impacto") == "estructural"),
        "impacto_sectorial": sum(1 for p in proyectos if p.get("nivel_impacto") == "sectorial"),
        "con_urgencia": len(con_urgencia),
        "discusion_inmediata": sum(1 for p in vigentes if p.get("urgencia_clave") == "discusion inmediata"),
        "prioridad_critica": sum(1 for p in vigentes if p.get("banda_prioridad") == "critica"),
        "prioridad_alta": sum(1 for p in vigentes if p.get("banda_prioridad") == "alta"),
        "movimiento_7d": len(movidos(7)),
        "movimiento_30d": len(movidos(30)),
        "requieren_revision_manual": sum(1 for p in vigentes
                                        if p.get("requiere_revision_manual")),
        "estancados_180d": sum(1 for p in vigentes
                               if (p.get("dias_sin_movimiento") or 0) > 180),
        "pipeline": [{"ordinal": k, "etapa": nombres_etapa.get(k, str(k)), "total": v}
                     for k, v in sorted(etapas.items())],
        "por_eje": ranking(proyectos, "ejes", ETIQUETAS_EJES),
        "por_sector": ranking(proyectos, "sectores", ETIQUETAS_SECTORES),
        "por_urgencia": ranking(vigentes, "urgencia_clave", ETIQUETAS_URGENCIA),
        "por_camara": ranking(vigentes, "camara_actual"),
        "por_iniciativa": ranking(proyectos, "iniciativa"),
        "generado": ahora.isoformat(),
    }


# ---------------------------------------------------------------------------
# Configuración y correo
# ---------------------------------------------------------------------------


def carga_config() -> dict[str, Any]:
    if not CONFIG.exists():
        try:
            CONFIG.write_text(json.dumps(CONFIG_EJEMPLO, ensure_ascii=False, indent=2,
                                         default=json_default), encoding="utf-8")
        except OSError:
            pass
    cfg = carga_json(CONFIG, CONFIG_EJEMPLO)
    correo = cfg.setdefault("correo", {})
    mapa = {
        "activo": ("MONITOR_CORREO_ACTIVO", env_bool),
        "servidor": ("MONITOR_SMTP_SERVIDOR", str),
        "puerto": ("MONITOR_SMTP_PUERTO", int),
        "seguridad": ("MONITOR_SMTP_SEGURIDAD", str),
        "usuario": ("MONITOR_SMTP_USUARIO", str),
        "clave": ("MONITOR_SMTP_CLAVE", str),
        "remitente_nombre": ("MONITOR_REMITENTE_NOMBRE", str),
        "minimo_para_avisar": ("MONITOR_MINIMO_AVISO", int),
        "silencio_minutos": ("MONITOR_SILENCIO_MINUTOS", int),
        "solo_impacto_directo": ("MONITOR_SOLO_DIRECTO", env_bool),
        "avisar_solo_con_urgencia": ("MONITOR_SOLO_URGENCIA", env_bool),
    }
    for clave, (env, conv) in mapa.items():
        valor = os.getenv(env)
        if valor is not None and valor != "":
            try:
                correo[clave] = conv(env, correo.get(clave)) if conv is env_bool else conv(valor)
            except Exception:
                pass
    dest = os.getenv("MONITOR_DESTINATARIOS")
    if dest:
        correo["destinatarios"] = [x.strip() for x in dest.split(",") if x.strip()]
    return cfg


def envia_correo(novedades: list[dict[str, Any]], estado: dict[str, Any], modo: str) -> None:
    """Aviso por SMTP de movimientos legislativos relevantes."""
    cfg = carga_config().get("correo", {})
    if not cfg.get("activo"):
        return
    silencio = max(0, int(cfg.get("silencio_minutos", 0) or 0))
    ultimo = parsea_fecha(estado.get("ultimo_correo"))
    if silencio and ultimo and ultimo > ahora_cl() - timedelta(minutes=silencio):
        log(f"Correo omitido por silencio de {silencio} minutos.")
        return

    avisos = list(novedades)
    if cfg.get("solo_impacto_directo"):
        avisos = [a for a in avisos if a.get("nivel_impacto") == "directo"]
    if cfg.get("avisar_solo_con_urgencia"):
        avisos = [a for a in avisos if a.get("urgencia_clave") != "sin urgencia"]
    if not avisos or len(avisos) < int(cfg.get("minimo_para_avisar", 1)):
        return
    destinatarios = cfg.get("destinatarios") or []
    if not destinatarios:
        return

    avisos.sort(key=lambda a: a.get("prioridad", 0), reverse=True)
    criticos = sum(1 for a in avisos if a.get("banda_prioridad") in ("critica", "alta"))

    msg = EmailMessage()
    asunto = f"Monitor Legislativo UAF: {len(avisos)} movimiento(s)"
    if criticos:
        asunto += f" · {criticos} de prioridad alta"
    msg["Subject"] = asunto
    msg["From"] = formataddr((cfg.get("remitente_nombre", "Monitor Legislativo UAF"),
                              cfg.get("usuario", "")))
    msg["To"] = ", ".join(destinatarios)
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid()

    lineas = ["Movimientos en proyectos de ley con impacto potencial en la Ley N° 19.913:", ""]
    for a in avisos[:30]:
        etiqueta = {"nuevo": "NUEVO EN CARTERA", "movimiento": "MOVIMIENTO",
                    "urgencia": "CAMBIO DE URGENCIA"}.get(a.get("novedad", ""), "ACTUALIZACIÓN")
        lineas += [
            f"[{etiqueta}] Boletín {a.get('boletin')} · {a.get('impacto_legible')}"
            f" · prioridad {a.get('banda_prioridad', '').upper()}",
            a.get("titulo", ""),
            a.get("sintesis", ""),
            f"Último movimiento: {a.get('ultimo_movimiento_legible') or 'sin registro'}",
            a.get("link_senado", ""),
            "",
        ]
    lineas += ["--", f"Motor {VERSION_MONITOR} · modo {modo}",
               "Fuente: servicios de datos abiertos del Senado y de la Cámara de Diputadas y Diputados."]
    msg.set_content("\n".join(lineas))

    servidor = cfg.get("servidor")
    puerto = int(cfg.get("puerto", 587))
    seguridad = str(cfg.get("seguridad", "starttls")).lower()
    usuario = cfg.get("usuario", "")
    clave = cfg.get("clave", "")
    contexto = ssl.create_default_context()
    if seguridad == "ssl":
        with smtplib.SMTP_SSL(servidor, puerto, context=contexto, timeout=30) as smtp:
            if usuario:
                smtp.login(usuario, clave)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(servidor, puerto, timeout=30) as smtp:
            smtp.ehlo()
            if seguridad == "starttls":
                smtp.starttls(context=contexto)
                smtp.ehlo()
            if usuario:
                smtp.login(usuario, clave)
            smtp.send_message(msg)
    estado["ultimo_correo"] = ahora_cl().isoformat()


# ---------------------------------------------------------------------------
# Ejecución principal
# ---------------------------------------------------------------------------


def ejecutar(modo: str) -> int:
    modo = modo.lower()
    if modo not in {"rapido", "conciliacion"}:
        raise ValueError("modo debe ser rapido o conciliacion")

    estado = carga_estado()
    migracion = bool(estado.pop("migracion_pendiente", False))
    previos = carga_previos()
    previos_por_boletin = {normaliza_boletin(p.get("boletin")): p
                           for p in (previos.get("proyectos") or [])
                           if normaliza_boletin(p.get("boletin"))}
    ahora = ahora_cl()
    log(f"Inicio motor {VERSION_MONITOR} · modo={modo} · migracion={migracion}")

    candidatos, resumen_canales = descubre(modo, estado)
    seleccion = preselecciona(candidatos, modo)
    log(f"Candidatos={len(candidatos)} · a consultar={len(seleccion)} · canales={resumen_canales}")

    enriquecidos: list[dict[str, Any]] = []
    fallidos = 0
    ex = ThreadPoolExecutor(max_workers=HILOS)
    futuros = {ex.submit(enriquece, b, candidatos.get(b, {})): b for b in seleccion}
    try:
        for fut in as_completed(futuros):
            if tiempo_agotado(90):
                for pendiente in futuros:
                    pendiente.cancel()
                log("! Presupuesto de tiempo agotado: se publica lo obtenido hasta aquí.")
                break
            try:
                datos = fut.result()
            except Exception as exc:
                fallidos += 1
                log(f"! error al consultar {futuros[fut]}: {type(exc).__name__}: {exc}")
                continue
            if datos:
                enriquecidos.append(datos)
            else:
                fallidos += 1
    finally:
        ex.shutdown(wait=False, cancel_futures=True)

    log(f"Fichas obtenidas={len(enriquecidos)} · fallidas={fallidos}")

    # Construcción, clasificación y detección de novedades
    registros: list[dict[str, Any]] = []
    descartados: list[dict[str, Any]] = []
    novedades: list[dict[str, Any]] = []
    huellas = estado.setdefault("huellas", {})

    for datos in enriquecidos:
        reg = construye_registro(datos)
        if not reg.get("boletin"):
            continue

        es_semilla = bool(candidatos.get(reg["boletin"], {}).get("es_semilla"))
        revisable = bool(reg.get("requiere_revision_manual")) and reg.get("vigente")
        if reg["nivel_impacto"] == "descartado" and not es_semilla and not revisable:
            descartados.append({
                "boletin": reg["boletin"], "titulo": reg.get("titulo", ""),
                "puntaje_pertinencia": reg.get("puntaje_pertinencia", 0),
                "motivo": "bajo umbral de pertinencia",
                "revisado": ahora.isoformat(),
            })
            huellas.pop(reg["boletin"], None)
            continue
        if reg["nivel_impacto"] == "descartado" and (es_semilla or revisable):
            # Se conserva: una semilla por decisión editorial, un ómnibus porque
            # el motor no tiene material para pronunciarse sobre él.
            reg["nivel_impacto"] = "seguimiento"
            reg["impacto_legible"] = ETIQUETAS_IMPACTO["seguimiento"]
            reg.update(calcula_prioridad(reg))

        previo_huella = (huellas.get(reg["boletin"]) or {}).get("huella")
        previo_urgencia = (huellas.get(reg["boletin"]) or {}).get("urgencia")
        if previo_huella is None:
            reg["novedad"] = "nuevo"
        elif previo_huella != reg["huella"]:
            reg["novedad"] = ("urgencia"
                              if previo_urgencia and previo_urgencia != reg["urgencia_clave"]
                              else "movimiento")
        else:
            reg["novedad"] = ""

        if reg["novedad"]:
            reg["novedad_detectada"] = ahora.isoformat()
            novedades.append(reg)
        else:
            anterior = previos_por_boletin.get(reg["boletin"], {})
            reg["novedad_detectada"] = anterior.get("novedad_detectada", "")

        huellas[reg["boletin"]] = {
            "huella": reg["huella"],
            "urgencia": reg["urgencia_clave"],
            "nivel": reg["nivel_impacto"],
            "visto": ahora.isoformat(),
        }
        registros.append(reg)

    # Conserva proyectos ya publicados que esta corrida no alcanzó a revisar.
    vistos = {r["boletin"] for r in registros}
    conservados = 0
    for boletin, anterior in previos_por_boletin.items():
        if boletin in vistos:
            continue
        anterior = dict(anterior)
        anterior["novedad"] = ""
        anterior["no_revisado_en_corrida"] = True
        registros.append(anterior)
        conservados += 1

    registros.sort(key=lambda r: (-(r.get("prioridad") or 0), r.get("boletin", "")))
    estado["cartera"] = [r["boletin"] for r in registros if r.get("boletin")]

    metricas = calcula_metricas(registros, ahora)
    if modo == "conciliacion":
        estado["ultima_conciliacion"] = ahora.isoformat()

    cobertura_canales = []
    for canal in ("senado_movimiento", "senado_boletin", "camara_boletin", "camara_anno"):
        reg = _COBERTURA.get(canal, {
            "canal": canal, "llamadas": 0, "resultados": 0,
            "errores": ["no consultado en esta corrida"], "consultado": False,
        })
        cobertura_canales.append(dict(reg))

    salida = {
        "generado": ahora.isoformat(),
        "generado_legible": ahora.strftime("%d/%m/%Y %H:%M"),
        "version_motor": VERSION_MONITOR,
        "modo_ejecucion": modo,
        "metricas": metricas,
        "proyectos": registros,
        "descartados": descartados[:400],
        "novedades": len(novedades),
        "catalogos": {
            "ejes": ETIQUETAS_EJES,
            "sectores": ETIQUETAS_SECTORES,
            "impacto": ETIQUETAS_IMPACTO,
            "urgencia": ETIQUETAS_URGENCIA,
        },
        "auditoria": {
            "modo": modo,
            "candidatos_descubiertos": len(candidatos),
            "boletines_consultados": len(seleccion),
            "fichas_obtenidas": len(enriquecidos),
            "consultas_fallidas": fallidos,
            "registros_publicados": len(registros),
            "registros_conservados_sin_revisar": conservados,
            "descartados_por_pertinencia": len(descartados),
            "retenidos_para_revision_manual": sum(
                1 for r in registros if r.get("requiere_revision_manual")),
            "novedades_corrida": len(novedades),
            "nuevos_en_cartera": sum(1 for n in novedades if n.get("novedad") == "nuevo"),
            "con_movimiento": sum(1 for n in novedades if n.get("novedad") == "movimiento"),
            "cambios_urgencia": sum(1 for n in novedades if n.get("novedad") == "urgencia"),
            "canales": resumen_canales,
            "cobertura_canales": cobertura_canales,
            "ultima_conciliacion": estado.get("ultima_conciliacion"),
            "migracion_estado": migracion,
            "umbral_pertinencia": UMBRAL_PERTINENCIA,
            "consulta_camara": CONSULTA_CAMARA,
            "respeta_robots": RESPETA_ROBOTS,
            "ventana_movimiento_dias": (VENTANA_MOVIMIENTO_RAPIDO if modo == "rapido"
                                        else VENTANA_MOVIMIENTO_CONCILIACION),
            "semillas_configuradas": len(carga_semillas()),
            "boletines_excluidos": len(carga_exclusiones()),
            "segundos_corrida": round(time.monotonic() - INICIO, 1),
        },
    }

    temporal = SALIDA.with_suffix(".tmp")
    temporal.write_text(json.dumps(salida, ensure_ascii=False, indent=1, default=json_default),
                        encoding="utf-8")
    os.replace(temporal, SALIDA)

    if migracion:
        log("Migración de esquema: se suprimen correos en esta corrida.")
    else:
        try:
            envia_correo(novedades, estado, modo)
        except Exception as exc:
            # El correo es accesorio: una falla SMTP no debe impedir publicar.
            estado["ultimo_error_correo"] = {
                "fecha": ahora_cl().isoformat(),
                "tipo": type(exc).__name__,
                "mensaje": str(exc)[:500],
            }
            log(f"ADVERTENCIA correo no enviado: {type(exc).__name__}: {exc}")

    guarda_estado(estado)
    log(f"Listo: {len(registros)} proyectos en cartera · {len(novedades)} novedades · "
        f"{salida['auditoria']['segundos_corrida']}s")
    return len(novedades)


# ---------------------------------------------------------------------------
# Diagnóstico y CLI
# ---------------------------------------------------------------------------


def validar_fuentes() -> int:
    """Comprueba que ambos servicios respondan XML interpretable."""
    resultado: dict[str, Any] = {"version": VERSION_MONITOR, "pruebas": []}
    fallas = 0

    pruebas = [
        ("senado_movimiento", url_senado_fecha(ahora_cl() - timedelta(days=7)), ("proyecto",)),
        ("senado_boletin", url_senado_boletin("15975"), ("proyecto",)),
        ("camara_boletin", url_camara("retornarProyectoLey", prmNumeroBoletin="15975-25"),
         ("proyectoley", "numeroboletin")),
    ]
    for nombre, url, esperados in pruebas:
        item: dict[str, Any] = {"canal": nombre, "url": url}
        try:
            raw, final, headers = descarga(url)
            item["bytes"] = len(raw)
            item["content_type"] = headers.get("content-type", "")
            raiz = parsea_xml(raw)
            if raiz is None:
                item["estado"] = "XML ilegible"
                fallas += 1
            else:
                etiquetas = {_tag(n) for n in raiz.iter()}
                item["raiz"] = _tag(raiz)
                item["etiquetas_detectadas"] = sorted(etiquetas)[:40]
                encontrados = [e for e in esperados if e in etiquetas or e == _tag(raiz)]
                item["estado"] = "ok" if encontrados else "esquema inesperado"
                if not encontrados:
                    fallas += 1
        except Exception as exc:
            item["estado"] = f"error: {type(exc).__name__}: {exc}"
            fallas += 1
        resultado["pruebas"].append(item)

    resultado["fallas"] = fallas
    print(json.dumps(resultado, ensure_ascii=False, indent=2, default=json_default))
    return 1 if fallas else 0


def probar_boletin(boletin: str) -> None:
    """Muestra cómo el motor lee y clasifica un boletín concreto."""
    b = normaliza_boletin(boletin)
    if not b:
        print(json.dumps({"error": "boletín no interpretable", "entrada": boletin},
                         ensure_ascii=False, indent=2))
        return
    senado = consulta_senado_boletin(b)
    camara = consulta_camara_boletin(b) if CONSULTA_CAMARA else None
    if not senado and not camara:
        print(json.dumps({"boletin": b, "error": "sin datos en ninguna fuente",
                          "cobertura": _COBERTURA}, ensure_ascii=False, indent=2))
        return
    reg = construye_registro(fusiona(senado, camara))
    resumen = {
        "boletin": reg["boletin"],
        "titulo": reg["titulo"],
        "fuentes": reg.get("fuentes"),
        "nivel_impacto": reg["nivel_impacto"],
        "puntaje_pertinencia": reg["puntaje_pertinencia"],
        "prioridad": reg["prioridad"],
        "banda_prioridad": reg["banda_prioridad"],
        "urgencia": reg["urgencia_legible"],
        "etapa": reg["etapa"],
        "subetapa": reg["subetapa"],
        "vigente": reg["vigente"],
        "total_tramites": reg["total_tramites"],
        "ultimo_tramite": reg["ultimo_tramite"],
        "ultimo_movimiento": reg["ultimo_movimiento_legible"],
        "dias_sin_movimiento": reg["dias_sin_movimiento"],
        "ejes": reg["ejes_legibles"],
        "sectores": reg["sectores_legibles"],
        "evidencia": reg["evidencia"],
        "link_senado": reg["link_senado"],
    }
    print(json.dumps(resumen, ensure_ascii=False, indent=2, default=json_default))


def probar_pertinencia(texto: str, materias: str = "") -> None:
    """Evalúa el motor de pertinencia sobre un texto arbitrario."""
    proy = {"titulo": texto, "materias": [m.strip() for m in materias.split(";") if m.strip()]}
    pert = evalua_pertinencia(proy)
    proy.update({"nivel_impacto": pert["nivel"], "etapa_ordinal": 1,
                 "dias_sin_movimiento": 0, "vigente": True})
    salida = dict(pert)
    salida["ejes"] = [ETIQUETAS_EJES.get(e, e) for e in clasifica_ejes(proy)]
    salida["sectores_legibles"] = [ETIQUETAS_SECTORES.get(s, s) for s in pert["sectores"]]
    salida.update(calcula_prioridad(proy))
    print(json.dumps(salida, ensure_ascii=False, indent=2, default=json_default))


def diagnostico() -> None:
    estado = carga_estado()
    datos = carga_previos()
    lex = lexico()
    print(json.dumps({
        "version": VERSION_MONITOR,
        "modo_predeterminado": MODO_ENV,
        "zona_horaria": str(TZ_CL),
        "ahora": ahora_cl().isoformat(),
        "archivos": {
            "datos.json": SALIDA.exists(),
            "estado": ESTADO.exists(),
            "config": CONFIG.exists(),
            "lexico": LEXICO_ARCHIVO.exists(),
            "semillas": SEMILLAS_ARCHIVO.exists(),
            "exclusiones": EXCLUSIONES_ARCHIVO.exists(),
        },
        "cartera_en_estado": len(estado.get("cartera", [])),
        "huellas_en_estado": len(estado.get("huellas", {})),
        "proyectos_publicados": len(datos.get("proyectos", [])),
        "ultima_generacion": datos.get("generado_legible", ""),
        "ultima_conciliacion": estado.get("ultima_conciliacion"),
        "ultimo_error_correo": estado.get("ultimo_error_correo"),
        "lexico": {
            "directas": len(lex["directas"]),
            "nucleo": len(lex["nucleo"]),
            "estructurales": len(lex["estructurales"]),
            "sectores": len(lex["sectoriales"]),
        },
        "semillas": len(carga_semillas()),
        "parametros": {
            "umbral_pertinencia": UMBRAL_PERTINENCIA,
            "ventana_rapido": VENTANA_MOVIMIENTO_RAPIDO,
            "ventana_conciliacion": VENTANA_MOVIMIENTO_CONCILIACION,
            "hilos": HILOS,
            "consulta_camara": CONSULTA_CAMARA,
            "respeta_robots": RESPETA_ROBOTS,
        },
    }, ensure_ascii=False, indent=2, default=json_default))


def prueba_correo() -> None:
    estado = carga_estado()
    demo = [{
        "boletin": "00000-00", "titulo": "Prueba de envío del Monitor Legislativo UAF",
        "impacto_legible": ETIQUETAS_IMPACTO["directo"], "nivel_impacto": "directo",
        "banda_prioridad": "alta", "prioridad": 150.0, "novedad": "nuevo",
        "sintesis": "Mensaje de prueba, sin contenido legislativo real.",
        "ultimo_movimiento_legible": fecha_legible(ahora_cl()),
        "urgencia_clave": "simple",
        "link_senado": "https://tramitacion.senado.cl/",
    }]
    try:
        envia_correo(demo, estado, "rapido")
        guarda_estado(estado)
        print("Correo de prueba enviado (si la configuración estaba activa).")
    except Exception as exc:
        print(f"Falla al enviar: {type(exc).__name__}: {exc}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Monitor Legislativo UAF Chile")
    ap.add_argument("--modo", choices=["rapido", "conciliacion"], default=MODO_ENV)
    ap.add_argument("--validar-fuentes", action="store_true")
    ap.add_argument("--probar-boletin", metavar="BOLETIN")
    ap.add_argument("--probar-pertinencia", metavar="TEXTO")
    ap.add_argument("--materias", metavar="LISTA", default="",
                    help="materias separadas por punto y coma, para --probar-pertinencia")
    ap.add_argument("--diagnostico", action="store_true")
    ap.add_argument("--probar-correo", action="store_true")
    args = ap.parse_args()

    if args.validar_fuentes:
        raise SystemExit(validar_fuentes())
    if args.probar_boletin:
        probar_boletin(args.probar_boletin)
        return
    if args.probar_pertinencia:
        probar_pertinencia(args.probar_pertinencia, args.materias)
        return
    if args.diagnostico:
        diagnostico()
        return
    if args.probar_correo:
        prueba_correo()
        return
    carga_config()
    ejecutar(args.modo)


if __name__ == "__main__":
    main()
