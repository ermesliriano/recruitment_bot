from app.llm_client import _fit_document_text


def test_document_limit_preserves_last_page():
    document = "\n\n".join(
        [
            "===== PÁGINA 1 (texto PDF) =====\n" + "CV " * 2500,
            "===== PÁGINA 2 (texto PDF) =====\n" + "Experiencia " * 1200,
            "===== PÁGINA 3 (OCR) =====\nLICENCIA DE CONDUCIR CATEGORÍA 02",
        ]
    )

    fitted = _fit_document_text(document, 1800)

    assert len(fitted) <= 1800
    assert "PÁGINA 1" in fitted
    assert "PÁGINA 2" in fitted
    assert "PÁGINA 3" in fitted
    assert "LICENCIA DE CONDUCIR" in fitted


def test_plain_text_limit_preserves_tail():
    text = "A" * 2000 + "DOCUMENTO_FINAL_IMPORTANTE"

    fitted = _fit_document_text(text, 300)

    assert len(fitted) <= 300
    assert "DOCUMENTO_FINAL_IMPORTANTE" in fitted
