# app/llm_client.py
import json
import re
import time
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.core.config import settings


# Límite de caracteres para todos los campos de texto libre devueltos por el LLM.
# Se aplica como instrucción en el prompt y, de forma defensiva, al validar el payload.
MAX_FREE_TEXT_CHARS = 200
PAGE_MARKER_RE = re.compile(r"(?=^===== PÁGINA \d+ \([^)]+\) =====$)", re.MULTILINE)
TRUNCATION_MARKER = "\n...[CONTENIDO INTERMEDIO RECORTADO POR LÍMITE]...\n"


def _clip_preserving_edges(text: str, limit: int) -> str:
    """Recorta conservando principio y final para no perder anexos o pies de página."""
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    if limit <= len(TRUNCATION_MARKER) + 20:
        return text[:limit]

    available = limit - len(TRUNCATION_MARKER)
    head_len = int(available * 0.65)
    tail_len = available - head_len
    return text[:head_len] + TRUNCATION_MARKER + text[-tail_len:]


def _fit_document_text(value: str | None, char_limit: int) -> str:
    """Ajusta el expediente al límite garantizando representación de cada página.

    El recorte anterior tomaba únicamente el principio del PDF y podía excluir
    licencias o certificados situados al final. Cuando existen marcadores de
    página, el presupuesto se reparte entre todas las páginas y se redistribuye
    el espacio que dejan libre las páginas cortas.
    """
    text = (value or "").strip()
    if not text or char_limit <= 0:
        return ""
    if len(text) <= char_limit:
        return text

    blocks = [block.strip() for block in PAGE_MARKER_RE.split(text) if block.strip()]
    if len(blocks) <= 1:
        return _clip_preserving_edges(text, char_limit)

    separator = "\n\n"
    content_budget = char_limit - len(separator) * (len(blocks) - 1)
    if content_budget <= 0:
        return _clip_preserving_edges(text, char_limit)

    allocations = [0] * len(blocks)
    remaining = set(range(len(blocks)))
    remaining_budget = content_budget

    while remaining:
        share = remaining_budget // len(remaining)
        completed = {i for i in remaining if len(blocks[i]) <= share}
        if not completed:
            ordered = sorted(remaining)
            for i in ordered:
                allocations[i] = share
            for i in ordered[: remaining_budget - share * len(ordered)]:
                allocations[i] += 1
            break

        for i in completed:
            allocations[i] = len(blocks[i])
            remaining_budget -= allocations[i]
        remaining -= completed

    fitted = separator.join(
        _clip_preserving_edges(block, allocations[i])
        for i, block in enumerate(blocks)
    )
    return fitted[:char_limit]


def _clip_text(value: Any) -> str | None:
    """Recorta un campo de texto libre a MAX_FREE_TEXT_CHARS. Devuelve None si queda vacío."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:MAX_FREE_TEXT_CHARS]


def _clip_str_list(value: Any) -> list[str]:
    """Normaliza una lista de strings: aplana dicts, descarta vacíos y recorta a 200 chars."""
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, dict):
            item = " - ".join(str(v) for v in item.values() if v)
        text = str(item).strip()
        if text:
            out.append(text[:MAX_FREE_TEXT_CHARS])
    return out


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

    # Campos cualitativos añadidos al análisis.
    missing_evidence: list[str] = Field(default_factory=list)
    fit_gaps: list[str] = Field(default_factory=list)
    follow_up_questions: list[str] = Field(default_factory=list)
    document_inventory: list[str] = Field(default_factory=list)

    cv_score_0_10: float = Field(ge=0, le=10)
    recommendation: str

    # Textos cualitativos (cada uno limitado a 200 caracteres).
    recommended_next_action: str | None = None
    human_readable_summary: str | None = None
    qualitative_assessment: str | None = None
    score_rationale: str | None = None

    # Nombre completo del candidato extraído del CV (o null si no aparece).
    candidate_full_name: str | None = None

    # Preguntas de la vacante que el LLM ha podido responder desde el CV.
    answered_vacancy_questions: list[CvInferredAnswer] = Field(default_factory=list)

    model_config = ConfigDict(extra="ignore")

    @field_validator(
        "experience_summary",
        "skills",
        "red_flags",
        "missing_evidence",
        "fit_gaps",
        "follow_up_questions",
        "document_inventory",
        mode="before",
    )
    @classmethod
    def _clip_lists(cls, value: Any) -> list[str]:
        return _clip_str_list(value)

    @field_validator(
        "recommended_next_action",
        "human_readable_summary",
        "qualitative_assessment",
        "score_rationale",
        mode="before",
    )
    @classmethod
    def _clip_texts(cls, value: Any) -> str | None:
        return _clip_text(value)


# ── Prompt ─────────────────────────────────────────────────────────────────────

PROMPT_TEMPLATE = """
Eres un evaluador técnico de expedientes documentales para procesos de reclutamiento. Tu función es analizar la compatibilidad del candidato con una vacante específica, diferenciando claramente entre información evidenciada en los documentos, información declarada por el candidato, información no evidenciada y brechas reales frente al perfil requerido.

