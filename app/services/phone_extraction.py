from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

import phonenumbers
from phonenumbers import PhoneNumberFormat, PhoneNumberMatcher

PHONE_CONTEXT_RE = re.compile(r"(m[oó]vil|tel[eé]fono|whatsapp|contacto|ll[aá]mame|phone|mobile)", re.I)
REJECT_CONTEXT_RE = re.compile(r"(fax|nif|nie|cif|iban|cuenta|pedido|zip|cp|postal)", re.I)


@dataclass(slots=True)
class PhoneCandidate:
    raw: str
    e164: str
    start: int
    end: int
    confidence: float
    context: str
    discard_reason: str | None = None


@dataclass(slots=True)
class PhoneExtractionResult:
    selected_phone: str | None
    candidates: list[PhoneCandidate]
    confidence: float
    status: str
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "selected_phone": self.selected_phone,
            "confidence": self.confidence,
            "status": self.status,
            "reason": self.reason,
            "candidates": [asdict(candidate) for candidate in self.candidates],
        }


def _score_candidate(*, raw: str, e164: str, context: str) -> float:
    score = 0.45

    if raw.startswith("+"):
        score += 0.10

    if PHONE_CONTEXT_RE.search(context):
        score += 0.20

    digits_count = len(re.sub(r"\D", "", raw))
    if 9 <= digits_count <= 15:
        score += 0.10

    if REJECT_CONTEXT_RE.search(context):
        score -= 0.35

    if e164.endswith(raw[-4:].replace(" ", "").replace("-", "")):
        score += 0.05

    return max(0.0, min(1.0, score))


def extract_phone_from_text(text: str, default_region: str = "ES") -> PhoneExtractionResult:
    normalized_text = text or ""
    found: dict[str, PhoneCandidate] = {}

    for match in PhoneNumberMatcher(normalized_text, default_region):
        number = match.number
        if not phonenumbers.is_valid_number(number):
            continue

        e164 = phonenumbers.format_number(number, PhoneNumberFormat.E164)
        start, end = match.start, match.end
        raw = normalized_text[start:end].strip()
        context = normalized_text[max(0, start - 30):min(len(normalized_text), end + 30)]

        confidence = _score_candidate(raw=raw, e164=e164, context=context)

        existing = found.get(e164)
        candidate = PhoneCandidate(
            raw=raw,
            e164=e164,
            start=start,
            end=end,
            confidence=confidence,
            context=context,
            discard_reason=None,
        )

        if existing is None or existing.confidence < confidence:
            found[e164] = candidate

    candidates = sorted(found.values(), key=lambda item: item.confidence, reverse=True)

    if not candidates:
        return PhoneExtractionResult(
            selected_phone=None,
            candidates=[],
            confidence=0.0,
            status="phone_not_found",
            reason="No se encontró ningún teléfono válido en el texto extraído.",
        )

    if len(candidates) == 1:
        best = candidates[0]
        return PhoneExtractionResult(
            selected_phone=best.e164,
            candidates=candidates,
            confidence=best.confidence,
            status="selected",
            reason=None,
        )

    best = candidates[0]
    second = candidates[1]

    if (best.confidence - second.confidence) < 0.15:
        return PhoneExtractionResult(
            selected_phone=None,
            candidates=candidates,
            confidence=best.confidence,
            status="ambiguous_phone",
            reason="Hay más de un teléfono plausible y la diferencia de confianza es insuficiente.",
        )

    return PhoneExtractionResult(
        selected_phone=best.e164,
        candidates=candidates,
        confidence=best.confidence,
        status="selected",
        reason=None,
    )
