# 🛡️ Bot Guardián (WFM Real-Time Sentinel) v1.0 | LOB COACH

**Asistente digital automatizado de monitoreo en tiempo real para Workforce Management (WFM).**
- **Responsable Técnico:** Juan Esteban Serna Gutiérrez (Área WFM)
- **Línea de Negocio (LOB):** COACH
- **Stack:** Python 3.11 · Playwright 1.47 (Headless Chromium) · FastAPI + Uvicorn · Google Cloud Run · Google Chat Webhooks

---

## 📋 1. Arquitectura y Flujo de Operación

1. **Servidor HTTP Ligero (`FastAPI`):** Expone los endpoints requeridos por Google Cloud Run en el puerto dinámico `$PORT` (`8080` por defecto).
2. **Motor de Scraping Asíncrono (`Playwright`):** Ejecuta Chromium en modo `headless=True` con banderas optimizadas para contenedores Linux (`--no-sandbox`, `--disable-dev-shm-usage`).
3. **Política Estricta Zero Data Retention:**
   - **0% persistencia en disco:** No guarda bases de datos, logs en archivos, nombres de clientes ni transcripciones.
   - **0% multimedia:** Prohibido el uso de `screenshot()`, grabación de video y descarga de imágenes/fuentes pesadas.
   - **Deduplicación 100% en memoria RAM volátil:** Envía una única alerta por agente/estado y se resetea automáticamente cuando el agente cambia de estado o reinicia su cronómetro.
4. **Notificaciones en Tiempo Real:** Envía tarjetas estructuradas (**Card v2**) al espacio de **Google Chat** de Supervisores de Operación.

---

## 📂 2. Estructura del Proyecto

```text
.
├── main.py              # API FastAPI (GET /, POST /start, POST /stop) y ciclo de vida
├── bot_guardian.py      # Orquestador Playwright, extracción DOM y lógica de umbrales WFM
├── notifier.py          # Cliente asíncrono (aiohttp) para Webhook de Google Chat (Card v2)
├── config.py            # Configuración centralizada y lectura de variables de entorno
├── Dockerfile           # Imagen oficial Playwright Python v1.47.0-jammy lista para Cloud Run
├── requirements.txt     # Dependencias exactas de producción
├── .env.example         # Plantilla de variables de entorno
└── README.md            # Guía de despliegue y operación
```

---

## ⚙️ 3. Configuración de Variables de Entorno

Copia la plantilla `.env.example` a `.env` (solo para entorno local; en GCP se inyectan como variables de entorno o desde **Secret Manager**):

```bash
cp .env.example .env
```

| Variable | Descripción | Valor por Defecto |
| :--- | :--- | :--- |
| `PORT` | Puerto HTTP de escucha (inyectado por Cloud Run) | `8080` |
| `POLL_INTERVAL_SECONDS` | Frecuencia de lectura del DOM en segundos | `15` |
| `TIMEZONE_OFFSET_HOURS` | Diferencia horaria respecto a UTC (ej. Colombia `-5`) | `-5` |
| `WFM_DASHBOARD_URL` | **(Obligatorio)** URL del dashboard en tiempo real | — |
| `WFM_LOGIN_URL` | URL de inicio de sesión (si difiere del dashboard) | `""` |
| `WFM_USERNAME` | Usuario de servicio para autenticación WFM | `""` |
| `WFM_PASSWORD` | Contraseña del usuario de servicio WFM | `""` |
| `GOOGLE_CHAT_WEBHOOK_URL` | **(Obligatorio)** URL del Webhook de Google Chat | — |
| `THRESHOLD_LONG_CALL` | Umbral máximo en llamada (segundos) | `900` (15 min) |
| `THRESHOLD_OVER_BREAK` | Umbral máximo en Break/Pausa (segundos) | `900` (15 min) |
| `THRESHOLD_OVER_LUNCH` | Umbral máximo en Lunch/Almuerzo (segundos) | `2700` (45 min) |
| `SELECTOR_AGENT_ROWS` | Selector CSS de cada fila de agente en la tabla | `table#agents-grid tbody tr, .agent-row` |
| `SELECTOR_AGENT_NAME` | Selector CSS del nombre/ID del agente dentro de la fila | `.agent-name, td:nth-child(1)` |
| `SELECTOR_AGENT_STATE` | Selector CSS del estado actual dentro de la fila | `.agent-state, td:nth-child(2)` |
| `SELECTOR_AGENT_TIME` | Selector CSS del tiempo acumulado (`MM:SS` o `HH:MM:SS`) | `.agent-time, td:nth-child(3)` |

---

## 💻 4. Ejecución en Estación Local (Bajo Demanda)

### Opción A: Con Python Virtualenv
```bash
# 1. Crear y activar entorno virtual (Python 3.11+)
python -m venv .venv
# En Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# En Linux/macOS:
source .venv/bin/activate

# 2. Instalar dependencias y binario de Chromium
pip install -r requirements.txt
playwright install chromium

# 3. Iniciar servidor FastAPI
python main.py
```

