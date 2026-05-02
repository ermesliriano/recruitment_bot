# app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.routers import admin, internal, questions, vacancies, webhook

app = FastAPI(title="Recruitment SaaS", version="2.0.0")

# ── CORS ──────────────────────────────────────────────────────────────────────
origins = ["*"] if settings.allow_origins == "*" else settings.allow_origins.split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(webhook.router)
app.include_router(admin.router)
app.include_router(internal.router)
app.include_router(vacancies.router)
app.include_router(questions.router)


# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/healthz", tags=["Health"])
def healthz():
    return {"status": "ok"}


# ── Frontend SPA (debe ir al final para no solapar rutas API) ─────────────────
app.mount("/", StaticFiles(directory="app/static", html=True), name="static")
