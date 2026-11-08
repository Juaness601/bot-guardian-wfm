"""
Configuración centralizada para Bot Guardián (WFM Real-Time Sentinel) - LOB COACH.
Responsable Técnico: Juan Esteban Serna Gutiérrez (Área WFM).
Política Zero Credentials: El bot no solicita ni almacena credenciales de usuario;
observa directamente el DOM de la pantalla activa de WFM y ejecuta el monitoreo.
"""

import os
from dotenv import load_dotenv

# Cargar variables de entorno desde archivo .env (si existe en entorno local)
load_dotenv()


class Config:
    # --- Entorno del Servidor (Cloud Run / Local) ---
    PORT: int = int(os.getenv("PORT", "8080"))
    HOST: str = os.getenv("HOST", "0.0.0.0")
    POLL_INTERVAL_SECONDS: int = int(os.getenv("POLL_INTERVAL_SECONDS", "15"))
    TIMEZONE_OFFSET_HOURS: int = int(os.getenv("TIMEZONE_OFFSET_HOURS", "-5"))  # Ej. America/Bogota (UTC-5)

    # --- Conexión a Pantalla / Canal de Transmisión ---
    # URL opcional de la vista en tiempo real (o conexión CDP a navegador ya abierto)
    DASHBOARD_URL: str = os.getenv("WFM_DASHBOARD_URL", "")
    BROWSER_CDP_URL: str = os.getenv("BROWSER_CDP_URL", "")
    GOOGLE_CHAT_WEBHOOK_URL: str = os.getenv("GOOGLE_CHAT_WEBHOOK_URL", "")

    # --- Umbrales de Alerta WFM (en segundos) ---
    THRESHOLD_LONG_CALL: int = int(os.getenv("THRESHOLD_LONG_CALL", "900"))    # 15 minutos
    THRESHOLD_OVER_BREAK: int = int(os.getenv("THRESHOLD_OVER_BREAK", "900"))  # 15 minutos
    THRESHOLD_OVER_LUNCH: int = int(os.getenv("THRESHOLD_OVER_LUNCH", "2700")) # 45 minutos

    # --- Mapeo de Estados del Dashboard (Normalizados en minúsculas) ---
    CALL_STATES: set[str] = {
        s.strip().lower()
        for s in os.getenv("WFM_CALL_STATES", "en llamada,on call,in call,talking,acd,llamada").split(",")
        if s.strip()
    }
    BREAK_STATES: set[str] = {
        s.strip().lower()
        for s in os.getenv("WFM_BREAK_STATES", "break,descanso,pausa,baño,auxiliar").split(",")
        if s.strip()
    }
    LUNCH_STATES: set[str] = {
        s.strip().lower()
        for s in os.getenv("WFM_LUNCH_STATES", "lunch,almuerzo,comida").split(",")
        if s.strip()
    }

    # --- Selectores CSS/XPath Parametrizados de la Grilla en Pantalla ---
    SELECTOR_AGENT_ROWS: str = os.getenv("SELECTOR_AGENT_ROWS", "table#agents-grid tbody tr, .agent-row, tbody tr")
    SELECTOR_AGENT_NAME: str = os.getenv("SELECTOR_AGENT_NAME", ".agent-name, td:nth-child(1)")
    SELECTOR_AGENT_STATE: str = os.getenv("SELECTOR_AGENT_STATE", ".agent-state, td:nth-child(2)")
    SELECTOR_AGENT_TIME: str = os.getenv("SELECTOR_AGENT_TIME", ".agent-time, td:nth-child(3)")

    # --- Argumentos de Chromium para Contenedores Linux (Cloud Run / Colab) ---
    CHROMIUM_ARGS: list[str] = [
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-dev-shm-usage",
        "--disable-accelerated-2d-canvas",
        "--no-first-run",
        "--no-zygote",
        "--disable-gpu",
        "--disable-background-networking",
        "--disable-default-apps",
        "--disable-extensions",
        "--disable-sync",
        "--mute-audio",
    ]


config = Config()
