"""
Punto de entrada HTTP para Google Cloud Run y ejecución local bajo demanda.
Envuelve el ciclo de monitoreo de Playwright dentro de un servidor FastAPI ligero.
Responsable Técnico: Juan Esteban Serna Gutiérrez (Área WFM).
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Optional
import uvicorn
from fastapi import FastAPI, status
from fastapi.responses import JSONResponse

from bot_guardian import BotGuardian
from config import config

# Configuración de logging en consola (stdout para Cloud Logging, sin archivos en disco)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("bot_guardian.api")

# Instancia singleton del centinela y referencia a la tarea en segundo plano
sentinel = BotGuardian()
monitoring_task: Optional[asyncio.Task] = None
task_lock = asyncio.Lock()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Gestiona el ciclo de vida del contenedor en Google Cloud Run.
    Asegura que al recibir SIGTERM el navegador se cierre limpiamente.
    """
    logger.info("Servidor FastAPI de Bot Guardián listo en el puerto %s.", config.PORT)
    yield
    logger.info("Recibida señal de apagado del contenedor. Cerrando Bot Guardián...")
    await _stop_monitoring_task()


app = FastAPI(
    title="Bot Guardián - WFM Real-Time Sentinel (LOB COACH)",
    description="Asistente digital automatizado de monitoreo en tiempo real para Workforce Management.",
    version="1.0.0",
    lifespan=lifespan,
)


async def _stop_monitoring_task() -> None:
    """Cancela la tarea asíncrona activa y libera recursos de Playwright."""
    global monitoring_task
    async with task_lock:
        if monitoring_task and not monitoring_task.done():
            await sentinel.stop()
            monitoring_task.cancel()
            try:
                await monitoring_task
            except asyncio.CancelledError:
                pass
        else:
            await sentinel.shutdown()
        monitoring_task = None


@app.get("/", status_code=status.HTTP_200_OK)
async def healthcheck() -> dict[str, str]:
    """
    Endpoint de Healthcheck requerido por Google Cloud Run.
    Retorna el estado actual del bot: 'running' o 'idle'.
    """
    is_active = (
        sentinel.is_running
        and monitoring_task is not None
        and not monitoring_task.done()
    )
    return {"status": "running" if is_active else "idle"}


@app.post("/start", status_code=status.HTTP_202_ACCEPTED)
async def start_bot() -> JSONResponse:
    """
    Inicia la tarea de monitoreo de Playwright en segundo plano sin bloquear el hilo HTTP.
    """
    global monitoring_task
    async with task_lock:
        if (
            sentinel.is_running
            and monitoring_task is not None
            and not monitoring_task.done()
        ):
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={
                    "status": "running",
                    "message": "El monitoreo de Bot Guardián ya se encuentra en ejecución.",
                },
            )

        if not config.DASHBOARD_URL:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "status": "idle",
                    "error": "La variable de entorno WFM_DASHBOARD_URL es obligatoria para iniciar.",
                },
            )

        monitoring_task = asyncio.create_task(
            sentinel.run_monitoring_loop(),
            name="wfm_sentinel_loop",
        )
        logger.info("Tarea de monitoreo disparada mediante POST /start.")

        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={
                "status": "running",
                "message": "Monitoreo WFM iniciado en segundo plano para LOB COACH.",
            },
        )


@app.post("/stop", status_code=status.HTTP_200_OK)
async def stop_bot() -> dict[str, str]:
    """
    Cancela la tarea en segundo plano y cierra de forma limpia la sesión y el navegador.
    """
    await _stop_monitoring_task()
    logger.info("Monitoreo detenido mediante POST /stop.")
    return {
        "status": "idle",
        "message": "Monitoreo detenido y sesión de Playwright cerrada limpiamente.",
    }


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=config.HOST,
        port=config.PORT,
        log_level="info",
    )
