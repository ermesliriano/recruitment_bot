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
Eres un evaluador técnico de CV para procesos de reclutamiento.

Analiza el CV en relación con la vacante indicada.

Devuelve EXCLUSIVAMENTE JSON válido con esta estructura:

{{
  "candidate_profile": {{}},
  "experience_summary": [],
  "skills": [],
  "red_flags": [],
  "cv_score_0_10": 0,
  "recommendation": ""
}}

Reglas:
- cv_score_0_10 debe ser un número entre 0 y 10.
- recommendation debe ser una de estas opciones:
  "muy_idoneo", "idoneo", "revisar", "no_idoneo".
- No añadas markdown.
- No añadas explicación fuera del JSON.

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

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", raw, flags=re.S)
    if not match:
        raise ValueError("No se encontró JSON en la respuesta del LLM")

    return json.loads(match.group(0))


class LlmClient:
    def __init__(self):
        self.client = httpx.Client(timeout=120)

        self.provider = getattr(settings, "llm_provider", "openai")
        self.openai_api_key = settings.openai_api_key
        self.openai_model = getattr(settings, "openai_model", "gpt-4o-mini")
        self.openai_url = getattr(
            settings,
            "openai_url",
            "https://api.openai.com/v1/chat/completions",
        )

    def evaluate_cv(
        self,
        vacancy: dict[str, Any],
        cv_text: str,
    ) -> tuple[LlmEvaluationPayload, str, int]:

        if self.provider != "openai":
            raise RuntimeError(f"Proveedor LLM no soportado: {self.provider}")

        prompt = PROMPT_TEMPLATE.format(
            title=vacancy["title"],
            description=vacancy["description"],
            mandatory=", ".join(vacancy["mandatory_requirements"]),
            desirable=", ".join(vacancy["desirable_requirements"]),
            location=vacancy.get("location_text") or "",
            schedule=vacancy.get("schedule_text") or "",
            cv_text=(cv_text or "")[: settings.llm_cv_char_limit],
        )

        last_error: Exception | None = None

        for attempt in range(1, settings.llm_max_retries + 1):
            if attempt > 1:
                time.sleep(min(10 * attempt, 40))

            started = time.perf_counter()

            try:
                resp = self.client.post(
                    self.openai_url,
                    headers={
                        "Authorization": f"Bearer {self.openai_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.openai_model,
                        "temperature": 0,
                        "messages": [
                            {
                                "role": "system",
                                "content": (
                                    "Eres un sistema de evaluación de CV. "
                                    "Debes responder únicamente JSON válido."
                                ),
                            },
                            {
                                "role": "user",
                                "content": prompt,
                            },
                        ],
                        "response_format": {
                            "type": "json_schema",
                            "json_schema": {
                                "name": "cv_evaluation",
                                "strict": True,
                                "schema": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "properties": {
                                        "candidate_profile": {
                                            "type": "object",
                                            "additionalProperties": True,
                                        },
                                        "experience_summary": {
                                            "type": "array",
                                            "items": {"type": "string"},
                                        },
                                        "skills": {
                                            "type": "array",
                                            "items": {"type": "string"},
                                        },
                                        "red_flags": {
                                            "type": "array",
                                            "items": {"type": "string"},
                                        },
                                        "cv_score_0_10": {
                                            "type": "number",
                                            "minimum": 0,
                                            "maximum": 10,
                                        },
                                        "recommendation": {
                                            "type": "string",
                                            "enum": [
                                                "muy_idoneo",
                                                "idoneo",
                                                "revisar",
                                                "no_idoneo",
                                            ],
                                        },
                                    },
                                    "required": [
                                        "candidate_profile",
                                        "experience_summary",
                                        "skills",
                                        "red_flags",
                                        "cv_score_0_10",
                                        "recommendation",
                                    ],
                                },
                            },
                        },
                    },
                )

                latency_ms = int((time.perf_counter() - started) * 1000)

                if resp.status_code == 429:
                    last_error = RuntimeError("Rate limit del proveedor OpenAI")
                    continue

                resp.raise_for_status()

                response_json = resp.json()
                raw = response_json["choices"][0]["message"]["content"]

                obj = extract_json_object(raw)
                validated = LlmEvaluationPayload.model_validate(obj)

                return validated, raw, latency_ms

            except (httpx.HTTPError, json.JSONDecodeError, KeyError, ValidationError, ValueError) as exc:
                last_error = exc

                if attempt >= settings.llm_max_retries:
                    raise RuntimeError(f"LLM error: {last_error}") from exc

        raise RuntimeError(f"LLM error: {last_error}")