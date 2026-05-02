# app/cv_pipeline.py
import hashlib
import io
import os
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


def normalize_phone(raw: str) -> str:
    parsed = phonenumbers.parse(raw, settings.default_phone_region)
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


def extract_pdf_text(content: bytes) -> tuple[str, CvParseStatus]:
    reader = PdfReader(io.BytesIO(content))
    text = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    if len(text) >= 200:
        return text, CvParseStatus.PARSED
    images = convert_from_bytes(content, dpi=200)
    ocr_text = "\n".join(
        pytesseract.image_to_string(img, lang="spa+eng") for img in images
    ).strip()
    if ocr_text:
        return ocr_text, CvParseStatus.OCR_FALLBACK
    return "", CvParseStatus.FAILED


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
