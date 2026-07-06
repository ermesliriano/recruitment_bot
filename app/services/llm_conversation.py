# app/services/llm_conversation.py
"""
Flujo de conversacion guiado por LLM (modo alternativo al bot clasico).

Arquitectura: el LLM actua como capa de INTERPRETACION y REDACCION sobre la
maquina de estados existente, que sigue siendo la fuente de verdad. La
validacion, la persistencia de Answer y el scoring NO cambian.

El system prompt se compone de TRES bloques configurables por tenant:
  1. Prompt de la personalidad (quien es la asistente y como se comporta)
  2. Prompt del guia conversacional (como interpretar y el contrato JSON)
  3. Informacion institucional (datos de la empresa, inyectados en el CONTEXTO)

Configuracion por tenant (en tenants.settings_json, sin migracion):
  - conversation_mode: "classic" (default) | "llm"
  - llm_flow_prompt: prompt del guia personalizado (None = default)
  - llm_personality_prompt: prompt de personalidad personalizado (None = default)
  - institutional_info: dict con los datos de la empresa (None = sin datos)
  - llm_flow_contract: contrato JSON personalizado (None = default)
  - llm_rewrite_messages: bool (default true) reescritura de mensajes salientes

Los defaults viven aqui y se exponen por API para que el frontend los muestre
y los administradores puedan editarlos, ampliarlos o recortarlos.

Cualquier error del LLM degrada silenciosamente al flujo clasico.
"""
from __future__ import annotations

import json
import re
from typing import Any

import httpx

from app.core.config import settings

# ── Configuracion por tenant ───────────────────────────────────────────────────

CONVERSATION_MODE_CLASSIC = "classic"
CONVERSATION_MODE_LLM = "llm"

# Campos admitidos en la informacion institucional del tenant.
INSTITUTIONAL_INFO_FIELDS = (
    "name",
    "description",
    "industry",
    "location",
    "website",
    "instagram",
    "facebook",
    "linkedin",
    "email",
    "phone",
)


def get_flow_settings(tenant) -> dict[str, Any]:
    raw = tenant.settings_json or {}
    return {
        "conversation_mode": raw.get("conversation_mode") or CONVERSATION_MODE_CLASSIC,
        "llm_flow_prompt": raw.get("llm_flow_prompt") or None,
        "llm_personality_prompt": raw.get("llm_personality_prompt") or None,
        "institutional_info": raw.get("institutional_info") or None,
        "llm_flow_contract": raw.get("llm_flow_contract") or None,
        "llm_rewrite_messages": bool(raw.get("llm_rewrite_messages", True)),
    }


def is_llm_flow_enabled(tenant) -> bool:
    return get_flow_settings(tenant)["conversation_mode"] == CONVERSATION_MODE_LLM


def institutional_company_context(tenant) -> dict[str, Any] | None:
    """Datos institucionales no vacios del tenant, para inyectar en el CONTEXTO."""
    info = get_flow_settings(tenant)["institutional_info"] or {}
    company = {
        key: str(info[key]).strip()
        for key in INSTITUTIONAL_INFO_FIELDS
        if info.get(key) and str(info[key]).strip()
    }
    return company or None


# ── Bloques por defecto (personalizables por tenant) ───────────────────────────

DEFAULT_CONTRACT: dict[str, Any] = {
    "intent": "provide_input | clarify | restart | passthrough",
    "normalized_input": "string o null",
    "reply": "string o null",
}

DEFAULT_PERSONALITY_PROMPT = """
Eres María, la Asistente Virtual de Reclutamiento.
Representas al departamento de Recursos Humanos de la empresa que está realizando el proceso de selección.
Tu función es acompañar a cada candidato durante su postulación, brindando una experiencia clara, profesional y cercana.
Tu personalidad debe transmitir:
• Profesionalismo.
• Empatía.
• Objetividad.
• Organización.
• Respeto.
• Agilidad.
Nunca debes sonar como un formulario automático.
Habla de forma natural, breve y cordial.
Siempre procura que el candidato complete exitosamente el proceso.
No debates.
No juzgas respuestas.
No haces bromas.
No utilizas sarcasmo.
No prometes contrataciones.
No prometes entrevistas.
No prometes salarios.
No haces evaluaciones del candidato.
No inventas información.
Cuando el candidato haga preguntas sobre la empresa o la vacante, responde únicamente utilizando la información recibida en el CONTEXTO.
Si la información no existe en el contexto, indica amablemente que el equipo de Recursos Humanos podrá ampliarla durante el proceso.
Cada respuesta debe ayudar al candidato a avanzar hacia el siguiente paso.
Nunca pierdas de vista que tu objetivo principal es completar correctamente la postulación.
""".strip()

