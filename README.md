# 🛡️ Bot Guardián (WFM Real-Time Sentinel) v1.0 | LOB COACH

**Asistente digital automatizado de monitoreo en tiempo real para Workforce Management (WFM).**
- **Responsable Técnico:** Juan Esteban Serna Gutiérrez (Área WFM)
- **Línea de Negocio (LOB):** COACH
- **Stack:** Python 3.11 · Playwright 1.47 (Headless Chromium) · FastAPI + Uvicorn · Google Cloud Run · Google Chat Webhooks

---

## 📋 1. Arquitectura y Flujo de Operación

1. **Lectura Directa de Pantalla (Zero Credentials):** El bot **no solicita ni almacena usuarios, contraseñas ni formularios de login**. Observa directamente el DOM de la pantalla activa de la página y continúa su ciclo de monitoreo automáticamente.
2. **Servidor HTTP Ligero (`FastAPI`):** Expone los endpoints requeridos por Google Cloud Run en el puerto dinámico `$PORT` (`8080` por defecto).
3. **Motor de Scraping Asíncrono (`Playwright`):** Ejecuta Chromium en modo `headless=True` con banderas optimizadas para contenedores Linux (`--no-sandbox`, `--disable-dev-shm-usage`) o se acopla a la ventana activa del navegador.
4. **Política Estricta Zero Data Retention:**
   - **0% persistencia en disco:** No guarda bases de datos, logs en archivos, nombres de clientes ni transcripciones.
   - **0% multimedia:** Prohibido el uso de `screenshot()`, grabación de video y descarga de imágenes/fuentes pesadas.
   - **Deduplicación 100% en memoria RAM volátil:** Envía una única alerta por agente/estado y se resetea automáticamente cuando el agente cambia de estado o reinicia su cronómetro.
5. **Notificaciones en Tiempo Real:** Envía tarjetas estructuradas (**Card v2**) al espacio de **Google Chat** de Supervisores de Operación.

---

## 📂 2. Estructura del Proyecto

```text
.
├── main.py                    # API FastAPI (GET /, POST /start, POST /stop) y ciclo de vida
├── bot_guardian.py            # Orquestador Playwright, lectura directa de pantalla y lógica WFM
├── notifier.py                # Cliente asíncrono (aiohttp) para Webhook de Google Chat (Card v2)
├── config.py                  # Configuración centralizada sin credenciales
├── Dockerfile                 # Imagen oficial Playwright Python v1.47.0-jammy lista para Cloud Run
├── requirements.txt           # Dependencias exactas de producción
├── .env.example               # Plantilla de variables de entorno (sin credenciales)
├── Bot_Guardian_Colab.ipynb   # Cuaderno interactivo listo para Google Colab
└── README.md                  # Guía de despliegue y operación
```

---

## ⚙️ 3. Configuración de Variables de Entorno

Copia la plantilla `.env.example` a `.env` para pruebas locales:

```bash
cp .env.example .env
```

| Variable | Descripción | Valor por Defecto |
| :--- | :--- | :--- |
| `PORT` | Puerto HTTP de escucha (inyectado por Cloud Run) | `8080` |
| `POLL_INTERVAL_SECONDS` | Frecuencia de lectura del DOM en segundos | `15` |
| `TIMEZONE_OFFSET_HOURS` | Diferencia horaria respecto a UTC (ej. Colombia `-5`) | `-5` |
| `GOOGLE_CHAT_WEBHOOK_URL` | **(Obligatorio)** URL del Webhook de Google Chat | — |
| `THRESHOLD_LONG_CALL` | Umbral máximo en llamada (segundos) | `900` (15 min) |
| `THRESHOLD_OVER_BREAK` | Umbral máximo en Break/Pausa (segundos) | `900` (15 min) |
| `THRESHOLD_OVER_LUNCH` | Umbral máximo en Lunch/Almuerzo (segundos) | `2700` (45 min) |
| `SELECTOR_AGENT_ROWS` | Selector CSS de cada fila de agente en la tabla | `table#agents-grid tbody tr, .agent-row, tbody tr` |
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

### Comando de Despliegue Directo a Cloud Run
Ejecuta el siguiente comando desde la raíz del proyecto (sin necesidad de configurar usuarios ni contraseñas):

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
  --set-env-vars="GOOGLE_CHAT_WEBHOOK_URL=https://chat.googleapis.com/v1/spaces/..."
```

---

## 🔌 6. Control Operativo (Endpoints HTTP)

1. **Verificar Estado (`GET /`):** Retorna `{"status": "idle"}` o `{"status": "running"}`.
2. **Iniciar Monitoreo WFM (`POST /start`):** Arranca la observación de la pantalla en segundo plano (`202 Accepted`).
3. **Detener Monitoreo (`POST /stop`):** Cancela la tarea y ejecuta el cierre limpio (`Graceful Shutdown`).
