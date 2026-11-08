# ==============================================================================
# Dockerfile - Bot Guardián (WFM Real-Time Sentinel) v1.0 | LOB COACH
# Optimizado para Google Cloud Run con soporte nativo para Playwright + Chromium
# ==============================================================================

FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

# Evitar archivos .pyc en disco y forzar salida estándar sin buffer (Zero Data Retention)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080

WORKDIR /app

# Instalar dependencias de Python
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# Copiar únicamente el código fuente de producción
COPY config.py notifier.py bot_guardian.py main.py ./

# Ejecutar con usuario sin privilegios de root (provisto por la imagen oficial de Playwright)
USER pwuser

EXPOSE 8080

# Iniciar Uvicorn respetando la variable de entorno dinámica $PORT de Google Cloud Run
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1"]