DEFAULT_GUIDE_PROMPT = """
Eres el motor de interpretación conversacional de María, la Asistente Virtual de Reclutamiento.
Recibirás:
1. CONTEXTO
2. MENSAJE DEL CANDIDATO
El CONTEXTO contiene toda la información necesaria para interpretar el mensaje, incluyendo:
• Empresa
• Vacante
• Paso actual
• Tipo de respuesta esperada
• Pregunta pendiente
• Variables dinámicas
• Historial necesario
Devuelve EXCLUSIVAMENTE un JSON válido con esta estructura:
{contract}
==============================
FILOSOFÍA
==============================
Tu prioridad es mantener el flujo del proceso.
Antes de solicitar aclaraciones intenta interpretar correctamente la intención del candidato.
Si la respuesta puede normalizarse de forma segura, continúa.
Solicita aclaraciones únicamente cuando exista una ambigüedad real.
No hagas repetir información que ya pueda extraerse del mensaje.
==============================
INTENT
==============================
provide_input
Cuando el candidato respondió correctamente.
Normaliza:
Vacantes
Devuelve únicamente el número.
Boolean
Devuelve exactamente:
"si"
o
"no"
Acepta expresiones equivalentes.
Number
Extrae únicamente el número.
Ejemplos:
"unos cinco"
↓
5
"aproximadamente 4"
↓
4
"ganaba RD$35,000"
↓
35000
Text
Elimina frases como:
Mi nombre es
Soy
Me llamo
Quisiera indicar
y devuelve únicamente el dato.
==============================
clarify
Utilízalo cuando:
• exista ambigüedad
• el candidato haga una pregunta
• exista un saludo
• falte información
• el formato sea incompatible
En reply:
1 Responde la duda si el contexto contiene la respuesta.
2 Si no existe la información, indícalo.
3 Recuerda cuál es el paso pendiente.
4 Invita a continuar.
==============================
restart
Cuando solicite EXPLÍCITAMENTE:
• reiniciar
• cambiar vacante
• volver al inicio
• ver vacantes nuevamente
Los mensajes de cortesía o despedida (gracias, ok, listo, perfecto, buen día) NUNCA son restart:
respóndelos con clarify mediante una despedida breve y amable, sin reiniciar nada.
==============================
passthrough
Cuando no exista suficiente información para interpretar correctamente el mensaje.
==============================
EMPRESA Y VACANTE
==============================
El CONTEXTO puede contener información dinámica sobre:
• empresa
• vacante
• salario
• horario
• modalidad
• beneficios
• ubicación
• fecha de inicio
• funciones
• redes sociales
• página web
Puedes responder preguntas relacionadas únicamente utilizando dicha información.
Nunca inventes información.
Si el dato no existe en el CONTEXTO, responde indicando que el equipo de Recursos Humanos podrá ampliarlo durante el proceso.
==============================
REGLAS
==============================
Nunca inventes información.
Nunca cambies datos del contexto.
Nunca completes datos faltantes.
Nunca inventes vacantes, opciones ni placeholders (nunca "Opción A", "Vacante 1", etc.).
Si el CONTEXTO incluye "opciones", al re-preguntar repítelas literalmente, con su número y título exactos.
Si el CONTEXTO no incluye "opciones" ni "pregunta_pendiente" y necesitarías mencionarlas, usa passthrough.
No respondas fuera del JSON.
reply:
• español
• máximo 500 caracteres
• sin Markdown
• natural
• profesional
""".strip()

# Plantilla de referencia de la informacion institucional (se muestra en el
# frontend como guia de los campos disponibles).
INSTITUTIONAL_INFO_TEMPLATE: dict[str, Any] = {
    "company": {
        "name": "@COMPANY_NAME",
        "description": "@COMPANY_DESCRIPTION",
        "industry": "@COMPANY_INDUSTRY",
        "location": "@COMPANY_LOCATION",
        "website": "@COMPANY_WEBSITE",
        "instagram": "@COMPANY_INSTAGRAM",
        "facebook": "@COMPANY_FACEBOOK",
        "linkedin": "@COMPANY_LINKEDIN",
        "email": "@COMPANY_EMAIL",
        "phone": "@COMPANY_PHONE",
    }
}

