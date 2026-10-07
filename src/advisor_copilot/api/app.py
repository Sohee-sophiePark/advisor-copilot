"""FastAPI app factory: local Host names only, CORS for the Vite dev server; dev routes only when
DEV_CONSOLE=1."""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from advisor_copilot.api.routes import dev, router
from advisor_copilot.config import Settings, get_settings
from advisor_copilot.db import Store
from advisor_copilot.llm.base import LLMClient


def create_app(settings: Settings | None = None, llm: LLMClient | None = None) -> FastAPI:
    app = FastAPI(title="Advisor Copilot")
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1"]
    )  # DNS rebinding
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    app.state.settings, app.state.llm, app.state.runs = settings or get_settings(), llm, {}
    app.state.store = Store(app.state.settings.path("db"))
    app.include_router(router)
    if os.environ.get("DEV_CONSOLE") == "1":
        app.include_router(dev)
    return app
