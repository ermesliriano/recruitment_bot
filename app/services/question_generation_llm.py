# app/services/question_generation_llm.py
from __future__ import annotations

import json
import re
import time
from typing import Any

import httpx
from fastapi import HTTPException, status
from pydantic import BaseModel, Field, ValidationError

from app.core.config import settings
from app.enums import AnswerType


# ── Modelos de validación de la respuesta del LLM ─────────────────────────────

class GeneratedQuestion(BaseModel):
    question_code: str = Field(..., max_length=80)
    prompt_text: str
    answer_type: AnswerType
    field_key: str = Field(..., max_length=120)
    question_order: int = Field(..., ge=1)
    required: bool = True
    scoring_enabled: bool = True
    max_points: int = Field(default=0, ge=0, le=100)
    validation: dict[str, Any] = Field(default_factory=dict)


class GeneratedQuestionsPayload(BaseModel):
    questions: list[GeneratedQuestion]


# ── Utilidades internas ────────────────────────────────────────────────────────

def _slugify(value: str, fallback: str) -> str:
    """Convierte una cadena en snake_case seguro para question_code y field_key."""
    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower())
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized[:90] or fallback


def _extract_json_object(content: str) -> dict[str, Any]:
    """
    Parsea JSON estricto. Si el modelo añade texto extra (markdown, comentarios),
    rescata el primer objeto JSON del contenido.
    """
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", content, flags=re.DOTALL)
    if not match:
        raise ValueError("El LLM no devolvió un objeto JSON válido.")

    return json.loads(match.group(0))


def _build_validation_for_type(answer_type: AnswerType) -> dict[str, Any]:
    """Genera valores de validación sensatos según el tipo de respuesta."""
    if answer_type == AnswerType.BOOLEAN:
        return {
            "true_values": ["si", "sí", "s", "yes", "true"],
            "false_values": ["no", "n", "false"],
        }
    if answer_type == AnswerType.NUMBER:
        return {"min": 0, "max": 100}
    return {}


def _build_prompt(
    *,
    vacancy_title: str,
    vacancy_description: str,
    mandatory_requirements: list[str],
    cv_max_score: int,
) -> list[dict[str, str]]:
    requirements_text = "\n".join(
        f"{idx + 1}. {item}" for idx, item in enumerate(mandatory_requirements)
    )
    available_points = max(0, 100 - int(cv_max_score or 0))

    system = (
        "Eres un especialista senior en selección de personal y diseño de "
        "preguntas de screening para chatbots de reclutamiento. "
        "Debes responder exclusivamente con JSON válido, sin markdown, "
        "sin backticks y sin ningún texto adicional fuera del objeto JSON."
    )

    user = f"""
Genera preguntas de screening para una vacante a partir de sus requisitos obligatorios.

Título de la vacante:
{vacancy_title}

Descripción:
{vacancy_description}

Requisitos obligatorios ({len(mandatory_requirements)} en total):
{requirements_text}

Reglas obligatorias:
- Genera exactamente UNA pregunta por cada requisito obligatorio (total: {len(mandatory_requirements)}).
- answer_type solo puede ser: "text", "boolean" o "number".
  · Usa "boolean" si el requisito puede validarse con sí/no (ej. "¿Tienes experiencia con X?").
  · Usa "number" si puede validarse con años de experiencia, nivel o cantidad numérica.
  · Usa "text" si requiere una explicación breve.
- Las preguntas deben ser claras, directas y adecuadas para un chatbot de texto.
- question_order debe empezar en 1 y ser consecutivo hasta {len(mandatory_requirements)}.
- required debe ser true en todas.
- scoring_enabled debe ser true en todas.
- La suma total de max_points de TODAS las preguntas debe ser exactamente {available_points}.
  · Si {available_points} es 0, max_points debe ser 0 en todas.
- field_key y question_code deben ser snake_case sin espacios, tildes ni caracteres especiales.
- No incluyas markdown ni backticks.
- No incluyas texto fuera del objeto JSON.

Formato de respuesta esperado:
{{
  "questions": [
    {{
      "question_code": "experiencia_fastapi",
      "prompt_text": "¿Tienes experiencia profesional con FastAPI?",
      "answer_type": "boolean",
      "field_key": "experiencia_fastapi",
      "question_order": 1,
      "required": true,
      "scoring_enabled": true,
      "max_points": 20,
      "validation": {{}}
    }}
  ]
}}
""".strip()

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


# ── Función principal pública ──────────────────────────────────────────────────

