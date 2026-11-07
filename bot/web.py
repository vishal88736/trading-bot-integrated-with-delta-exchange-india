import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from filelock import FileLock, Timeout
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from starlette.middleware.trustedhost import TrustedHostMiddleware

from bot.service import Service
from bot.settings import Settings, atomic_json
from clients.delta import DeltaError

STATIC = Path(__file__).parent / "static"


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_key: SecretStr = Field(min_length=1, max_length=512)
    api_secret: SecretStr = Field(min_length=1, max_length=512)


def create_app(root: Path = Path(".runtime")):
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    service = Service(root)

    @asynccontextmanager
    async def lifespan(app):
        lock = FileLock(root / "server.lock", timeout=0)
        try:
            lock.acquire()
        except Timeout:
            raise RuntimeError("Another dashboard is already using this runtime folder") from None
        try:
            yield
        finally:
            await asyncio.to_thread(service.stop)
            lock.release()

    app = FastAPI(title="Delta / Automation", lifespan=lifespan)
    app.state.service = service
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"]
    )

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request, exc):
        from fastapi.responses import JSONResponse

        # FastAPI's default validation payload can echo password inputs.
        errors = exc.errors()
        if request.url.path == "/api/credentials":
            detail = "Check the demo key and secret fields"
        else:
            detail = "; ".join(error["msg"] for error in errors)
        return JSONResponse({"detail": detail}, status_code=422)

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        # Cross-site pages must never be able to start a locally authenticated trading bot.
        if request.method in ("POST", "PUT", "DELETE", "PATCH"):
            origin = request.headers.get("origin")
            expected = urlparse(str(request.base_url))
            parsed = urlparse(origin) if origin else None
            if parsed and (parsed.scheme != expected.scheme or parsed.netloc != expected.netloc):
                from fastapi.responses import JSONResponse

                return JSONResponse({"detail": "Cross-origin request blocked"}, status_code=403)
            if request.headers.get("content-type", "").split(";")[0] != "application/json":
                from fastapi.responses import JSONResponse

                return JSONResponse({"detail": "JSON request required"}, status_code=415)
        response = await call_next(request)
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "Content-Security-Policy": "default-src 'self'; style-src 'self'; "
                "script-src 'self'; img-src 'self' data:; frame-ancestors 'none'",
            }
        )
        return response

    @app.exception_handler(DeltaError)
    async def exchange_error(request, exc):
        from fastapi.responses import JSONResponse

        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/api/status")
    def status():
        with service.lock:
            return service.snapshot()

    @app.post("/api/settings")
    def settings(value: Settings):
        with service.lock:
            service.assert_editable()
            atomic_json(root / "settings.json", value.model_dump())
            service.engine = None
            return {"saved": True}

    @app.post("/api/credentials")
    def credentials(value: Credentials):
        with service.lock:
            service.assert_editable()
            key, secret = (
                value.api_key.get_secret_value().strip(),
                value.api_secret.get_secret_value().strip(),
            )
            if not key or not secret:
                raise HTTPException(422, "Both demo key and secret are required")
            atomic_json(root / "credentials.json", {"api_key": key, "api_secret": secret})
            return {"saved": True}

    @app.post("/api/start")
    def start():
        service.start()
        return {"started": True}

    @app.post("/api/stop")
    def stop():
        service.stop()
        return {"stopped": True}

    @app.post("/api/reconcile")
    def reconcile():
        with service.lock:
            service.reconcile()
            return {"reconciled": True}

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
