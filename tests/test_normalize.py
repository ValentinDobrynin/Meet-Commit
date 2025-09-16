"""Тесты для app.core.normalize.run"""

from app.core.normalize import run as normalize_run


def test_normalize_with_text():
    """Тест обработки текстового ввода."""
    text = "Встреча 25.03.2024 с Валентином и Даней. Обсудили бюджет проекта IFRS."
    result = normalize_run(raw_bytes=None, text=text, filename="test_meeting.txt")

    assert result["title"] == "test_meeting"
    assert result["date"] == "2024-03-25"
    assert "Valentin" in result["attendees"]
    assert "Daniil" in result["attendees"]
    assert result["text"] == text
    assert result["raw_hash"] is not None


def test_normalize_with_empty_input():
    """Тест обработки пустого ввода."""
    result = normalize_run(raw_bytes=None, text="", filename="")

    assert result["title"] == "Meeting"
    assert result["date"] is not None  # fallback to today
    assert result["attendees"] == []
    assert result["text"] == ""
    assert result["raw_hash"] is not None


def test_normalize_with_filename_date():
    """Тест извлечения даты из имени файла."""
    result = normalize_run(raw_bytes=None, text="", filename="2024-12-25_meeting.txt")

    assert result["title"] == "2024-12-25_meeting"
    assert result["date"] == "2024-12-25"


def test_normalize_with_pdf_bytes():
    """Тест обработки PDF файла."""
    # Создаем минимальный PDF
    pdf_bytes = b"%PDF-1.4\n1 0 obj\n<<\n/Type /Catalog\n/Pages 2 0 R\n>>\nendobj\n2 0 obj\n<<\n/Type /Pages\n/Kids [3 0 R]\n/Count 1\n>>\nendobj\n3 0 obj\n<<\n/Type /Page\n/Parent 2 0 R\n/MediaBox [0 0 612 792]\n/Contents 4 0 R\n>>\nendobj\n4 0 obj\n<<\n/Length 44\n>>\nstream\nBT\n/F1 12 Tf\n72 720 Td\n(Test PDF content) Tj\nET\nendstream\nendobj\nxref\n0 5\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n0000000204 00000 n \ntrailer\n<<\n/Size 5\n/Root 1 0 R\n>>\nstartxref\n297\n%%EOF"

    result = normalize_run(raw_bytes=pdf_bytes, text=None, filename="test.pdf")

    assert result["title"] == "test"
    assert result["text"] is not None
    assert result["raw_hash"] is not None


def test_normalize_with_docx_bytes():
    """Тест обработки DOCX файла."""
    # Используем mock для тестирования DOCX обработки
    from unittest.mock import Mock, patch

    with patch("app.core.normalize.Document") as mock_document:
        mock_doc = Mock()
        mock_paragraph = Mock()
        mock_paragraph.text = "Test DOCX content"
        mock_doc.paragraphs = [mock_paragraph]
        mock_document.return_value = mock_doc

        docx_bytes = b"fake docx content"
        result = normalize_run(raw_bytes=docx_bytes, text=None, filename="test.docx")

        assert result["title"] == "test"
        assert result["text"] == "Test DOCX content"
        assert result["raw_hash"] is not None


def test_normalize_with_vtt_bytes():
    """Тест обработки VTT файла."""
    vtt_content = """WEBVTT

00:00:01.000 --> 00:00:05.000
Встреча началась

00:00:05.000 --> 00:00:10.000
Обсудили бюджет проекта
"""
    vtt_bytes = vtt_content.encode("utf-8")

    result = normalize_run(raw_bytes=vtt_bytes, text=None, filename="test.vtt")

    assert result["title"] == "test"
    assert "Встреча началась" in result["text"]
    assert "Обсудили бюджет проекта" in result["text"]
    assert result["raw_hash"] is not None


def test_normalize_with_unknown_extension():
    """Тест обработки файла с неизвестным расширением."""
    result = normalize_run(raw_bytes=b"some content", text=None, filename="test.unknown")

    assert result["title"] == "test"  # Path(filename).stem убирает расширение
    assert result["text"] == "some content"
    assert result["raw_hash"] is not None
