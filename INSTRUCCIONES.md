# Monitor Legislativo UAF · v1.0.0

Vigilancia de proyectos de ley en tramitación en el Congreso Nacional que pueden impactar las competencias de la Unidad de Análisis Financiero (Ley N° 19.913).

Replica la arquitectura del Monitor UAF de prensa v8.2.2 —capa de red segura, respeto de `robots.txt`, espaciado por host, presupuesto de tiempo, estado persistente, aviso por SMTP, `datos.json` + tablero HTML, modos rápido y conciliación— reorientada a tramitación legislativa.

---

## 1. Lo primero que debes hacer

**El motor no fue ejecutado contra los servicios reales.** Fue construido y validado íntegramente contra fixtures XML, porque el entorno donde se desarrolló no tiene salida de red hacia `senado.cl` ni `camara.cl`. Antes de programarlo, corre esto:

```bash
python monitor_legislativo.py --validar-fuentes
```

Imprime, para cada servicio, el código de respuesta, el nodo raíz y **las etiquetas XML que realmente devuelve**. Con eso confirmas que el esquema asumido coincide con el vigente.

Qué esperar:

| Resultado | Significado | Acción |
|---|---|---|
| `"estado": "ok"` en los tres canales | Todo correcto | Continúa al paso 2 |
| `"estado": "esquema inesperado"` | El servicio responde, pero con otras etiquetas | Copia el campo `etiquetas_detectadas` y amplía los alias en `parsea_proyecto_senado` |
| `"error: HTTPError 404"` en el Senado | El endpoint cambió de ruta | Verifica en `https://tramitacion.senado.cl/datos-abiertos-legislativos` |
| `"error: PermissionError"` | `robots.txt` bloquea al agente | Evalúa institucionalmente antes de usar `MONITOR_RESPETA_ROBOTS=false` |

Luego prueba un boletín concreto:

```bash
python monitor_legislativo.py --probar-boletin 15975-25
```

Devuelve título, etapa, urgencia, trámites, nivel de impacto, prioridad y **la evidencia textual** que motivó la clasificación. Si esto sale bien, el motor funciona de punta a punta.

---

## 2. Instalación

Solo requiere Python 3.11+ y biblioteca estándar. Sin dependencias externas.

```
monitor_legislativo.py          Motor
index.html                      Tablero
boletines_semilla.json          Cartera de seguimiento permanente
lexico_uaf.json                 Ampliaciones del léxico de pertinencia
exclusiones_boletines.json      Falsos positivos confirmados
test_monitor_legislativo.py     118 pruebas offline
generar_demo.py                 Genera un datos.json de muestra
prueba_dashboard.mjs            24 pruebas del tablero (requiere: npm install jsdom)
.github/workflows/monitor.yml   Automatización
```

Ejecución local:

```bash
python test_monitor_legislativo.py      # debe dar 118/118
python monitor_legislativo.py --modo rapido
python -m http.server 8000              # abre http://localhost:8000
```

Para revisar el tablero **antes** de la primera corrida real hay un `datos.json` de demostración incluido. Sus boletines y títulos son reales; **los estados procesales son ilustrativos y no deben citarse como información oficial**. Se sobrescribe en la primera corrida. Puedes regenerarlo con `python generar_demo.py`.

---

## 3. Cómo descubre los proyectos

Los "motores de búsqueda" no son buscadores probabilísticos como en el monitor de prensa: son los servicios oficiales de datos abiertos, lo que hace el descubrimiento **exhaustivo** en lugar de estimado.

| Canal | Endpoint | Cuándo | Función |
|---|---|---|---|
| Senado · movimiento | `tramitacion.php?fecha=DD/MM/AAAA` | Siempre | Todos los boletines con movimiento desde una fecha. Es el descubrimiento incremental |
| Senado · ficha | `tramitacion.php?boletin=NNNNN` | Por boletín | Trámites, urgencias, votaciones, comisiones |
| Cámara · ficha | `WSLegislativo.asmx/retornarProyectoLey` | Por boletín | Materias clasificadas, autores, ministerios patrocinantes |
| Cámara · universo anual | `retornarMocionesXAnno` y `retornarMensajesXAnno` | Solo conciliación | Barrido completo del año legislativo |
| Semillas | `boletines_semilla.json` | Siempre | Cartera crítica, se consulta aunque no registre movimiento |
| Cartera | Estado interno | Siempre | Todo lo ya clasificado como pertinente se reconsulta |

