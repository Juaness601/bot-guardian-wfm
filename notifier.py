"""
Módulo de Notificaciones hacia Google Workspace (Google Chat Webhook).
Cumple con la política de Zero Data Retention (sin almacenamiento en disco ni logs sensibles).
"""

import logging
from datetime import datetime, timezone, timedelta
import aiohttp
from config import config

logger = logging.getLogger("bot_guardian.notifier")


def format_seconds_to_hms(total_seconds: int) -> str:
    """Convierte segundos acumulados a formato legible HH:MM:SS o MM:SS."""
    hours, remainder = divmod(max(0, int(total_seconds)), 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def build_google_chat_card(
    agent_name: str,
    event_type: str,
    current_state: str,
    elapsed_seconds: int,
    threshold_seconds: int,
) -> dict:
    """
    Construye el payload estructurado en formato Card v2 de Google Chat.
    """
    tz = timezone(timedelta(hours=config.TIMEZONE_OFFSET_HOURS))
    detection_time = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
    formatted_duration = format_seconds_to_hms(elapsed_seconds)
    formatted_threshold = format_seconds_to_hms(threshold_seconds)

    return {
        "cardsV2": [
            {
                "cardId": f"wfm-alert-{int(datetime.now().timestamp())}",
                "card": {
                    "header": {
                        "title": "⚠️ Alerta WFM - Bot Guardián | LOB COACH",
                        "subtitle": f"Evento: {event_type}",
                    },
                    "sections": [
                        {
                            "header": "Detalles del Incumplimiento en Tiempo Real",
                            "widgets": [
                                {
                                    "decoratedText": {
                                        "topLabel": "Nombre del Agente",
                                        "text": f"<b>{agent_name}</b>",
                                        "startIcon": {"knownIcon": "PERSON"},
                                    }
                                },
                                {
                                    "decoratedText": {
                                        "topLabel": "Evento Detectado",
                                        "text": f"<font color='#d93025'><b>{event_type}</b></font> (Estado: {current_state})",
                                        "startIcon": {"knownIcon": "DESCRIPTION"},
                                    }
                                },
                                {
                                    "decoratedText": {
                                        "topLabel": "Tiempo Transcurrido / Umbral",
                                        "text": f"<b>{formatted_duration}</b> (Umbral máx: {formatted_threshold})",
                                        "startIcon": {"knownIcon": "CLOCK"},
                                    }
                                },
                                {
                                    "decoratedText": {
                                        "topLabel": "Hora de Detección",
                                        "text": detection_time,
                                        "startIcon": {"knownIcon": "EVENT_SEAT"},
                                    }
                                },
                            ],
                        }
                    ],
                },
            }
        ]
    }


async def send_google_chat_alert(
    agent_name: str,
    event_type: str,
    current_state: str,
    elapsed_seconds: int,
    threshold_seconds: int,
    session: aiohttp.ClientSession | None = None,
) -> bool:
    """
    Envía de forma asíncrona una alerta estructurada al Webhook oficial de Google Chat.
    Retorna True si el envío fue exitoso (HTTP 2xx), False en caso contrario.
    """
    webhook_url = config.GOOGLE_CHAT_WEBHOOK_URL
    if not webhook_url:
        logger.error("GOOGLE_CHAT_WEBHOOK_URL no está configurada. No se pudo enviar la alerta.")
        return False

    payload = build_google_chat_card(
        agent_name=agent_name,
        event_type=event_type,
        current_state=current_state,
        elapsed_seconds=elapsed_seconds,
        threshold_seconds=threshold_seconds,
    )

    timeout = aiohttp.ClientTimeout(total=10)
    own_session = session is None

    try:
        if own_session:
            session = aiohttp.ClientSession(timeout=timeout)

        async with session.post(
            webhook_url,
            json=payload,
            headers={"Content-Type": "application/json; charset=UTF-8"},
        ) as response:
            if 200 <= response.status < 300:
                logger.info("Alerta WFM (%s) enviada exitosamente a Google Chat.", event_type)
                return True
            else:
                logger.warning(
                    "Error al enviar alerta a Google Chat. Código HTTP: %s",
                    response.status,
                )
                return False

    except aiohttp.ClientError as exc:
        logger.error("Error de red al conectar con Google Chat Webhook: %s", type(exc).__name__)
        return False
    except Exception as exc:
        logger.error("Error inesperado en el notificador: %s", type(exc).__name__)
        return False
    finally:
        if own_session and session is not None:
            await session.close()
