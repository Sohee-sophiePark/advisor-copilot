"""FastAPI app factory with CORS for the Vite dev server."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from advisor_copilot.api.routes import router
from advisor_copilot.config import Settings, get_settings
from advisor_copilot.llm.base import LLMClient


def create_app(settings: Settings | None = None, llm: LLMClient | None = None) -> FastAPI:
    app = FastAPI(title="Advisor Copilot")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    app.state.settings, app.state.llm, app.state.runs = settings or get_settings(), llm, {}
    app.include_router(router)
    return app
