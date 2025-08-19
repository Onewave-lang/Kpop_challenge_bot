# Kpop Challenge Bot

## Режим ИИ

Для использования режима игры с ИИ:

1. Установите библиотеку `openai`:
   ```bash
   pip install openai
   ```
2. Установите переменную окружения `OPENAI_API_KEY` со своим ключом OpenAI.
3. Сгенерируйте список групп:
   ```bash
   OPENAI_API_KEY=... python generate_top_kpop_groups.py
   ```
4. Поместите полученный `top50_groups.json` в ту же папку, что и `app.py`.

После этого в меню бота станет доступен пункт **AI игра**.
