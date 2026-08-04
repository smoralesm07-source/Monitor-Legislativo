# Monitor Legislativo UAF

Vigilancia automatizada de proyectos de ley en tramitación en el Congreso Nacional de Chile que pueden impactar las competencias de la Unidad de Análisis Financiero (**Ley N° 19.913**).

Se ejecuta solo en GitHub Actions. **No necesitas instalar Python ni ninguna herramienta en tu computador.**

---

## Puesta en marcha en 6 pasos

Todo se hace desde el navegador.

### 1. Crear el repositorio

En GitHub: **New repository** → nombre, por ejemplo `monitor-legislativo-uaf`.

Elige **Private** si prefieres que la cartera no sea pública. El monitor funciona igual; solo el tablero web (paso 6) requiere que sea público, salvo que tengas GitHub Pro o Enterprise.

No marques "Add a README file" — ya viene uno en el paquete.

### 2. Subir los archivos

En el repositorio recién creado: **Add file → Upload files**.

Arrastra **todo el contenido** de la carpeta descomprimida. Importante: arrastra los archivos y la carpeta `.github`, no la carpeta contenedora.

Si GitHub no te deja arrastrar la carpeta oculta `.github`, hazlo así:
1. Sube primero el resto de los archivos y confirma con **Commit changes**.
2. Luego **Add file → Create new file**, escribe en el nombre exactamente `.github/workflows/monitor.yml` (GitHub crea las carpetas al escribir las barras), y pega dentro el contenido de ese archivo.

### 3. Permitir que Actions escriba en el repositorio

**Settings → Actions → General → Workflow permissions** → marca **Read and write permissions** → **Save**.

Sin esto el monitor corre pero no puede guardar los resultados.

### 4. Comprobar que los servicios del Congreso responden

**Actions → Monitor legislativo UAF → Run workflow** → modo **`validar`** → **Run workflow**.

Tarda menos de un minuto. Al terminar, entra al job y mira el **Summary**: verás las pruebas del motor, el diagnóstico de cada servicio y la lectura completa de un boletín real (15975-25, el del Subsistema de Inteligencia Económica).

Qué buscar en el bloque `Servicios del Congreso`:

| Lo que ves | Qué significa | Qué hacer |
|---|---|---|
| `"estado": "ok"` en los tres canales | Todo correcto | Sigue al paso 5 |
| `"estado": "esquema inesperado"` | El servicio responde con otras etiquetas XML | Copia el campo `etiquetas_detectadas` del Summary y pásamelo para ajustar el parser |
| `error: HTTPError 404` | El endpoint cambió de ruta | Revisa `tramitacion.senado.cl/datos-abiertos-legislativos` |
| `error: PermissionError` | `robots.txt` bloquea al agente | Requiere decisión institucional antes de continuar |

Este paso reemplaza al comando local que no puedes ejecutar. **Hazlo antes que nada:** si el esquema de alguna fuente cambió, es mejor saberlo ahora que después de programar el monitor.

### 5. Primera corrida real

**Actions → Run workflow** → modo **`conciliacion`** → **Run workflow**.

Tarda entre 5 y 15 minutos: hace el barrido profundo, construye la cartera desde cero y publica `datos.json`. En el Summary quedan los indicadores y los diez proyectos de mayor prioridad.

A partir de aquí el monitor corre solo: **cada 2 horas en días hábiles** (barrido incremental) y **los domingos** (conciliación profunda).

> En esta primera corrida los correos se suprimen a propósito. Toda la cartera sería "nueva" y llenaría la bandeja. Desde la segunda corrida solo avisa de movimientos reales.

### 6. Publicar el tablero

**Settings → Pages → Source: Deploy from a branch → Branch: `main` / `(root)`** → **Save**.

En un par de minutos el tablero queda en `https://TU-USUARIO.github.io/monitor-legislativo-uaf/`.

Mientras no hayas hecho el paso 5, el tablero muestra datos de demostración con un aviso visible: los boletines y títulos son reales, pero los estados procesales son ilustrativos.

---

## Avisos por correo (opcional)

El monitor funciona sin esto; simplemente no notifica.

**Settings → Secrets and variables → Actions → New repository secret**, uno por cada uno:

| Secret | Valor |
|---|---|
| `MONITOR_SMTP_SERVIDOR` | `smtp.gmail.com` |
| `MONITOR_SMTP_PUERTO` | `587` |
| `MONITOR_SMTP_USUARIO` | tu dirección de correo |
| `MONITOR_SMTP_CLAVE` | clave de aplicación (no la contraseña de la cuenta) |
| `MONITOR_DESTINATARIOS` | `correo1@uaf.cl,correo2@uaf.cl` |

Con Gmail necesitas verificación en dos pasos activada y generar una clave de aplicación en la configuración de tu cuenta Google.

Para probar: **Run workflow** → modo **`probar_correo`**.

---

## Uso diario

No hay que hacer nada: el monitor corre solo y publica en el tablero.

**Cuando llegue un correo de aviso**, indica el tipo de novedad:

- `NUEVO EN CARTERA` — un proyecto entró al perímetro de vigilancia
- `MOVIMIENTO` — avanzó procesalmente
- `CAMBIO DE URGENCIA` — el Ejecutivo modificó la calificación, y eso cambia el tiempo real disponible para incidir técnicamente

