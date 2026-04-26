# app/llm_client.py
import json
import re
import time
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core import settings

class LlmEvaluationPayload(BaseModel):
    candidate_profile: dict[str, Any] = Field(default_factory=dict)
    experience_summary: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    red_flags: list[str] = Field(default_factory=list)
    cv_score_0_10: float = Field(ge=0, le=10)
    recommendation: str

    model_config = ConfigDict(extra="ignore")

PROMPT_TEMPLATE = """
Eres un evaluador de CV para reclutamiento.
Devuelve EXCLUSIVAMENTE JSON válido, sin markdown y sin texto adicional.
Usa EXACTAMENTE esta estructura:

{{
  "candidate_profile": {{}},
  "experience_summary": [],
  "skills": [],
  "red_flags": [],
  "cv_score_0_10": 0,
  "recommendation": ""
}}

Vacante:
- Título: {title}
- Descripción: {description}
- Requisitos obligatorios: {mandatory}
- Requisitos deseables: {desirable}
- Ubicación: {location}
- Horario: {schedule}

CV:
{cv_text}
""".strip()

def extract_json_object(raw: str) -> dict[str, Any]:
    raw = raw.strip()
    match = re.search(r"\{.*\}", raw, flags=re.S)
    if not match:
        raise ValueError("No se encontró JSON en la respuesta")
    return json.loads(match.group(0))

class LlmClient:
    def __init__(self):
        self.client = httpx.Client(timeout=120)

    def evaluate_cv(self, vacancy: dict[str, Any], cv_text: str) -> tuple[LlmEvaluationPayload, str, int]:
    
        log_event(
            db,
            level="INFO",
            source="llm",
            event="REQUEST",
            payload={"text_length": len(text)},
            application_id=app.id,
        )
        
        prompt = PROMPT_TEMPLATE.format(
            title=vacancy["title"],
            description=vacancy["description"],
            mandatory=", ".join(vacancy["mandatory_requirements"]),
            desirable=", ".join(vacancy["desirable_requirements"]),
            location=vacancy.get("location_text") or "",
            schedule=vacancy.get("schedule_text") or "",
            cv_text=cv_text[: settings.llm_cv_char_limit],
        )

        last_error = None
        for attempt in range(1, settings.llm_max_retries + 1):
            if attempt > 1:
                time.sleep(40 * (attempt - 1))

            started = time.perf_counter()
            resp = self.client.post(
                settings.llm_url,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {settings.llm_api_key}",
                },
                json={"message": prompt, "model": settings.llm_model},
            )
            latency_ms = int((time.perf_counter() - started) * 1000)

            if resp.status_code == 429:
                last_error = RuntimeError("Rate limit del proveedor")
                continue

            resp.raise_for_status()
            payload = resp.json()
            raw = payload["response"]
            try:
                obj = extract_json_object(raw)
                validated = LlmEvaluationPayload.model_validate(obj)
                return validated, raw, latency_ms
            except (json.JSONDecodeError, ValidationError, ValueError) as exc:
                log_event(
                    db,
                    level="ERROR",
                    source="llm",
                    event="FAILURE",
                    message=str(exc),
                    exc=exc,
                    application_id=app.id,
                )
                last_error = exc
                prompt = prompt + "\n\nTu respuesta anterior no fue JSON válido. Repite devolviendo únicamente JSON válido."

        raise RuntimeError(f"LLM error: {last_error}")