El archivo recibido puede contener un CV y, en páginas posteriores, documentos complementarios no previstos inicialmente: licencia de conducir, cédula, certificados, títulos, cartas u otras evidencias. Debes revisar TODAS las páginas y tratar los anexos como parte del expediente del candidato.

Analiza el expediente documental completo en relación con la vacante indicada.

Además de evaluar el perfil de forma general, debes revisar si cualquier página del expediente contiene información suficiente para responder cada pregunta específica asociada a la vacante. Solo responde una pregunta si existe evidencia clara en el conjunto de documentos; si no la hay, márcala como no respondida.

También recibirás, si existen, respuestas genéricas del candidato a preguntas globales del tenant. Debes incorporarlas al análisis general del perfil y hacer que influyan en cv_score_0_10.

Devuelve EXCLUSIVAMENTE JSON válido con esta estructura exacta:

{{
  "candidate_profile": {{}},
  "experience_summary": [],
  "skills": [],
  "red_flags": [],
  "missing_evidence": [],
  "fit_gaps": [],
  "cv_score_0_10": 0,
  "recommendation": "",
  "recommended_next_action": "",
  "human_readable_summary": "",
  "qualitative_assessment": "",
  "score_rationale": "",
  "candidate_full_name": null,
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
  ],
  "follow_up_questions": [],
  "document_inventory": []
}}

Reglas generales:
- cv_score_0_10 debe ser un número entre 0 y 10.
- recommendation debe ser exactamente uno de: "muy_idoneo", "idoneo", "revisar" o "no_idoneo".
- candidate_full_name debe ser el nombre y apellidos del candidato tal como aparecen en el expediente, o null si no puede determinarse con seguridad.
- No añadas markdown, backticks ni texto fuera del JSON.
- LÍMITE DE LONGITUD: todos los campos de texto libre (recommended_next_action, human_readable_summary, qualitative_assessment, score_rationale y cada elemento de experience_summary, skills, red_flags, missing_evidence, fit_gaps, follow_up_questions y document_inventory) NO pueden superar los 200 caracteres. Si necesitas resumir, hazlo para respetar ese límite.
- document_inventory debe enumerar brevemente los tipos de documentos detectados e indicar la página cuando sea posible, por ejemplo: "Página 4: licencia de conducir".
- Antes de afirmar que falta una licencia, certificado, identificación u otra evidencia, verifica todas las páginas y document_inventory.
- Una licencia de conducir visible en un anexo constituye evidencia directa de que el candidato aportó una licencia. No afirmes que no hay información sobre ella.
- No deduzcas categoría, vigencia, restricciones o autenticidad de una licencia salvo que esos datos sean legibles.
- Los marcadores "PÁGINA N" forman parte del expediente y sirven para citar la procedencia de la evidencia.

Definición de recommendation:
- "muy_idoneo": el expediente evidencia ajuste alto con la vacante y cumple la mayoría de requisitos obligatorios y deseables.
- "idoneo": el expediente evidencia buen ajuste con la vacante, aunque puede tener algunos puntos pendientes de validación.
- "revisar": el expediente muestra señales relevantes para la vacante, pero faltan datos críticos que deben validarse en entrevista o conversación.
- "no_idoneo": el expediente no muestra relación suficiente con la vacante o presenta brechas muy marcadas frente al perfil requerido.