Dos detalles del Senado que cuestan horas si no se saben: el parámetro `boletin` exige **el correlativo sin la materia** (`15975`, no `15975-25`), y la consulta por fecha **no acepta más de un mes hacia atrás**. Ambos están manejados en el código.

Ninguna fuente basta sola: el Senado tiene el itinerario procesal, la Cámara tiene las materias y el patrocinio ministerial. El motor las fusiona por boletín normalizado, privilegiando al Senado en tramitación.

Antes de gastar una llamada de red por boletín, el motor **preselecciona por título**, porque un año legislativo trae más de mil proyectos y solo una fracción toca el perímetro de la UAF.

El descarte tiene un riesgo asimétrico: un falso positivo cuesta una llamada de red, un falso negativo cuesta que un proyecto relevante **nunca aparezca**. Por eso solo se descarta el caso claro —título informativo que puntúa bajo el umbral— y todo lo ambiguo pasa a consulta, en este orden:

| Nivel | Qué es | Se consulta |
|---|---|---|
| 0 | Semillas y cartera | Siempre |
| 1 | Pertinente por título | Siempre |
| 2 | Sin título conocido | Siempre |
| 3 | Título genérico en materia sensible (05, 07, 25, 03, 06, 02) | Hasta el tope |
| 4 | Título genérico | Hasta el tope |
| — | Título informativo bajo umbral | **Descartado** |

Hay dos razones distintas para no descartar por título, y conviene no confundirlas:

- **Título ómnibus** — agrupa materias que no anuncia (*"Para la reconstrucción nacional..."*, *"Modifica diversos cuerpos legales"*, una ley de presupuestos). Se consulta **y además se retiene** marcado para revisión de analista, porque ni el título ni las materias permiten concluir nada sobre 38 artículos heterogéneos.
- **Título escueto** — tres o menos palabras sustantivas. Solo justifica **gastar la consulta** para ver materias y comisiones reales. Si con ese material completo sigue sin señales, se descarta como cualquier otro. Un título breve pero descriptivo —*"Ley de protección tarifaria eléctrica"*— no debe quedar en la cartera indefinidamente. Solo se retiene si además el código de materia es sensible.

Los **títulos ómnibus** son el punto crítico. Un proyecto ómnibus del Ejecutivo agrupa decenas de materias heterogéneas bajo un encabezado que no describe nada: *"Para la reconstrucción nacional y el desarrollo económico y social"* (boletín 18216-05) reúne 38 artículos permanentes de materia tributaria, ambiental, laboral y municipal. Descartarlo por título sería perder justamente los casos donde una norma que afecta a la UAF viaja escondida entre otras cien. El tope de estos pases está en `MONITOR_MAX_GENERICOS` (140).

---

## 4. Cómo decide qué es pertinente

Este es el punto donde la herramienta se separa del monitor de prensa. Allá la pregunta era "¿menciona a la UAF?". Aquí es **"¿puede este proyecto alterar el marco en que la UAF opera?"** — y los proyectos que más importan a menudo nunca escriben la sigla: agregan delitos base al artículo 27, tocan el secreto bancario, o regulan a un sector que ya es sujeto obligado.

Cuatro capas:

| Nivel | Criterio | Ejemplo |
|---|---|---|
| **Directo** | Nombra la Ley 19.913, la UAF, los ROS o los sujetos obligados | *Crea el Subsistema de Inteligencia Económica* |
| **Estructural** | Opera sobre el sistema ALA/CFT sin nombrar la ley | *Agrava las sanciones en materia de lavado de activos* |
| **Sectorial** | Regula a un sujeto obligado del art. 3 sin tocar el régimen ALA/CFT | *Regula el corretaje de propiedades* |
| **Descartado** | Bajo el umbral | *Declara el Día Nacional de...* |

El puntaje pondera **dónde** aparece la señal: el título de un proyecto es una declaración de propósito y pesa el triple que el texto de la tramitación. La sigla "UAF" aislada solo cuenta si el entorno es financiero o penal, para no capturar homónimos.