**El tablero se organiza en tres niveles**, del más al menos crítico para el área:

| Nivel | Qué agrupa |
|---|---|
| **1 · Impacto en la Ley 19.913** | Nombran la ley, la UAF, el reporte de operaciones sospechosas o el régimen de sujetos obligados |
| **2 · Perímetro regulatorio** | Tocan delitos base, sujetos obligados o el sistema ALA/CFT sin modificar la ley directamente |
| **3 · Seguimiento** | Sin señales suficientes en el material disponible; incluye los ómnibus pendientes de criterio de analista |

**En el tablero:**

- El **panel de novedades** abre la vista: cuatro indicadores de pulso y, debajo, dos columnas. La principal muestra los movimientos recientes de **nivel 1** en tarjetas grandes; la lateral, el nivel 2 en lista compacta. Todo ordenado de más reciente a más antiguo, con distintivo cuando hay novedad respecto de la corrida anterior.
- Si ningún proyecto de nivel 1 aparece en la vista, el panel lo dice explícitamente. Esa ausencia es información, no un hueco.
- Las **tarjetas de composición por nivel** muestran cuántos proyectos hay en cada uno, cuántos con urgencia y cuántos se movieron en 30 días. Clic para filtrar.
- **Clic en cualquier boletín** —en el encabezado, en el itinerario o en el listado— abre una **ficha emergente** con todo lo levantado: estado procesal, urgencia, ejes, sectores, materias, autoría, ministerios, tramitación completa, votaciones, historial de urgencias, enlaces a las fuentes y **la evidencia textual que motivó la clasificación**. Se cierra al hacer clic fuera, con la tecla `Esc` o con el botón de cierre.
- Los **filtros que se aplican con un clic** (ejes, sectores, urgencias, cámara, trámite en el itinerario, botones del encabezado) **se anulan al volver a hacer clic** sobre el mismo elemento.
- El itinerario legislativo muestra dónde está cada proyecto; el color del borde indica la urgencia. Clic en el nombre de un trámite filtra por esa etapa.

---

## Ajustes sin tocar código

Los tres archivos JSON se editan directamente en GitHub (**clic en el archivo → ícono del lápiz → Commit changes**). El cambio toma efecto en la siguiente corrida.

**`boletines_semilla.json`** — cartera de seguimiento permanente. Se consultan siempre, aunque no registren movimiento y aunque el motor no los puntúe. Vienen cargados 11 boletines.

**`lexico_uaf.json`** — terminología adicional para la detección. Es **aditivo**: lo que escribas se suma al léxico incorporado. Frases en minúsculas y sin tildes.

**`exclusiones_boletines.json`** — falsos positivos confirmados por un analista, con el motivo registrado.

---

## Qué vigila y cómo decide

Los "motores de búsqueda" no son buscadores probabilísticos: son los **servicios oficiales de datos abiertos** del Senado (`tramitacion.senado.cl`) y de la Cámara (`opendata.camara.cl`). El descubrimiento es exhaustivo, no estimado.

Ninguna fuente basta sola: el Senado tiene el itinerario procesal y las urgencias, la Cámara tiene las materias clasificadas y el patrocinio ministerial. El motor las fusiona por boletín.

La pregunta que responde no es "¿menciona a la UAF?" sino **"¿puede alterar el marco en que la UAF opera?"**. Los proyectos que más importan a menudo nunca escriben la sigla: agregan delitos base al artículo 27, tocan el secreto bancario, o regulan a un sector que ya es sujeto obligado. Por eso clasifica en cuatro capas —directo, estructural, sectorial, descartado— y calcula una prioridad que combina impacto, urgencia, proximidad al despacho y frescura.

**La clasificación es una estimación automática y requiere validación de analista antes de cualquier uso institucional.**

El motor lee título, materias, comisiones y tramitación, **no el articulado**. En los proyectos ómnibus eso no alcanza: una norma que afecta a la UAF puede viajar en el artículo 31 sin dejar rastro en ninguno de esos campos. Esos proyectos no se descartan: quedan marcados como **"Revisión de analista"**, visibles con el filtro *Solo pendientes de revisión*. Cuando confirmes que uno sí es relevante, agrégalo a `boletines_semilla.json`.

El detalle técnico completo está en [`INSTRUCCIONES.md`](INSTRUCCIONES.md).

---

## Si algo falla

**El workflow aparece en rojo.** Entra al job y mira qué paso falló. Si fueron las *Pruebas del motor*, el parser se rompió por un cambio de esquema de alguna fuente: el workflow falla a propósito en lugar de sobrescribir `datos.json` con datos corruptos.

**El tablero dice "No se pudo leer datos.json".** Falta la primera corrida (paso 5) o Pages aún no terminó de desplegar.

**El monitor corre pero no guarda nada.** Falta el paso 3, los permisos de escritura.

**No llegan correos.** Revisa que los cinco secrets estén creados y prueba con el modo `probar_correo`. Recuerda que la primera corrida suprime los avisos.

**Quiero reconstruir la cartera desde cero.** **Run workflow** → modo `conciliacion` → marca **reiniciar_estado**.

---

*Fuentes: servicios de datos abiertos del Senado y de la Cámara de Diputadas y Diputados de Chile.*