def generate_questions_from_requirements(
    *,
    vacancy_title: str,
    vacancy_description: str,
    mandatory_requirements: list[str],
    cv_max_score: int,
) -> list[GeneratedQuestion]:
    """
    Llama al LLM configurado y devuelve una lista de preguntas normalizadas.
    Aplica reintentos automáticos según `settings.llm_max_retries`.
    Lanza HTTPException en caso de error irrecuperable.
    """
    if not mandatory_requirements:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="La vacante no tiene requisitos obligatorios.",
        )

    if len(mandatory_requirements) > 10:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "TOO_MANY_MANDATORY_REQUIREMENTS",
                "message": (
                    "La generación automática solo está disponible para "
                    "vacantes con 10 requisitos obligatorios o menos."
                ),
                "count": len(mandatory_requirements),
            },
        )

    if not settings.openai_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No está configurada la API key del proveedor LLM.",
        )

    messages = _build_prompt(
        vacancy_title=vacancy_title,
        vacancy_description=vacancy_description,
        mandatory_requirements=mandatory_requirements,
        cv_max_score=cv_max_score,
    )

    headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }

    payload: dict[str, Any] = {
        "model": settings.openai_model,
        "messages": messages,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }

    last_error: Exception | None = None
    max_attempts = max(1, settings.llm_max_retries)

    for attempt in range(max_attempts):
        try:
            with httpx.Client(timeout=60) as client:
                response = client.post(
                    settings.openai_url,
                    headers=headers,
                    json=payload,
                )

            if response.status_code >= 400:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail={
                        "code": "LLM_HTTP_ERROR",
                        "message": "El proveedor LLM devolvió un error HTTP.",
                        "llm_status_code": response.status_code,
                        "llm_body": response.text[:1000],
                    },
                )

            data = response.json()
            content = data["choices"][0]["message"]["content"]

            raw = _extract_json_object(content)
            result = GeneratedQuestionsPayload.model_validate(raw)

            return _normalize_generated_questions(
                result.questions,
                mandatory_requirements=mandatory_requirements,
                cv_max_score=cv_max_score,
            )

        except HTTPException:
            raise

        except (httpx.HTTPError, KeyError, ValueError, ValidationError) as exc:
            last_error = exc
            wait = min(2 ** attempt, 8)
            if attempt < max_attempts - 1:
                time.sleep(wait)

    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail={
            "code": "LLM_GENERATION_FAILED",
            "message": (
                "No se pudieron generar preguntas válidas tras "
                f"{max_attempts} intento(s)."
            ),
            "error": str(last_error) if last_error else None,
        },
    )


# ── Normalización post-LLM ────────────────────────────────────────────────────

def _normalize_generated_questions(
    questions: list[GeneratedQuestion],
    *,
    mandatory_requirements: list[str],
    cv_max_score: int,
) -> list[GeneratedQuestion]:
    """
    Endurece la salida del LLM:
    - Fuerza una pregunta por requisito.
    - Garantiza orden consecutivo desde 1.
    - Genera codes/field_keys estables en snake_case.
    - Redistribuye los puntos de forma exacta sin depender del LLM.
    - Inyecta validaciones por tipo cuando el LLM no las aporta.
    """
    expected_count = len(mandatory_requirements)

    if len(questions) != expected_count:
        raise ValueError(
            f"El LLM generó {len(questions)} preguntas, "
            f"pero se esperaban {expected_count}."
        )

    available_points = max(0, 100 - int(cv_max_score or 0))
    base_points = available_points // expected_count if expected_count else 0
    remainder = available_points % expected_count if expected_count else 0

    normalized: list[GeneratedQuestion] = []

    for idx, question in enumerate(questions):
        fallback_key = f"req_{idx + 1}"
        source_for_key = (
            question.field_key
            or question.question_code
            or mandatory_requirements[idx]
        )
        field_key = _slugify(source_for_key, fallback_key)

        # Validación automática por tipo, usada solo si el LLM no aportó nada.
        auto_validation = _build_validation_for_type(question.answer_type)
        final_validation = question.validation if question.validation else auto_validation

        normalized.append(
            GeneratedQuestion(
                question_code=field_key[:80],
                prompt_text=question.prompt_text.strip(),
                answer_type=question.answer_type,
                field_key=field_key[:120],
                question_order=idx + 1,
                required=True,
                scoring_enabled=True,
                max_points=base_points + (1 if idx < remainder else 0),
                validation=final_validation,
            )
        )

    return normalized