Cada registro guarda la **evidencia textual** que motivó su clasificación, visible al expandir la ficha en el tablero. Esto permite que un analista audite por qué el motor incluyó o excluyó un boletín, en lugar de confiar en un número.

En el tablero esas cuatro capas se presentan agrupadas en **tres niveles**: nivel 1 corresponde a `directo`; nivel 2 reúne `estructural` y `sectorial`, más cualquier proyecto cuyos ejes toquen facultades de la UAF, delitos base o sujetos obligados; nivel 3 recoge el resto. La agrupación se calcula en el tablero, de modo que un cambio de criterio no obliga a reconstruir la cartera.

Sobre esa capa va la **prioridad**:

```
prioridad = base(nivel) × urgencia × proximidad al despacho × frescura
```

La urgencia es lo que define cuánto tiempo real queda para incidir técnicamente: discusión inmediata multiplica por 3, suma por 2,2, simple por 1,6. La proximidad premia los trámites avanzados y castiga los cerrados. Bandas: crítica ≥200, alta ≥120, media ≥55.

**Esta clasificación es una estimación automática y requiere validación de analista antes de cualquier uso institucional.**

---

## 5. Detección de movimiento

El estado guarda una **firma** por boletín construida solo con lo que un analista consideraría un cambio de estado real: etapa, subetapa, urgencia, número de ley, cantidad de trámites, fecha y descripción del último trámite, cantidad de votaciones. Comparar la ficha completa produciría falsos movimientos por reordenamientos de campos volátiles.

Tres tipos de novedad, todas notificables por correo: `nuevo` (entra a la cartera), `movimiento` (avanzó procesalmente), `urgencia` (cambió la calificación).

---

## 6. Ajuste sin tocar el código

Tres archivos son editables en caliente:

**`boletines_semilla.json`** — cartera de seguimiento permanente. Vienen cargados los cinco boletines de tu lista más seis detectados como vigentes al revisar el listado del Senado, entre ellos **18407-25** (agrava sanciones por lavado de activos, ingresado 24/06/2026) y **18080-03** (trazabilidad en operaciones prendarias), que no estaban en tu enumeración inicial.

**`lexico_uaf.json`** — es **aditivo**: lo que escribas se suma al léxico incorporado, no lo reemplaza. Frases en minúsculas y sin tildes; el motor normaliza antes de comparar y exige coincidencia de palabra completa (por eso "bancos de plaza" no dispara el sector bancario).

**`exclusiones_boletines.json`** — falsos positivos confirmados por un analista. Quedan fuera de forma auditable, con motivo registrado.

Si el umbral resulta muy laxo o muy estricto tras la primera conciliación, ajústalo con `MONITOR_UMBRAL_PERTINENCIA` (valor por omisión: 30) antes de tocar el léxico.

---

## 7. Automatización en GitHub Actions

El workflow corre cada 2 horas en días hábiles (modo rápido) y hace conciliación profunda los domingos. Antes de cada corrida ejecuta las 118 pruebas offline: si el parser se rompe por un cambio de esquema, el workflow falla en lugar de publicar datos corruptos.

Secrets para el correo (opcionales; sin ellos el monitor funciona igual, solo no avisa):

```
MONITOR_SMTP_SERVIDOR    smtp.gmail.com
MONITOR_SMTP_PUERTO      587
MONITOR_SMTP_USUARIO     tu.correo@dominio.cl
MONITOR_SMTP_CLAVE       clave de aplicación
MONITOR_DESTINATARIOS    correo1@uaf.cl,correo2@uaf.cl
```

Primera corrida: **Actions → Actualizar y publicar monitor legislativo → Run workflow**, modo `conciliacion`. Construye la cartera desde cero. Los correos se suprimen en esa corrida por la migración de esquema, para no inundar la bandeja con toda la cartera histórica.

---

## 8. Comandos de diagnóstico

```bash
python monitor_legislativo.py --validar-fuentes
python monitor_legislativo.py --probar-boletin 18407-25
python monitor_legislativo.py --probar-pertinencia "texto del título del proyecto"
python monitor_legislativo.py --diagnostico
python monitor_legislativo.py --probar-correo
```