DEFAULT_REWRITE_PROMPT = """
Reescribe los mensajes del bot para que suenen naturales, calidos y profesionales EN ESPANOL, con estas reglas:
- Conserva EXACTAMENTE los datos: listas numeradas de vacantes (mismos numeros y titulos),
  nombres, preguntas y su significado. No agregues ni quites opciones ni preguntas.
- PROHIBIDO inventar vacantes, opciones o placeholders (nunca "Opcion A", "Vacante 1", etc.).
- No inventes informacion. No cambies instrucciones (ej. "escribe empezar").
- Un mensaje reescrito por cada mensaje original, mismo orden.
- Manten cada mensaje razonablemente corto (chat movil).

Devuelve EXCLUSIVAMENTE un JSON valido: {"messages": ["...", "..."]} con tantos elementos
como mensajes recibiste, en el mismo orden. Sin texto fuera del JSON.
""".strip()


def compose_system_prompt(
    *,
    personality: str | None,
    guide: str | None,
    contract: dict[str, Any] | None,
) -> str:
    """Compone el system prompt: personalidad + guia (con el contrato inyectado)."""
    personality_text = (personality or DEFAULT_PERSONALITY_PROMPT).strip()
    guide_text = (guide or DEFAULT_GUIDE_PROMPT).replace(
        "{contract}", json.dumps(contract or DEFAULT_CONTRACT, ensure_ascii=False, indent=2)
    )
    return personality_text + "\n\n" + guide_text


# ── Cliente ────────────────────────────────────────────────────────────────────

def _extract_json_object(raw: str) -> dict[str, Any]:
    raw = (raw or "").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", raw, flags=re.S)
    if not match:
        raise ValueError("No se encontro JSON en la respuesta del LLM")
    return json.loads(match.group(0))


class LlmConversationGuide:
    """Interprete y redactor conversacional. Los fallos degradan a passthrough."""

    def __init__(self) -> None:
        self._client = httpx.Client(timeout=30)

    def _chat(self, system: str, user: str) -> str:
        if settings.llm_provider != "openai":
            raise RuntimeError(f"Proveedor LLM no soportado: {settings.llm_provider}")
        resp = self._client.post(
            settings.openai_url,
            headers={
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": settings.openai_model,
                "temperature": 0.3,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    # ── Interpretacion del mensaje entrante ───────────────────────────────────

    def interpret(
        self,
        *,
        context: dict[str, Any],
        user_text: str,
        custom_prompt: str | None = None,
        custom_personality: str | None = None,
        custom_contract: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        system = compose_system_prompt(
            personality=custom_personality,
            guide=custom_prompt,
            contract=custom_contract,
        )
        user = (
            "CONTEXTO:\n"
            + json.dumps(context, ensure_ascii=False, indent=2)
            + "\n\nMENSAJE DEL CANDIDATO:\n"
            + (user_text or "")
        )
        try:
            obj = _extract_json_object(self._chat(system, user))
        except Exception:
            return {"intent": "passthrough", "normalized_input": None, "reply": None}

        intent = str(obj.get("intent") or "").strip().lower()
        if intent not in {"provide_input", "clarify", "restart", "passthrough"}:
            intent = "passthrough"

        normalized = obj.get("normalized_input")
        normalized = str(normalized).strip() if normalized not in (None, "") else None

        reply = obj.get("reply")
        reply = str(reply).strip()[:500] if reply not in (None, "") else None

        if intent == "provide_input" and not normalized:
            intent = "passthrough"
        if intent == "clarify" and not reply:
            intent = "passthrough"

        return {"intent": intent, "normalized_input": normalized, "reply": reply}

    # ── Reescritura de mensajes salientes ─────────────────────────────────────

    def rewrite(
        self,
        *,
        messages: list[dict[str, Any]],
        context: dict[str, Any],
        custom_personality: str | None = None,
    ) -> list[dict[str, Any]]:
        """Reescribe los textos de los mensajes salientes con la personalidad del
        tenant. Ante cualquier problema, devuelve los mensajes originales."""
        texts = [m.get("text") or "" for m in messages]
        if not any(texts):
            return messages
        system = (
            (custom_personality or DEFAULT_PERSONALITY_PROMPT).strip()
            + "\n\n"
            + DEFAULT_REWRITE_PROMPT
        )
        user = (
            "CONTEXTO:\n"
            + json.dumps(context, ensure_ascii=False, indent=2)
            + "\n\nMENSAJES A REESCRIBIR (array JSON):\n"
            + json.dumps(texts, ensure_ascii=False, indent=2)
        )
        try:
            obj = _extract_json_object(self._chat(system, user))
            rewritten = obj.get("messages")
            if not isinstance(rewritten, list) or len(rewritten) != len(messages):
                return messages
            out: list[dict[str, Any]] = []
            for original, new_text in zip(messages, rewritten):
                text = str(new_text).strip() if new_text not in (None, "") else ""
                out.append({**original, "text": text or original.get("text")})
            return out
        except Exception:
            return messages
