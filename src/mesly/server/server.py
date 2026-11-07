"""
FastAPI backend for the browser extension: translation + in-memory page context.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from threading import Thread

import uvicorn

from ..translation import TranslationService
from ..utils import Logger
from .context import BrowserContext


class TranslateRequest(BaseModel):
    text: str
    from_lang: str = "auto"
    to_lang: str = "en"


class ContextRequest(BaseModel):
    url: str
    title: str
    html: str
    type: str = "default"


class Server:
    def __init__(self, host="127.0.0.1", port=8000, translation_service: TranslationService = None,
                 config=None):
        self.host = host
        self.port = port
        self.config = config
        self.translation_service = translation_service or TranslationService()
        self.browser_context = BrowserContext()
        self.app = FastAPI(title="Mesly API")

        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        self._setup_routes()
        self._thread = None

    def _setup_routes(self):
        @self.app.get("/")
        async def root():
            return {"message": "Mesly server is running."}

        @self.app.post("/context")
        async def context(request: ContextRequest):
            # In-memory only: nothing is stored to disk
            self.browser_context.push(request.url, request.title, request.html)
            return {"status": "context updated"}

        @self.app.post("/context/select")
        async def selection(data: dict):
            if "text" in data:
                self.browser_context.selected_text = data["text"]
            return JSONResponse(content={"status": "selection updated"}, media_type="application/json")

        @self.app.post("/translate")
        def translate_text(request: TranslateRequest):
            """Translate text using the local MarianMT model."""
            return self.translation_service.translate(
                request.text, from_lang=request.from_lang, to_lang=request.to_lang
            )

    def start(self):
        """Start the FastAPI server in a background thread."""
        if self._thread is not None and self._thread.is_alive():
            return  # Already running

        def run_server():
            uvicorn.run(self.app, host=self.host, port=self.port, log_level="info")

        self._thread = Thread(target=run_server, daemon=True)
        self._thread.start()
        Logger.info(f"Server started on {self.host}:{self.port}")

    def is_running(self):
        """Check if the server thread is running."""
        return self._thread is not None and self._thread.is_alive()
