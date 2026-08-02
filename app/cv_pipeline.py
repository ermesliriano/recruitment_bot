# app/cv_pipeline.py
import hashlib
import io
import os
import re
from pathlib import Path

import phonenumbers
import pytesseract
from pdf2image import convert_from_bytes
from PIL import Image
from pypdf import PdfReader
from sqlalchemy import func, select

from app.core.config import settings
from app.core.db import SessionLocal
from app.enums import CvParseStatus, StorageBackendType
from app.models.cv import CvDocument

ALLOWED_MIME = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
}
ALLOWED_EXT = {".pdf", ".jpg", ".jpeg", ".png"}

# Un PDF puede contener un CV con capa de texto y anexos escaneados. La decisión
# de usar OCR se toma por página, no por la cantidad total de texto del archivo.
PDF_PAGE_TEXT_MIN_CHARS = 80
PDF_OCR_DPI = 200


def normalize_phone(raw: str) -> str:
    # Telegram sends phone_number without '+' but always includes the country code.
    # Prepending '+' lets phonenumbers parse any country correctly,
    # regardless of settings.default_phone_region (which would break non-ES numbers).
    e164_input = raw if raw.startswith("+") else f"+{raw}"
    parsed = phonenumbers.parse(e164_input, None)
    if not phonenumbers.is_valid_number(parsed):
        raise ValueError("Teléfono inválido")
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


class LocalFileStorage:
    def save(self, tenant_id, application_id, version, filename, content):
        root = Path(settings.storage_root) / str(tenant_id) / str(application_id)
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"v{version}_{filename}"
        path.write_bytes(content)
        return str(path), None


class DbBlobStorage:
    def save(self, tenant_id, application_id, version, filename, content):
        return f"db://cv_documents/{application_id}/v{version}/{filename}", content


def get_storage():
    if settings.storage_backend == "local_fs":
        return LocalFileStorage(), StorageBackendType.LOCAL_FS
    return DbBlobStorage(), StorageBackendType.DB_BLOB


def validate_cv(filename: str, mime_type: str, size_bytes: int) -> str:
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXT:
        raise ValueError("Formato inválido. Solo PDF/JPG/PNG")
    if size_bytes <= 0 or size_bytes > 20 * 1024 * 1024:
        raise ValueError("El CV supera 20 MB")
    return ext


def _clean_extracted_text(value: str | None) -> str:
    """Normaliza texto de PDF/OCR sin destruir saltos de línea útiles."""
    text = (value or "").replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _has_meaningful_page_text(text: str) -> bool:
    compact = re.sub(r"\s+", "", text or "")
    return len(compact) >= PDF_PAGE_TEXT_MIN_CHARS


def _ocr_pdf_page(content: bytes, page_number: int) -> str:
    """Renderiza y procesa una sola página para limitar memoria y tiempo de OCR."""
    images = convert_from_bytes(
        content,
        dpi=PDF_OCR_DPI,
        first_page=page_number,
        last_page=page_number,
    )
    if not images:
        return ""
    return _clean_extracted_text(
        pytesseract.image_to_string(images[0], lang="spa+eng")
    )


def extract_pdf_text(content: bytes) -> tuple[str, CvParseStatus]:
    """Extrae todas las páginas y aplica OCR únicamente donde haga falta.

    El comportamiento anterior decidía usar OCR según el texto TOTAL del PDF.
    Un CV de dos páginas podía superar el umbral y provocar que una licencia,
    certificado u otro anexo escaneado de páginas posteriores quedara invisible.
    """
    reader = PdfReader(io.BytesIO(content))
    sections: list[str] = []
    used_ocr = False
    found_text = False

    for index, page in enumerate(reader.pages, start=1):
        try:
            embedded_text = _clean_extracted_text(page.extract_text())
        except Exception:
            embedded_text = ""

        page_text = embedded_text
        source = "texto PDF"

        if not _has_meaningful_page_text(embedded_text):
            try:
                ocr_text = _ocr_pdf_page(content, index)
            except Exception:
                # Un fallo de OCR en una página no debe descartar el texto de las
                # demás páginas ni hacer fallar el expediente completo.
                ocr_text = ""

            if ocr_text:
                used_ocr = True
                source = "OCR"
                # Conserva cualquier fragmento de la capa de texto y añade el OCR.
                page_text = "\n".join(
                    part for part in (embedded_text, ocr_text) if part
                ).strip()
            elif embedded_text:
                source = "texto PDF parcial"

        marker = f"===== PÁGINA {index} ({source}) ====="
        if page_text:
            found_text = True
            sections.append(f"{marker}\n{page_text}")
        else:
            sections.append(f"{marker}\n[Sin texto reconocido]")

    text = "\n\n".join(sections).strip()
    if not found_text:
        return text, CvParseStatus.FAILED
    if used_ocr:
        return text, CvParseStatus.OCR_FALLBACK
    return text, CvParseStatus.PARSED


def extract_image_text(content: bytes) -> tuple[str, CvParseStatus]:
    img = Image.open(io.BytesIO(content))
    text = pytesseract.image_to_string(img, lang="spa+eng").strip()
    return (text, CvParseStatus.OCR_FALLBACK) if text else ("", CvParseStatus.FAILED)


def extract_cv_text(ext: str, content: bytes) -> tuple[str, CvParseStatus]:
    if ext == ".pdf":
        return extract_pdf_text(content)
    if ext in {".jpg", ".jpeg", ".png"}:
        return extract_image_text(content)
    return "", CvParseStatus.UNSUPPORTED


def next_cv_version(db, application_id) -> int:
    current = db.execute(
        select(func.max(CvDocument.version)).where(CvDocument.application_id == application_id)
    ).scalar_one()
    return 1 if current is None else int(current) + 1


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()
