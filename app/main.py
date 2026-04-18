# app/main.py
from fastapi import FastAPI

from app.api_webhooks import admin_router, internal_router, webhook_router

app = FastAPI(title="Recruitment Chatbot SaaS", version="1.0.0")

@app.get("/healthz")
def healthz():
    return {"ok": True}

app.include_router(webhook_router)
app.include_router(admin_router)
app.include_router(internal_router)