"""
Módulo central de automatización y monitoreo con Playwright (Async API).
Opera bajo política Zero Credentials & Zero Data Retention:
observa directamente la pantalla/DOM activo sin almacenar ni requerir contraseñas,
sin capturas multimedia y con deduplicación en memoria volátil.
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
    Observa la pantalla/DOM activo y continúa el ciclo sin requerir credenciales.
    """

    def __init__(self) -> None:
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._http_session: Optional[aiohttp.ClientSession] = None
        self._attached_over_cdp: bool = False

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

    async def _attach_or_launch_screen(self) -> None:
        """
        Conecta el bot directamente a la pantalla activa sin usar credenciales:
        1. Si BROWSER_CDP_URL está definido, se acopla a la ventana/pestaña ya abierta por el supervisor.
        2. En caso contrario (Cloud Run / Colab), lanza Chromium Headless estricto y visualiza
           directamente la pantalla activa para comenzar a leer la grilla.
        """
        self._playwright = await async_playwright().start()

        if config.BROWSER_CDP_URL:
            logger.info("Acoplando Bot Guardián a la ventana activa del navegador vía CDP...")
            self._browser = await self._playwright.chromium.connect_over_cdp(config.BROWSER_CDP_URL)
            self._attached_over_cdp = True
            contexts = self._browser.contexts
            self._context = contexts[0] if contexts else await self._browser.new_context()
            pages = self._context.pages
            self._page = pages[0] if pages else await self._context.new_page()
            logger.info("Pantalla activa detectada correctamente. Continuando monitoreo sobre la vista actual.")
            return

        logger.info("Inicializando navegador Chromium en modo Headless estricto...")
        self._attached_over_cdp = False
        self._browser = await self._playwright.chromium.launch(
            headless=True,
            args=[arg.strip() for arg in config.CHROMIUM_ARGS if arg.strip()],
        )
        self._context = await self._browser.new_context(
            viewport={"width": 1280, "height": 720},
            ignore_https_errors=True,
            accept_downloads=False,
        )
        self._page = await self._context.new_page()

        # Bloquear recursos multimedia pesados innecesarios para optimizar CPU/RAM
        await self._page.route(
            "**/*.{png,jpg,jpeg,gif,webp,svg,mp4,webm,mp3,wav,woff,woff2,ttf}",
            lambda route: route.abort(),
        )

        if config.DASHBOARD_URL:
            logger.info("Abriendo vista en tiempo real y esperando carga de pantalla...")
            await self._page.goto(config.DASHBOARD_URL, wait_until="domcontentloaded", timeout=45000)

    async def _extract_agents_snapshot(self) -> list[dict[str, str]]:
        """
        Observa la pantalla activa del DOM y extrae únicamente:
        - Nombre o identificador del agente
        - Estado actual
        - Tiempo acumulado en ese estado
        Si hay varias pestañas abiertas en el contexto, inspecciona la que contenga la tabla de agentes.
        """
        if not self._context:
            return []

        pages_to_check = list(self._context.pages) if self._context.pages else ([self._page] if self._page else [])

        for candidate_page in pages_to_check:
            if candidate_page is None or candidate_page.is_closed():
                continue

            rows_locator = candidate_page.locator(config.SELECTOR_AGENT_ROWS)
            count = await rows_locator.count()
            if count == 0:
                continue

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
            if snapshot:
                return snapshot

        return []

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

            previous_record = self._agent_last_state.get(agent_name)
            if previous_record is not None:
                prev_state, prev_seconds = previous_record
                prev_key = f"{agent_name}_{prev_state}"

                # Caso 1: Cambió de estado (ej. de 'Break' a 'Disponible' o 'En llamada')
                if prev_state != normalized_state:
                    self._notified_keys.discard(prev_key)
                # Caso 2: Mismo estado pero el contador se reinició (ej. nueva llamada)
                elif elapsed_seconds < prev_seconds:
                    self._notified_keys.discard(state_key)

            self._agent_last_state[agent_name] = (normalized_state, elapsed_seconds)

            rule = self.classify_alert_rule(raw_state)
            if rule is None:
                continue

            event_type, threshold_seconds = rule

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

        disconnected_agents = set(self._agent_last_state.keys()) - seen_agents_in_cycle
        for absent_agent in disconnected_agents:
            prev_state, _ = self._agent_last_state.pop(absent_agent)
            self._notified_keys.discard(f"{absent_agent}_{prev_state}")

    async def run_monitoring_loop(self) -> None:
        """
        Ciclo principal de monitoreo asíncrono ejecutado en segundo plano.
        Observa la pantalla de la página y continúa monitoreando automáticamente.
        """
        if self._is_running:
            logger.warning("El ciclo de monitoreo ya se encuentra en ejecución.")
            return

        self._is_running = True
        self._stop_event.clear()
        self._http_session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))

        try:
            await self._attach_or_launch_screen()
            logger.info("Monitoreo WFM activo sobre la pantalla actual para LOB COACH.")

            while not self._stop_event.is_set():
                try:
                    agents_snapshot = await self._extract_agents_snapshot()
                    if agents_snapshot:
                        await self._process_agents(agents_snapshot)
                    else:
                        logger.debug("Esperando que la tabla de agentes sea visible en la pantalla actual...")
                except PlaywrightError as pw_err:
                    logger.warning(
                        "Aviso transitorio al leer la pantalla (%s). Continuando ciclo...",
                        type(pw_err).__name__,
                    )
                except Exception as loop_err:
                    logger.error(
                        "Error en iteración de monitoreo (%s).",
                        type(loop_err).__name__,
                    )

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
        Cierra de forma limpia y segura (graceful shutdown) la sesión HTTP y Playwright.
        Si estaba acoplado por CDP a la ventana del usuario, se desconecta sin cerrarle su ventana.
        """
        self._is_running = False
        self._stop_event.set()

        self._notified_keys.clear()
        self._agent_last_state.clear()

        if self._http_session and not self._http_session.closed:
            try:
                await self._http_session.close()
            except Exception:
                pass
        self._http_session = None

        if not self._attached_over_cdp:
            if self._page:
                try:
                    await self._page.close()
                except Exception:
                    pass
            if self._context:
                try:
                    await self._context.close()
                except Exception:
                    pass
            if self._browser:
                try:
                    await self._browser.close()
                except Exception:
                    pass

        self._page = None
        self._context = None
        self._browser = None

        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

        logger.info("Recursos de Playwright y memoria liberados correctamente (Graceful Shutdown).")
