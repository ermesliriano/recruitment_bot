# app/llm_client.py
import json
import re
import time
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.config import settings


# ── Modelos de respuesta ───────────────────────────────────────────────────────

class CvInferredAnswer(BaseModel):
    """
    Respuesta inferida por el LLM a partir del contenido del CV.
    Una entrada por cada pregunta de la vacante recibida en el prompt.
    """
    vacancy_question_id: str
    field_key: str
    prompt_text: str
    answer_type: str

    is_answered_in_cv: bool = False
    normalized_answer: str | None = None

    evidence: str | None = None
    confidence: float = Field(default=0, ge=0, le=1)

    model_config = ConfigDict(extra="ignore")


class LlmEvaluationPayload(BaseModel):
    candidate_profile: dict[str, Any] = Field(default_factory=dict)
    experience_summary: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    red_flags: list[str] = Field(default_factory=list)
    cv_score_0_10: float = Field(ge=0, le=10)
    recommendation: str

    # Preguntas de la vacante que el LLM ha podido responder desde el CV.
    answered_vacancy_questions: list[CvInferredAnswer] = Field(default_factory=list)

    model_config = ConfigDict(extra="ignore")


# ── Prompt ─────────────────────────────────────────────────────────────────────

PROMPT_TEMPLATE = """
Eres un evaluador técnico de CV para procesos de reclutamiento.

Analiza el CV en relación con la vacante indicada.

Además de evaluar el CV de forma general, debes revisar si el propio CV contiene información suficiente para responder cada una de las preguntas específicas asociadas a la vacante. Solo responde una pregunta si hay evidencia clara en el CV; si no la hay, márcala como no respondida.

También recibirás, si existen, respuestas genéricas del candidato a preguntas globales del tenant. Debes incorporarlas al análisis general del perfil y hacer que influyan en cv_score_0_10.

Devuelve EXCLUSIVAMENTE JSON válido con esta estructura exacta:

{{
  "candidate_profile": {{}},
  "experience_summary": [],
  "skills": [],
  "red_flags": [],
  "cv_score_0_10": 0,
  "recommendation": "",
  "answered_vacancy_questions": [
    {{
      "vacancy_question_id": "",
      "field_key": "",
      "prompt_text": "",
      "answer_type": "text",
      "is_answered_in_cv": false,
      "normalized_answer": null,
      "evidence": null,
      "confidence": 0
    }}
  ]
}}

Reglas generales:
- cv_score_0_10 debe ser un número entre 0 y 10.
- recommendation debe ser exactamente uno de: "muy_idoneo", "idoneo", "revisar" o "no_idoneo".
- No añadas markdown, backticks ni texto fuera del JSON.

Reglas sobre respuestas genéricas del candidato:
- Considéralas declaraciones explícitas del candidato.
- Úsalas para enriquecer candidate_profile, experience_summary, red_flags y cv_score_0_10.
- Si alguna respuesta contradice el CV, prioriza la respuesta explícita del candidato y registra la inconsistencia en red_flags.
- No las devuelvas dentro de answered_vacancy_questions.

Reglas para answered_vacancy_questions:
- Debes devolver UNA entrada por cada pregunta recibida en "Preguntas asociadas a la vacante".
- is_answered_in_cv=true solo si el CV contiene evidencia clara y directa.
- Si no hay evidencia suficiente, usa is_answered_in_cv=false, normalized_answer=null, evidence=null y confidence=0.
- confidence debe estar entre 0 y 1.
- Para answer_type="boolean", normalized_answer debe ser "sí" o "no".
- Para answer_type="number", normalized_answer debe ser únicamente un número en texto.
- Para answer_type="text", normalized_answer debe ser una respuesta breve y literal al CV.
- No inventes información.
- La evidencia debe ser un fragmento breve o resumen del CV que justifique la respuesta.

Vacante:
- Título: {title}
- Descripción: {description}
- Requisitos obligatorios: {mandatory}
- Requisitos deseables: {desirable}
- Ubicación: {location}
- Horario: {schedule}

Respuestas genéricas del candidato:
{tenant_screening_answers_json}

Preguntas asociadas a la vacante:
{vacancy_questions_json}

CV del candidato:
{cv_text}
""".strip()


