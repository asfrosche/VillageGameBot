from __future__ import annotations

import asyncio
import logging
import re
import subprocess
import threading
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Depends
from fastapi.staticfiles import StaticFiles

from .api import overview, commands, performance, errors, features, cogs
from .auth import create_auth_dependency
from .config import DashboardConfig

logger = logging.getLogger("analytics.dashboard")

_server: uvicorn.Server | None = None
_thread: threading.Thread | None = None
_timer: threading.Timer | None = None
_LOCK = threading.Lock()
_tunnel_url: str | None = None
_tunnel_process: subprocess.Popen | None = None
_SHUTDOWN_TIMEOUT = 600  # 10 minutes


def create_app(config: DashboardConfig) -> FastAPI:
    app = FastAPI(
        title="Analytics Dashboard",
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
    )

    auth = create_auth_dependency(config.password)

    app.include_router(overview.router, dependencies=[Depends(auth)])
    app.include_router(commands.router, dependencies=[Depends(auth)])
    app.include_router(performance.router, dependencies=[Depends(auth)])
    app.include_router(errors.router, dependencies=[Depends(auth)])
    app.include_router(features.router, dependencies=[Depends(auth)])
    app.include_router(cogs.router, dependencies=[Depends(auth)])

    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app


def _run_uvicorn(config: DashboardConfig) -> None:
    global _server
    app = create_app(config)
    _server = uvicorn.Server(
        uvicorn.Config(app, host=config.host, port=config.port, log_level="info")
    )
    _server.run()


def start_dashboard(config: DashboardConfig | None = None) -> None:
    global _thread, _timer
    cfg = config or DashboardConfig.from_env()
    if not cfg.enabled:
        logger.info("Dashboard disabled by configuration")
        return

    with _LOCK:
        _cancel_timer()
        if _thread is None or not _thread.is_alive():
            _thread = threading.Thread(target=_run_uvicorn, args=(cfg,), daemon=True)
            _thread.start()
            logger.info("Dashboard started on %s:%s", cfg.host, cfg.port)

            if cfg.tunnel_enabled:
                tunnel_thread = threading.Thread(target=_start_tunnel, args=(cfg,), daemon=True)
                tunnel_thread.start()

        _timer = threading.Timer(_SHUTDOWN_TIMEOUT, _stop_dashboard)
        _timer.daemon = True
        _timer.start()
        logger.info("Dashboard auto-shutdown in %s seconds", _SHUTDOWN_TIMEOUT)


def stop_dashboard() -> None:
    with _LOCK:
        _cancel_timer()
        _stop_dashboard()


def _stop_dashboard() -> None:
    global _server, _thread
    _stop_tunnel()
    if _server:
        try:
            _server.should_exit = True
        except Exception:
            pass
        _server = None
    _thread = None
    logger.info("Dashboard stopped")


def _cancel_timer() -> None:
    global _timer
    if _timer:
        _timer.cancel()
        _timer = None


# ── Tunnel (localhost.run) ──────────────────────────────────────────────────


def _start_tunnel(config: DashboardConfig) -> str | None:
    global _tunnel_process, _tunnel_url
    _tunnel_url = None
    try:
        proc = subprocess.Popen(
            ["ssh", "-o", "StrictHostKeyChecking=no",
             "-o", "ServerAliveInterval=30",
             "-R", f"80:localhost:{config.port}",
             "nokey@localhost.run"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        )
        _tunnel_process = proc
        for line in iter(proc.stdout.readline, ""):
            m = re.search(r"https://(?!admin\.)[a-zA-Z0-9-]+\.(?:lhr\.life|localhost\.run)", line)
            if m:
                _tunnel_url = m.group(0)
                logger.info("Tunnel URL: %s", _tunnel_url)
                return _tunnel_url
            logger.debug("Tunnel: %s", line.rstrip())
    except Exception as exc:
        logger.warning("Tunnel failed: %s", exc)
    return None


def _stop_tunnel() -> None:
    global _tunnel_process, _tunnel_url
    if _tunnel_process:
        try:
            _tunnel_process.terminate()
            _tunnel_process.wait(timeout=5)
        except Exception:
            try:
                _tunnel_process.kill()
            except Exception:
                pass
        _tunnel_process = None
    _tunnel_url = None


def get_tunnel_url() -> str | None:
    return _tunnel_url


# ── Legacy runner ───────────────────────────────────────────────────────────


def run_dashboard(config: DashboardConfig | None = None) -> None:
    """Legacy blocking run — kept for backward compatibility."""
    cfg = config or DashboardConfig.from_env()
    if not cfg.enabled:
        return
    app = create_app(cfg)
    uvicorn.run(app, host=cfg.host, port=cfg.port, log_level="info")
