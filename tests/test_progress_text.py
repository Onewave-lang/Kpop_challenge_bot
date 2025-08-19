import app


def test_progress_text_basic():
    g = {"score": 2, "total": 5, "index": 3}
    assert app.progress_text(g) == "Правильных ответов: 2 из 5. Осталось вопросов: 2."
