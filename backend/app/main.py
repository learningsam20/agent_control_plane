from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from sqlalchemy.orm import Session

from . import opa, telemetry
from .config import get_settings
from .database import SessionLocal, init_db
from .routers import agents, audit, dashboard, datahub, delegations, demo, policies, requests, runs
from .seed import seed

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    telemetry.init_telemetry("controlplane")
    FastAPIInstrumentor.instrument_app(app, tracer_provider=telemetry.get_tracer_provider())
    HTTPXClientInstrumentor().instrument(tracer_provider=telemetry.get_tracer_provider())
    init_db()
    with SessionLocal() as db:
        seed(db)
    if settings.policy_engine in ("auto", "opa") and opa.available():
        pushed = opa.push_policy_file()
        print(f"[control-plane] OPA reachable at {settings.opa_url}; "
              f"policy {settings.opa_policy_name} pushed={pushed}; using OPA engine")
    yield


app = FastAPI(
    title="Agent Control Plane 2.0",
    description="Zero-trust control plane for AI agents acting on organizational data.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for router in (
    agents.router,
    delegations.router,
    requests.router,
    audit.router,
    policies.router,
    datahub.router,
    dashboard.router,
    demo.router,
    runs.router,
):
    app.include_router(router, prefix=settings.api_prefix)


@app.get("/health")
def health():
    return {"status": "ok", "app": settings.app_name}


# Serve the built React console from the same process (single-container deploy).
# `frontend/dist` is produced by the Docker images; local dev uses the Vite
# dev server instead, so this is a no-op when the build directory is absent.
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def _serve_index() -> FileResponse | JSONResponse:
    index = FRONTEND_DIST / "index.html"
    if index.is_file():
        return FileResponse(index)
    return JSONResponse({"detail": "frontend not built (use `npm run build` or the Vite dev server)"}, status_code=404)


if (FRONTEND_DIST / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")


@app.get("/{full_path:path}", include_in_schema=False)
def spa(full_path: str):
    if full_path.startswith(("api/", "health")):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    return _serve_index()
