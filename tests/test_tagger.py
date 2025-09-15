from app.core.tagger import run as tagger_run


def test_tagger_detects_from_text():
    text = "Обсудили IFRS и бюджет по EVM."
    tags = tagger_run(summary_md=text, meta={"title": "weekly sync"})
    # ожидаем теги из словаря синонимов
    assert "area/ifrs" in tags
    assert "project/budgets" in tags
    assert "project/evm" in tags


def test_tagger_detects_from_title():
    text = "Прошли по плану."
    tags = tagger_run(summary_md=text, meta={"title": "Бюджеты Q4"})
    assert "project/budgets" in tags
