"""
Módulo central de automatización y monitoreo con Playwright (Async API).
Implementa extracción mínima del DOM, políticas Zero Data Retention, sin capturas
multimedia, y deduplicación de alertas en memoria volátil.
"""

import asyncio
import logging
import re
from typing import Optional
import aiohttp
from playwright.async_api import (
    async_playwright,
    Playwright,
    Browser,
    BrowserContext,
    Page,
    Error as PlaywrightError,
)

from config import config
from notifier import send_google_chat_alert

logger = logging.getLogger("bot_guardian.sentinel")


class BotGuardian:
    """
    Orquestador de monitoreo WFM en tiempo real para la LOB COACH.
    Opera 100% en memoria RAM (Zero Data Retention) y en modo Headless estricto.
    """

    def __init__(self) -> None:
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._http_session: Optional[aiohttp.ClientSession] = None

        self._is_running: bool = False
        self._stop_event: asyncio.Event = asyncio.Event()

        # Memoria volátil para deduplicación:
        # - _notified_keys: conjunto de claves f"{agent_name}_{normalized_state}" ya notificadas
        # - _agent_last_state: diccionario {agent_name: (normalized_state, last_seconds)}
        self._notified_keys: set[str] = set()
        self._agent_last_state: dict[str, tuple[str, int]] = {}

    @property
    def is_running(self) -> bool:
        return self._is_running

    @staticmethod
    def parse_duration_to_seconds(raw_time: str) -> Optional[int]:
        """
        Convierte cadenas de tiempo en formato 'MM:SS' o 'HH:MM:SS' a segundos totales.
        Retorna None si el formato no es válido.
        """
        if not raw_time:
            return None

        cleaned = raw_time.strip()
        # Extraer patrón HH:MM:SS o MM:SS incluso si viene rodeado de texto adicional
        match = re.search(r"(\d{1,3}):(\d{2})(?::(\d{2}))?", cleaned)
        if not match:
            return None

        part1, part2, part3 = match.group(1), match.group(2), match.group(3)
        try:
            if part3 is not None:
                hours = int(part1)
                minutes = int(part2)
                seconds = int(part3)
                return (hours * 3600) + (minutes * 60) + seconds
            else:
                minutes = int(part1)
                seconds = int(part2)
                return (minutes * 60) + seconds
        except ValueError:
            return None

    @staticmethod
    def classify_alert_rule(state_raw: str) -> Optional[tuple[str, int]]:
        """
        Evalúa si el estado actual del agente corresponde a una regla monitoreada.
        Retorna una tupla (nombre_evento, umbral_en_segundos) o None si no aplica.
        """
        normalized = state_raw.strip().lower()
        if not normalized:
            return None

        if any(keyword in normalized for keyword in config.CALL_STATES):
            return ("Long Call", config.THRESHOLD_LONG_CALL)
        if any(keyword in normalized for keyword in config.BREAK_STATES):
            return ("Over Break", config.THRESHOLD_OVER_BREAK)
        if any(keyword in normalized for keyword in config.LUNCH_STATES):
            return ("Over Lunch", config.THRESHOLD_OVER_LUNCH)

        return None

    async def _init_browser(self) -> None:
        """
        Inicializa Playwright y Chromium en modo Headless estricto con banderas
        optimizadas para contenedores Linux en Google Cloud Run.
        """
        logger.info("Inicializando navegador Chromium en modo Headless estricto...")
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=True,
            args=[arg.strip() for arg in config.CHROMIUM_ARGS if arg.strip()],
        )
        # Contexto sin almacenamiento persistente ni grabación de video
        self._context = await self._browser.new_context(
            viewport={"width": 1280, "height": 720},
            ignore_https_errors=True,
            accept_downloads=False,
        )
        self._page = await self._context.new_page()

        # Bloquear recursos multimedia pesados innecesarios para optimizar CPU/RAM en Cloud Run
        await self._page.route(
            "**/*.{png,jpg,jpeg,gif,webp,svg,mp4,webm,mp3,wav,woff,woff2,ttf}",
            lambda route: route.abort(),
        )

    async def _authenticate_if_needed(self) -> None:
        """
        Navega a la URL de login/dashboard y ejecuta autenticación si las credenciales
        están configuradas y el formulario de acceso está presente en el DOM.
        """
        if not self._page:
            raise RuntimeError("La página de Playwright no ha sido inicializada.")

        target_url = config.LOGIN_URL or config.DASHBOARD_URL
        if not target_url:
            raise ValueError("WFM_DASHBOARD_URL no está configurada en las variables de entorno.")

        logger.info("Navegando al portal WFM...")
        await self._page.goto(target_url, wait_until="domcontentloaded", timeout=45000)

        # Verificar si se requiere autenticación por formulario
        if config.WFM_USERNAME and config.WFM_PASSWORD:
            user_locator = self._page.locator(config.SELECTOR_USERNAME_INPUT).first
            if await user_locator.count() > 0 and await user_locator.is_visible():
                logger.info("Formulario de autenticación detectado. Iniciando sesión...")
                await user_locator.fill(config.WFM_USERNAME)
                await self._page.locator(config.SELECTOR_PASSWORD_INPUT).first.fill(
                    config.WFM_PASSWORD
                )
                await self._page.locator(config.SELECTOR_LOGIN_BUTTON).first.click()
                await self._page.wait_for_load_state("domcontentloaded", timeout=30000)

        # Si existe una URL de dashboard distinta a la de login, navegar a ella
        if config.LOGIN_URL and config.DASHBOARD_URL and self._page.url != config.DASHBOARD_URL:
            await self._page.goto(
                config.DASHBOARD_URL, wait_until="domcontentloaded", timeout=45000
            )

    async def _extract_agents_snapshot(self) -> list[dict[str, str]]:
        """
        Realiza una extracción mínima del DOM leyendo únicamente:
        - Nombre o identificador del agente
        - Estado actual
        - Tiempo acumulado en ese estado
        Prohibido extraer datos de clientes, transcripciones o tomar capturas.
        """
        if not self._page:
            return []

        # Extracción ligera en un solo llamado evaluate_all para minimizar overhead IPC
        rows_locator = self._page.locator(config.SELECTOR_AGENT_ROWS)
        count = await rows_locator.count()
        if count == 0:
            return []

        snapshot: list[dict[str, str]] = await rows_locator.evaluate_all(
            """(rows, selectors) => {
                return rows.map(row => {
                    const nameEl = row.querySelector(selectors.name);
                    const stateEl = row.querySelector(selectors.state);
                    const timeEl = row.querySelector(selectors.time);
                    return {
                        agent_name: nameEl ? nameEl.innerText.trim() : "",
                        state: stateEl ? stateEl.innerText.trim() : "",
                        time_str: timeEl ? timeEl.innerText.trim() : ""
                    };
                }).filter(item => item.agent_name !== "" && item.state !== "");
            }""",
            {
                "name": config.SELECTOR_AGENT_NAME,
                "state": config.SELECTOR_AGENT_STATE,
                "time": config.SELECTOR_AGENT_TIME,
            },
        )
        return snapshot

    async def _process_agents(self, agents_data: list[dict[str, str]]) -> None:
        """
        Aplica la lógica de negocio WFM, evalúa umbrales y gestiona la deduplicación
        y reseteo automático de estados en memoria.
        """
        seen_agents_in_cycle: set[str] = set()

        for item in agents_data:
            agent_name = item["agent_name"]
            raw_state = item["state"]
            normalized_state = raw_state.strip().lower()
            elapsed_seconds = self.parse_duration_to_seconds(item["time_str"])

            if elapsed_seconds is None:
                continue

            seen_agents_in_cycle.add(agent_name)
            state_key = f"{agent_name}_{normalized_state}"

            # Verificar si el agente cambió de estado o reinició su cronómetro en el mismo estado
            previous_record = self._agent_last_state.get(agent_name)
            if previous_record is not None:
                prev_state, prev_seconds = previous_record
                prev_key = f"{agent_name}_{prev_state}"

                # Caso 1: Cambió de estado (ej. de 'Break' a 'Disponible' o 'En llamada')
                if prev_state != normalized_state:
                    self._notified_keys.discard(prev_key)
                # Caso 2: Mismo estado pero el contador se reinició (ej. nueva llamada tras colgar la anterior)
                elif elapsed_seconds < prev_seconds:
                    self._notified_keys.discard(state_key)

            # Actualizar el estado actual en memoria volátil
            self._agent_last_state[agent_name] = (normalized_state, elapsed_seconds)

            # Evaluar si el estado aplica a una regla WFM (Long Call / Over Break / Over Lunch)
            rule = self.classify_alert_rule(raw_state)
            if rule is None:
                continue

            event_type, threshold_seconds = rule

            # Si supera el umbral y no ha sido notificado en este estado actual -> Disparar Alerta Única
            if elapsed_seconds > threshold_seconds and state_key not in self._notified_keys:
                sent = await send_google_chat_alert(
                    agent_name=agent_name,
                    event_type=event_type,
                    current_state=raw_state,
                    elapsed_seconds=elapsed_seconds,
                    threshold_seconds=threshold_seconds,
                    session=self._http_session,
                )
                if sent:
                    self._notified_keys.add(state_key)

        # Limpiar agentes que ya no aparecen en el grid (desconectados) para evitar fugas de memoria
        disconnected_agents = set(self._agent_last_state.keys()) - seen_agents_in_cycle
        for absent_agent in disconnected_agents:
            prev_state, _ = self._agent_last_state.pop(absent_agent)
            self._notified_keys.discard(f"{absent_agent}_{prev_state}")

    async def run_monitoring_loop(self) -> None:
        """
        Ciclo principal de monitoreo asíncrono ejecutado en segundo plano.
        """
        if self._is_running:
            logger.warning("El ciclo de monitoreo ya se encuentra en ejecución.")
            return

        self._is_running = True
        self._stop_event.clear()
        self._http_session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))

        try:
            await self._init_browser()
            await self._authenticate_if_needed()
            logger.info("Monitoreo WFM iniciado exitosamente para LOB COACH.")

            while not self._stop_event.is_set():
                try:
                    agents_snapshot = await self._extract_agents_snapshot()
                    await self._process_agents(agents_snapshot)
                except PlaywrightError as pw_err:
                    logger.warning(
                        "Error transitorio de Playwright durante lectura del DOM (%s). Reintentando...",
                        type(pw_err).__name__,
                    )
                except Exception as loop_err:
                    logger.error(
                        "Error en iteración de monitoreo (%s).",
                        type(loop_err).__name__,
                    )

                # Espera no bloqueante interrumpible de inmediato por /stop
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=config.POLL_INTERVAL_SECONDS,
                    )
                except asyncio.TimeoutError:
                    pass

        except asyncio.CancelledError:
            logger.info("Tarea de monitoreo cancelada bajo demanda.")
            raise
        except Exception as fatal_err:
            logger.error("Fallo crítico al iniciar o mantener el monitoreo: %s", fatal_err)
        finally:
            await self.shutdown()

    async def stop(self) -> None:
        """Señaliza la detención inmediata del bucle y ejecuta el cierre limpio."""
        self._stop_event.set()
        await self.shutdown()

    async def shutdown(self) -> None:
        """
        Cierra de forma limpia y segura (graceful shutdown) la sesión HTTP,
        la página, el contexto, el navegador Chromium y la instancia de Playwright.
        Limpia además los registros en memoria RAM.
        """
        self._is_running = False
        self._stop_event.set()

        # Limpiar estructuras en memoria volátil
        self._notified_keys.clear()
        self._agent_last_state.clear()

        if self._http_session and not self._http_session.closed:
            try:
                await self._http_session.close()
            except Exception:
                pass
        self._http_session = None

        if self._page:
            try:
                await self._page.close()
            except Exception:
                pass
            self._page = None

        if self._context:
            try:
                await self._context.close()
            except Exception:
                pass
            self._context = None

        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None

        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

        logger.info("Recursos de Playwright y memoria liberados correctamente (Graceful Shutdown).")