# ── Utilidades internas ────────────────────────────────────────────────────────

def _extract_json_object(raw: str) -> dict[str, Any]:
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", raw, flags=re.S)
    if not match:
        raise ValueError("No se encontró JSON en la respuesta del LLM")

    return json.loads(match.group(0))


def _normalize_payload(obj: dict) -> dict:
    # Normaliza experience_summary si el LLM devuelve objetos en lugar de strings.
    exp = obj.get("experience_summary")
    if isinstance(exp, list) and exp and isinstance(exp[0], dict):
        obj["experience_summary"] = [
            f"{e.get('company', '')} - {e.get('role', '')}".strip()
            for e in exp
        ]

    # Garantiza que answered_vacancy_questions siempre sea lista.
    questions = obj.get("answered_vacancy_questions")
    if not isinstance(questions, list):
        obj["answered_vacancy_questions"] = []

    return obj


# ── Cliente ────────────────────────────────────────────────────────────────────

class LlmClient:
    def __init__(self) -> None:
        self._client = httpx.Client(timeout=120)

    def evaluate_cv(
        self,
        vacancy: dict[str, Any],
        cv_text: str,
        vacancy_questions: list[dict[str, Any]] | None = None,
        tenant_screening_answers: list[dict[str, Any]] | None = None,
    ) -> tuple[LlmEvaluationPayload, str, int]:
        if settings.llm_provider != "openai":
            raise RuntimeError(f"Proveedor LLM no soportado: {settings.llm_provider}")

        prompt = PROMPT_TEMPLATE.format(
            title=vacancy["title"],
            description=vacancy["description"],
            mandatory=", ".join(vacancy.get("mandatory_requirements", [])),
            desirable=", ".join(vacancy.get("desirable_requirements", [])),
            location=vacancy.get("location_text") or "",
            schedule=vacancy.get("schedule_text") or "",
            tenant_screening_answers_json=json.dumps(
                tenant_screening_answers or [],
                ensure_ascii=False,
                indent=2,
            ),
            vacancy_questions_json=json.dumps(
                vacancy_questions or [],
                ensure_ascii=False,
                indent=2,
            ),
            cv_text=(cv_text or "")[: settings.llm_cv_char_limit],
        )

        last_error: Exception | None = None

        for attempt in range(1, settings.llm_max_retries + 1):
            if attempt > 1:
                time.sleep(min(10 * attempt, 40))

            t0 = time.perf_counter()

            try:
                resp = self._client.post(
                    settings.openai_url,
                    headers={
                        "Authorization": f"Bearer {settings.openai_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": settings.openai_model,
                        "temperature": 0,
                        "messages": [
                            {
                                "role": "system",
                                "content": "Responde únicamente JSON válido.",
                            },
                            {
                                "role": "user",
                                "content": prompt,
                            },
                        ],
                    },
                )

                latency_ms = int((time.perf_counter() - t0) * 1000)

                if resp.status_code == 429:
                    last_error = RuntimeError("Rate limit OpenAI")
                    continue

                resp.raise_for_status()

                raw = resp.json()["choices"][0]["message"]["content"]
                obj = _normalize_payload(_extract_json_object(raw))

                return LlmEvaluationPayload.model_validate(obj), raw, latency_ms

            except (
                httpx.HTTPError,
                json.JSONDecodeError,
                KeyError,
                ValidationError,
                ValueError,
            ) as exc:
                last_error = exc
                if attempt >= settings.llm_max_retries:
                    raise RuntimeError(f"LLM error: {last_error}") from exc

        raise RuntimeError(f"LLM error: {last_error}")
