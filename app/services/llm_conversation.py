# app/services/llm_conversation.py
"""
Flujo de conversacion guiado por LLM (modo alternativo al bot clasico).

Arquitectura: el LLM actua como capa de INTERPRETACION y REDACCION sobre la
maquina de estados existente, que sigue siendo la fuente de verdad:

  1. interpret(): recibe el mensaje del candidato + el contexto de lo que el
     flujo espera en el estado actual (vacantes disponibles, pregunta pendiente
     con su tipo, CV esperado...) y devuelve un JSON con:
       - intent = "provide_input": el candidato respondio; normalized_input es
         el valor ya normalizado que los handlers clasicos pueden consumir
         (numero de vacante, "si"/"no", numero, texto).
       - intent = "clarify": la respuesta fue invalida/ambigua o el candidato
         hizo una pregunta; reply es la re-pregunta natural que se le envia,
         sin avanzar de estado.
       - intent = "restart": el candidato quiere empezar de nuevo / ver vacantes.
       - intent = "passthrough": el LLM no esta seguro; se delega al flujo clasico.
  2. rewrite(): reescribe los mensajes salientes del bot clasico con un tono
     natural y cercano, preservando datos (listas numeradas, nombres, formatos).

La validacion, la persistencia de Answer y el scoring NO cambian: si el LLM
extrae un valor, este pasa por los mismos validadores del flujo clasico.

Configuracion por tenant (en tenants.settings_json, sin migracion):
  - conversation_mode: "classic" (default) | "llm"
  - llm_flow_prompt: system prompt personalizado (opcional; sustituye al default)
  - llm_flow_contract: contrato JSON personalizado (opcional, dict; se muestra
    al LLM como estructura de salida obligatoria)
  - llm_rewrite_messages: bool (default true) reescritura de mensajes salientes

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


def get_flow_settings(tenant) -> dict[str, Any]:
    raw = tenant.settings_json or {}
    return {
        "conversation_mode": raw.get("conversation_mode") or CONVERSATION_MODE_CLASSIC,
        "llm_flow_prompt": raw.get("llm_flow_prompt") or None,
        "llm_flow_contract": raw.get("llm_flow_contract") or None,
        "llm_rewrite_messages": bool(raw.get("llm_rewrite_messages", True)),
    }


def is_llm_flow_enabled(tenant) -> bool:
    return get_flow_settings(tenant)["conversation_mode"] == CONVERSATION_MODE_LLM


# ── Contrato y prompt por defecto (personalizables por tenant) ────────────────

DEFAULT_CONTRACT: dict[str, Any] = {
    "intent": "provide_input | clarify | restart | passthrough",
    "normalized_input": "string o null",
    "reply": "string o null",
}

DEFAULT_GUIDE_PROMPT = """
Eres el asistente conversacional de un proceso de seleccion por chat (WhatsApp/Telegram).
Tu funcion es interpretar el mensaje del candidato dentro del paso actual del proceso y
ayudarle con calidez cuando se equivoca, duda o pregunta algo.

Recibiras un CONTEXTO con: el paso actual, que se espera del candidato en este paso
(opciones de vacante numeradas, una pregunta con su tipo de respuesta, el envio de un CV...),
y el MENSAJE del candidato.

Devuelve EXCLUSIVAMENTE un JSON valido con esta estructura exacta:
{contract}

Reglas para decidir intent:
- "provide_input": el mensaje del candidato responde a lo que se espera. En normalized_input
  devuelve el valor normalizado:
  * Si se esperan opciones numeradas de vacante: devuelve SOLO el numero de la opcion elegida
    (ej. "1"). Solo si la eleccion es inequivoca.
  * Si la pregunta es de tipo boolean: devuelve exactamente "si" o "no".
  * Si la pregunta es de tipo number: devuelve solo el numero (ej. "3").
  * Si la pregunta es de tipo text o se espera el nombre: devuelve el texto relevante limpio
    (sin muletillas como "mi nombre es").
- "clarify": el mensaje NO responde a lo esperado (respuesta ambigua, invalida, una pregunta
  del candidato, un saludo, una queja...). En reply redacta una respuesta natural, breve y
  amable EN ESPANOL que: (1) atienda lo que dijo o pregunto el candidato si procede, y
  (2) le recuerde con claridad que se espera de el en este paso (repite las opciones o la
  pregunta pendiente). No inventes informacion sobre la empresa ni la vacante que no este
  en el contexto.
- "restart": el candidato pide explicitamente empezar de nuevo, cambiar de vacante o ver
  las vacantes otra vez.
- "passthrough": no estas seguro de como interpretar el mensaje. No fuerces una respuesta.

Reglas CRITICAS contra contenido inventado:
- PROHIBIDO inventar vacantes, opciones, listas o placeholders (nunca escribas cosas como
  "Opcion A", "Opcion B", "Vacante 1", etc.).
- Si el CONTEXTO incluye el campo "opciones", al re-preguntar en reply DEBES repetir esas
  opciones LITERALMENTE, con su numero y titulo exactos, sin anadir ni quitar ninguna.
- Si el CONTEXTO NO incluye "opciones" ni "pregunta_pendiente" y necesitarias mencionarlas
  para responder, usa intent "passthrough" en lugar de "clarify".
- reply solo puede contener informacion presente en el CONTEXTO o en el mensaje del candidato.

Reglas adicionales:
- NUNCA marques "provide_input" con una eleccion de vacante si el candidato dijo "no",
  rechazo las opciones o no eligio claramente una.
- reply siempre en espanol, maximo 500 caracteres, sin markdown.
- No añadas texto fuera del JSON.
""".strip()

DEFAULT_REWRITE_PROMPT = """
Eres el asistente conversacional de un proceso de seleccion por chat. Reescribe los mensajes
del bot para que suenen naturales, calidos y profesionales EN ESPANOL, con estas reglas:
- Conserva EXACTAMENTE los datos: listas numeradas de vacantes (mismos numeros y titulos),
  nombres, preguntas y su significado. No agregues ni quites opciones ni preguntas.
- PROHIBIDO inventar vacantes, opciones o placeholders (nunca "Opcion A", "Vacante 1", etc.).
- No inventes informacion. No cambies instrucciones (ej. "escribe /start").
- Un mensaje reescrito por cada mensaje original, mismo orden.
- Manten cada mensaje razonablemente corto (chat movil).

Devuelve EXCLUSIVAMENTE un JSON valido: {"messages": ["...", "..."]} con tantos elementos
como mensajes recibiste, en el mismo orden. Sin texto fuera del JSON.
""".strip()


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
        custom_contract: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        contract = custom_contract or DEFAULT_CONTRACT
        system = (custom_prompt or DEFAULT_GUIDE_PROMPT).replace(
            "{contract}", json.dumps(contract, ensure_ascii=False, indent=2)
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
        custom_prompt: str | None = None,
    ) -> list[dict[str, Any]]:
        """Reescribe los textos de los mensajes salientes. Los mensajes con
        reply_markup (botones) mantienen su markup; solo se toca el texto.
        Ante cualquier problema, devuelve los mensajes originales."""
        texts = [m.get("text") or "" for m in messages]
        if not any(texts):
            return messages
        user = (
            "CONTEXTO:\n"
            + json.dumps(context, ensure_ascii=False, indent=2)
            + "\n\nMENSAJES A REESCRIBIR (array JSON):\n"
            + json.dumps(texts, ensure_ascii=False, indent=2)
        )
        try:
            obj = _extract_json_object(
                self._chat(custom_prompt or DEFAULT_REWRITE_PROMPT, user)
            )
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