`--probar-pertinencia` es el más útil para calibrar: pasa el título de un proyecto que crees que el motor debería o no capturar, y verás el puntaje, la evidencia, los ejes y la prioridad resultante.

---

## 9. Variables de entorno

| Variable | Por omisión | Qué controla |
|---|---|---|
| `MONITOR_MODO` | `rapido` | Modo de ejecución |
| `MONITOR_UMBRAL_PERTINENCIA` | `30` | Corte para entrar a la cartera |
| `MONITOR_VENTANA_RAPIDO` | `7` | Días de movimiento en modo rápido |
| `MONITOR_VENTANA_CONCILIACION` | `30` | Días en conciliación (tope del servicio) |
| `MONITOR_ANNOS_CONCILIACION` | `3` | Años del barrido anual de la Cámara |
| `MONITOR_CONSULTA_CAMARA` | `true` | Consultar o no la Cámara (duplica llamadas, aporta materias) |
| `MONITOR_HILOS` | `4` | Concurrencia |
| `MONITOR_INTERVALO_HOST` | `1.1` | Segundos entre llamadas al mismo host |
| `MONITOR_PRESUPUESTO_SEG` | `900` | Tiempo máximo de corrida |
| `MONITOR_RESPETA_ROBOTS` | `true` | Cumplimiento de `robots.txt` |

---

## 10. Validación realizada

**118/118 pruebas offline** (`test_monitor_legislativo.py`): normalización de boletines, parser tolerante al esquema contra dos nomenclaturas XML distintas, fechas en cuatro formatos, motor de pertinencia con casos positivos y falsos amigos, ejes, estado procesal, prioridad, fusión de fuentes, detección de movimiento, preselección, métricas, construcción de URLs y barreras de red.

**24/24 comprobaciones del tablero** (`prueba_dashboard.mjs`, requiere `npm install jsdom`): render inicial, filtros, búsqueda, ordenamientos, acciones rápidas, expansión de fichas, itinerario clicable y escape de contenido.

Durante la construcción se detectaron y corrigieron dos defectos reales: el bloque `<descripcion>` de cabecera se confundía con el campo `Descripcion` de un trámite —el motor leía el encabezado desde un trámite cualquiera—, y las barras de la fecha no se codificaban en la URL del Senado.

El parser se escribió **tolerante al esquema** a propósito: accede a los campos por nombre normalizado y listas de alias, no por ruta literal. Los servicios del Congreso no publican un contrato estable y alternan nomenclatura entre bloques; amarrar el motor a nombres literales lo haría frágil ante cualquier ajuste del proveedor.

---

## 11. Limitaciones conocidas

- La ventana de movimiento del Senado **no excede un mes**. Un proyecto que pase más de 30 días sin moverse solo se reconsulta por estar en la cartera o en las semillas; si nunca entró, requiere una conciliación para ser descubierto.
- El servicio del Senado no expone un campo de comisión actual estable, por lo que la comisión se infiere de la descripción del último trámite y puede quedar vacía.
- Los proyectos **refundidos** conservan boletines separados en la fuente. El motor guarda el campo `refundidos` cuando el servicio lo entrega, pero no unifica automáticamente las fichas.
- La clasificación **no lee el texto del articulado**, solo título, materias, comisiones y tramitación. Esta es la limitación de fondo y no tiene solución automática: los servicios del Congreso no exponen el articulado en formato estructurado.

  Para acotarla, los proyectos con título genérico que no alcanzan a clasificarse quedan retenidos con la marca **"Revisión de analista"** en lugar de descartarse. Aparecen en el tablero con el filtro *Solo pendientes de revisión* y en el indicador del encabezado. El motor está diciendo ahí, explícitamente, que no tiene material para pronunciarse — no que el proyecto sea irrelevante.

  Cuando confirmes que uno de esos proyectos sí toca a la UAF, agrégalo a `boletines_semilla.json` con una nota. Así queda en seguimiento permanente y con el criterio registrado.

---

*Fuentes: servicios de datos abiertos del Senado (`tramitacion.senado.cl`) y de la Cámara de Diputadas y Diputados (`opendata.camara.cl`).*
