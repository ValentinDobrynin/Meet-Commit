import pytest
from app.core.llm_summarize import _merge_prompt


def test_merge_prompt_with_extra_placeholder():
    """Тест замены плейсхолдера {EXTRA}"""
    base = "Сделай краткое саммари встречи. {EXTRA}"
    extra = "Обрати внимание на решения"
    result = _merge_prompt(base, extra)
    expected = "Сделай краткое саммари встречи. Обрати внимание на решения"
    assert result == expected


def test_merge_prompt_without_extra_placeholder():
    """Тест добавления дополнительных указаний без плейсхолдера"""
    base = "Сделай краткое саммари встречи."
    extra = "Обрати внимание на решения"
    result = _merge_prompt(base, extra)
    expected = "Сделай краткое саммари встречи.\n\nДоп. указания:\nОбрати внимание на решения"
    assert result == expected


def test_merge_prompt_no_extra():
    """Тест без дополнительного промпта"""
    base = "Сделай краткое саммари встречи."
    extra = None
    result = _merge_prompt(base, extra)
    assert result == base


def test_merge_prompt_empty_extra():
    """Тест с пустым дополнительным промптом"""
    base = "Сделай краткое саммари встречи."
    extra = ""
    result = _merge_prompt(base, extra)
    assert result == base


def test_merge_prompt_whitespace_extra():
    """Тест с дополнительным промптом из пробелов"""
    base = "Сделай краткое саммари встречи."
    extra = "   \n  \t  "
    result = _merge_prompt(base, extra)
    assert result == base


def test_merge_prompt_multiple_extra_placeholders():
    """Тест с несколькими плейсхолдерами {EXTRA}"""
    base = "Сделай саммари. {EXTRA} И еще {EXTRA}"
    extra = "важно"
    result = _merge_prompt(base, extra)
    expected = "Сделай саммари. важно И еще важно"
    assert result == expected