Guía para cv_score_0_10:
- 9 a 10: perfil muy idóneo; evidencia directa de experiencia relevante y cumplimiento fuerte de requisitos.
- 7 a 8.9: perfil idóneo; cumple varios criterios relevantes, aunque puede requerir validaciones puntuales.
- 4 a 6.9: perfil a revisar; existen señales relevantes, pero faltan evidencias críticas que deben validarse.
- 0 a 3.9: perfil no idóneo; baja relación con la vacante o brechas significativas.

Reglas sobre respuestas genéricas del candidato:
- Considéralas declaraciones explícitas del candidato.
- Úsalas para enriquecer candidate_profile, experience_summary, red_flags, missing_evidence, fit_gaps y cv_score_0_10.
- Si alguna respuesta contradice el expediente, prioriza la respuesta explícita del candidato y registra la inconsistencia en red_flags.
- Cuando una respuesta genérica del candidato complemente el expediente, úsala como declaración explícita, pero diferencia su origen dentro del análisis.
- No las devuelvas dentro de answered_vacancy_questions.
- Si la información proviene de una respuesta del candidato y no de los documentos, no debe marcarse como respondida dentro de answered_vacancy_questions, salvo que también esté evidenciada directamente en alguna página del expediente.

Diferencia entre red_flags, missing_evidence y fit_gaps:

- red_flags: alertas negativas reales, tales como contradicciones, información inconsistente, datos dudosos, experiencia incompatible o elementos que puedan representar riesgo para el proceso.
- missing_evidence: información importante para la vacante que no aparece en ninguna página del expediente ni en las respuestas genéricas del candidato.
- fit_gaps: brechas reales entre el perfil del candidato y los requisitos de la vacante.
- No incluyas como red_flag una información simplemente no evidenciada.
- Antes de añadir un elemento a missing_evidence, comprueba todas las páginas y los anexos del expediente.

Reglas para answered_vacancy_questions:
- Debes devolver UNA entrada por cada pregunta recibida en "Preguntas asociadas a la vacante".
- is_answered_in_cv=true si cualquier página del expediente contiene evidencia clara y directa; el nombre del campo se conserva por compatibilidad.
- Si no hay evidencia suficiente, usa is_answered_in_cv=false, normalized_answer=null, evidence=null y confidence=0.
- confidence debe estar entre 0 y 1.
- Para answer_type="boolean", normalized_answer debe ser "sí" o "no".
- Para answer_type="number", normalized_answer debe ser únicamente un número en texto.
- Para answer_type="text", normalized_answer debe ser una respuesta breve y fiel al expediente.
- No inventes información.
- La evidencia debe ser un fragmento breve o resumen del documento que justifique la respuesta e indicar la página cuando sea posible.

Reglas para follow_up_questions:

- Genera preguntas de seguimiento cuando existan requisitos importantes no evidenciados en ninguna página del expediente.
- Las preguntas deben ser breves, directas y útiles para completar la evaluación.
- No preguntes información que ya esté claramente respondida en el CV o en un documento complementario.
- Prioriza preguntas relacionadas con requisitos obligatorios, disponibilidad, ubicación, experiencia específica, herramientas, movilidad, salario, horario o modalidad de trabajo.
- Si no hacen falta preguntas adicionales, devuelve un arreglo vacío.

Reglas para human_readable_summary, qualitative_assessment y score_rationale:

- human_readable_summary debe ser un resumen ejecutivo de una o dos frases.
- qualitative_assessment debe ser un párrafo claro, profesional y humano que explique el ajuste general del candidato frente a la vacante.
- score_rationale debe explicar por qué se asignó el puntaje, mencionando fortalezas, anexos relevantes, brechas, información no evidenciada y elementos que influyeron en la recomendación.
- No inventes logros, experiencia ni competencias.
- Si el perfil tiene potencial pero no cumple completamente, indícalo de forma objetiva.
- Recuerda el límite de 200 caracteres por campo de texto libre.

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

EXPEDIENTE DOCUMENTAL COMPLETO DEL CANDIDATO:
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

    # Garantiza que las listas cualitativas siempre sean listas.
    for list_field in (
        "answered_vacancy_questions",
        "missing_evidence",
        "fit_gaps",
        "follow_up_questions",
        "document_inventory",
    ):
        if not isinstance(obj.get(list_field), list):
            obj[list_field] = []

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
            cv_text=_fit_document_text(cv_text, settings.llm_cv_char_limit),
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
