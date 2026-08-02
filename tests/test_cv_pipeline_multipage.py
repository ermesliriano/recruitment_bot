from types import SimpleNamespace

from app import cv_pipeline
from app.enums import CvParseStatus


class FakePage:
    def __init__(self, text):
        self.text = text

    def extract_text(self):
        return self.text


def test_ocr_is_applied_to_sparse_later_page(monkeypatch):
    long_cv = "Experiencia profesional " * 20
    monkeypatch.setattr(
        cv_pipeline,
        "PdfReader",
        lambda _stream: SimpleNamespace(pages=[FakePage(long_cv), FakePage("")]),
    )

    calls = []

    def fake_convert(_content, **kwargs):
        calls.append(kwargs)
        return [object()]

    monkeypatch.setattr(cv_pipeline, "convert_from_bytes", fake_convert)
    monkeypatch.setattr(
        cv_pipeline.pytesseract,
        "image_to_string",
        lambda _image, lang: "LICENCIA DE CONDUCIR categoría 02",
    )

    text, status = cv_pipeline.extract_pdf_text(b"fake-pdf")

    assert status == CvParseStatus.OCR_FALLBACK
    assert "PÁGINA 1" in text
    assert "PÁGINA 2 (OCR)" in text
    assert "LICENCIA DE CONDUCIR" in text
    assert calls == [
        {
            "dpi": cv_pipeline.PDF_OCR_DPI,
            "first_page": 2,
            "last_page": 2,
        }
    ]


def test_text_pages_do_not_trigger_ocr(monkeypatch):
    monkeypatch.setattr(
        cv_pipeline,
        "PdfReader",
        lambda _stream: SimpleNamespace(
            pages=[
                FakePage("Currículum y experiencia " * 10),
                FakePage("Certificado profesional " * 10),
            ]
        ),
    )

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("No se esperaba OCR para páginas con texto suficiente")

    monkeypatch.setattr(cv_pipeline, "convert_from_bytes", fail_if_called)

    text, status = cv_pipeline.extract_pdf_text(b"fake-pdf")

    assert status == CvParseStatus.PARSED
    assert "PÁGINA 1 (texto PDF)" in text
    assert "PÁGINA 2 (texto PDF)" in text
