import app


def test_upload_success_keyboard_buttons():
    kb = app.upload_success_keyboard()
    assert len(kb.inline_keyboard) == 4
    assert kb.inline_keyboard[0][0].text == "Добавить ещё фото для этого айдола"
    assert kb.inline_keyboard[0][0].callback_data == app.CB_UPLOAD_MORE
    assert kb.inline_keyboard[1][0].text == "Добавить для других айдолов"
    assert kb.inline_keyboard[1][0].callback_data == app.CB_UPLOAD_OTHER
    assert kb.inline_keyboard[2][0].text == "📁 В каталог фото"
    assert kb.inline_keyboard[2][0].callback_data == "menu_catalog"
    assert kb.inline_keyboard[3][0].text == "⬅️ Назад в меню"
    assert kb.inline_keyboard[3][0].callback_data == "menu_back"