### Opción B: Con Docker Local
```bash
# 1. Construir la imagen
docker build -t bot-guardian-coach:1.0 .

# 2. Ejecutar el contenedor pasando el archivo .env
docker run --rm -p 8080:8080 --env-file .env bot-guardian-coach:1.0
```

---

## ☁️ 5. Despliegue en Google Cloud Run (Producción)

### 5.1 Requisitos Previos en GCP
1. Tener instalado y autenticado [Google Cloud SDK (`gcloud`)](https://cloud.google.com/sdk/docs/install):
   ```bash
   gcloud auth login
   gcloud config set project TU_PROJECT_ID
   ```
2. Habilitar las APIs necesarias:
   ```bash
   gcloud services enable run.googleapis.com \
                          cloudbuild.googleapis.com \
                          artifactregistry.googleapis.com \
                          secretmanager.googleapis.com
   ```

### 5.2 (Recomendado) Guardar Credenciales Sensibles en Secret Manager
Para máxima seguridad, almacena la contraseña y el Webhook en **Google Secret Manager**:
```bash
echo -n "TU_PASSWORD_WFM" | gcloud secrets create wfm-password --data-file=-
echo -n "https://chat.googleapis.com/v1/spaces/..." | gcloud secrets create gchat-webhook-url --data-file=-
```

### 5.3 Comando de Despliegue Directo a Cloud Run
Ejecuta el siguiente comando desde la raíz del proyecto:

```bash
gcloud run deploy bot-guardian-coach \
  --source . \
  --region us-central1 \
  --platform managed \
  --memory 1Gi \
  --cpu 1 \
  --min-instances 0 \
  --max-instances 1 \
  --no-cpu-throttling \
  --timeout 3600 \
  --no-allow-unauthenticated \
  --set-env-vars="WFM_DASHBOARD_URL=https://wfm.ejemplo.com/realtime,WFM_LOGIN_URL=https://wfm.ejemplo.com/login,WFM_USERNAME=usuario_wfm" \
  --set-secrets="WFM_PASSWORD=wfm-password:latest,GOOGLE_CHAT_WEBHOOK_URL=gchat-webhook-url:latest"
```

> **📌 Notas Críticas de Arquitectura para Cloud Run:**
> - `--no-cpu-throttling` (**Asignación de CPU siempre activa**): Indispensable porque el ciclo de Playwright corre en una tarea en segundo plano (`asyncio.create_task`) después de que `POST /start` responde `202 Accepted`. Sin esta bandera, Cloud Run congelaría la CPU al terminar la petición HTTP.
> - `--max-instances 1`: Evita que escalen múltiples contenedores en paralelo leyendo la misma tabla y enviando alertas duplicadas.
> - `--memory 1Gi`: Chromium Headless requiere al menos `1 GiB` de RAM para operar con estabilidad en memoria compartida reducida.

---

## 🔌 6. Control Operativo (Endpoints HTTP)

Una vez desplegado, obtén la URL del servicio:
```bash
SERVICE_URL=$(gcloud run services describe bot-guardian-coach --region us-central1 --format='value(status.url)')
```

### 1️⃣ Verificar Estado (`GET /`)
```bash
curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" "$SERVICE_URL/"
```
**Respuesta:**
```json
{"status": "idle"}
```

### 2️⃣ Iniciar Monitoreo WFM (`POST /start`)
```bash
curl -X POST \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  "$SERVICE_URL/start"
```
**Respuesta (`202 Accepted`):**
```json
{
  "status": "running",
  "message": "Monitoreo WFM iniciado en segundo plano para LOB COACH."
}
```

### 3️⃣ Detener Monitoreo y Cerrar Navegador (`POST /stop`)
```bash
curl -X POST \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  "$SERVICE_URL/stop"
```
**Respuesta (`200 OK`):**
```json
{
  "status": "idle",
  "message": "Monitoreo detenido y sesión de Playwright cerrada limpiamente."
}
```

---

## ⏰ 7. Automatización de Horarios con Cloud Scheduler (Opcional)

Puedes programar el encendido y apagado automático al inicio y fin del turno operativo de la LOB COACH:

```bash
# Encender de Lunes a Sábado a las 07:00 AM (Hora Bogotá/Lima)
gcloud scheduler jobs create http bot-guardian-start \
  --schedule="0 7 * * 1-6" \
  --time-zone="America/Bogota" \
  --uri="$SERVICE_URL/start" \
  --http-method=POST \
  --oidc-service-account-email="TU_SERVICE_ACCOUNT@TU_PROJECT_ID.iam.gserviceaccount.com"

# Apagar de Lunes a Sábado a las 10:00 PM
gcloud scheduler jobs create http bot-guardian-stop \
  --schedule="0 22 * * 1-6" \
  --time-zone="America/Bogota" \
  --uri="$SERVICE_URL/stop" \
  --http-method=POST \
  --oidc-service-account-email="TU_SERVICE_ACCOUNT@TU_PROJECT_ID.iam.gserviceaccount.com"
```
