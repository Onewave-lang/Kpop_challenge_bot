import os
import random
from contextlib import asynccontextmanager
from http import HTTPStatus
from typing import Dict, List, Optional

from fastapi import FastAPI, Request, Response

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# =======================
#  ДАННЫЕ
# =======================

kpop_groups: Dict[str, List[str]] = {
    "twice": ["Momo", "Jihyo", "Nayeon", "Sana", "Dahyun", "Jeongyeon", "Mina", "Chaeyoung", "Tzuyu"],
    "illit": ["Yunah", "Minju", "Wonhee", "Moka", "Iroha"],
    "i-dle": ["Soyeon", "Minnie", "Miyeon", "Shuhua", "Yuqi"],
    "all day project": ["Youngseo", "Annie", "Bailey", "Tarzzan", "Woochan"],
    "le sserafim": ["Chaewon", "Sakura", "Kazuha", "Eunchae", "Yunjin"],
    "katseye": ["Lara", "Megan", "Sophia", "Yoonchae", "Manon", "Daniela"],
    "itzy": ["Yeji", "Ryujin", "Chaeryeong", "Lia", "Yuna"],
    "red velvet": ["Joy", "Seulgi", "Yeri", "Irene", "Wendy"],
    "njz": ["Minji", "Hanni", "Danielle", "Haerin", "Hyein"],
    "blackpink": ["Lisa", "Jisoo", "Jennie", "Rose"],
    "aespa": ["Giselle", "Winter", "Ningning", "Karina"],
    "baby monster": ["Ruka", "Pharita", "Chiquita", "Rami", "Asa", "Ahyeon", "Rora"],
    "kiss of life": ["Natty", "Julie", "Haneul", "Belle"],
}

correct_grnames: Dict[str, str] = {
    "twice": "Twice",
    "illit": "ILLIT",
    "i-dle": "I-dle",
    "all day project": "All Day Project",
    "le sserafim": "Le Sserafim",
    "katseye": "Katseye",
    "itzy": "Itzy",
    "red velvet": "Red Velvet",
    "njz": "NJZ",
    "blackpink": "BLACKPINK",
    "aespa": "Aespa",
    "baby monster": "Baby Monster",
    "kiss of life": "Kiss of Life",
}

# Быстрые словари для сопоставления "красивого" названия -> ключ группы
PRETTY_TO_KEY: Dict[str, str] = {v.lower(): k for k, v in correct_grnames.items()}

# =======================
#  УТИЛИТЫ
# =======================

def dictionary_to_list(dictionary: Dict[str, List[str]]) -> List[str]:
    all_values: List[str] = []
    for _k, value in dictionary.items():
        all_values.extend(value)
    return all_values

def norm_group_key(s: str) -> str:
    return s.strip().lower()

def menu_keyboard() -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton("1. Угадай группу", callback_data="menu_play")],
        [InlineKeyboardButton("2. Показать все группы", callback_data="menu_show_all")],
        [InlineKeyboardButton("3. Найти участника", callback_data="menu_find_member")],
    ]
    return InlineKeyboardMarkup(kb)

def back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад в меню", callback_data="menu_back")]])

def in_game_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🏁 Прервать игру", callback_data="menu_back")]])

# =======================
#  СОСТОЯНИЕ ПОЛЬЗОВАТЕЛЯ
# =======================
# user_data схема:
# {
#   "mode": "idle" | "find" | "game",
#   "game": {
#       "members": list[str],
#       "index": int,
#       "score": int,
#       "current_member": str | None
#   }
# }

def reset_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.clear()
    context.user_data["mode"] = "idle"

def start_game(context: ContextTypes.DEFAULT_TYPE) -> None:
    all_members = dictionary_to_list(kpop_groups)
    random_members = random.sample(all_members, 10)
    context.user_data["mode"] = "game"
    context.user_data["game"] = {
        "members": random_members,
        "index": 0,
        "score": 0,
        "current_member": None,
    }

def next_question(context: ContextTypes.DEFAULT_TYPE) -> Optional[str]:
    g = context.user_data.get("game", {})
    idx: int = g.get("index", 0)
    members: List[str] = g.get("members", [])
    if idx >= 10:
        return None
    member = members[idx]
    g["current_member"] = member
    context.user_data["game"] = g
    return member

def finish_text(context: ContextTypes.DEFAULT_TYPE) -> str:
    g = context.user_data.get("game", {})
    score = g.get("score", 0)
    return f"Игра окончена! Ты угадал {score} из 10."

# =======================
#  ХЕНДЛЕРЫ PTB
# =======================

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    reset_state(context)
    await update.message.reply_text(
        "Добро пожаловать в K-pop игру!! Выбери действие:",
        reply_markup=menu_keyboard(),
    )

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "menu_back":
        reset_state(context)
        await query.edit_message_text("Меню:", reply_markup=menu_keyboard())
        return

    if data == "menu_play":
        start_game(context)
        member = next_question(context)
        if member is None:
            await query.edit_message_text(finish_text(context), reply_markup=back_keyboard())
            return
        await query.edit_message_text(
            f"К какой группе относится: {member}?\n\n"
            "Напиши название группы.",
            reply_markup=in_game_keyboard(),
            parse_mode="Markdown",
        )
        return

    if data == "menu_show_all":
        lines = []
        for key, members in kpop_groups.items():
            line = f"*{correct_grnames[key]}*: {', '.join(members)}"
            lines.append(line)
        text = "Все группы:\n\n" + "\n".join(lines)
        # 4096 — лимит Telegram на длину текста, но мы сильно меньше
        await query.edit_message_text(text, reply_markup=back_keyboard(),parse_mode="Markdown")
        return

    if data == "menu_find_member":
        context.user_data["mode"] = "find"
        await query.edit_message_text(
            "Введите имя участника k-pop группы:",
            reply_markup=back_keyboard(),
            parse_mode="Markdown",
        )
        return

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    mode = context.user_data.get("mode", "idle")
    text = (update.message.text or "").strip()

    if mode == "find":
        member = text.title()
        for group_key, members in kpop_groups.items():
            if member in members:
                await update.message.reply_text(
                    f"{member} — участник группы *{correct_grnames[group_key]}*",
                    reply_markup=back_keyboard(),
                    parse_mode="Markdown"
                )
                break
        else:
            await update.message.reply_text("Такой участник не найден", reply_markup=back_keyboard())
        return

    if mode == "game":
        g = context.user_data.get("game", {})
        member = g.get("current_member")
        if member is None:
            member = next_question(context)
            if member is None:
                await update.message.reply_text(finish_text(context), reply_markup=back_keyboard())
                reset_state(context)
                return
            await update.message.reply_text(
                f"К какой группе относится: {member}?",
                reply_markup=in_game_keyboard(),
            )
            return

        # Допускаем 2 формы ввода: ключ ("twice") или красивое имя ("Blackpink")
        answer_key = norm_group_key(text)
        is_correct = False

        if answer_key in kpop_groups and member in kpop_groups[answer_key]:
            is_correct = True
        else:
            mapped_key = PRETTY_TO_KEY.get(answer_key)  # например, "blackpink" -> "blackpink"
            if mapped_key and member in kpop_groups[mapped_key]:
                is_correct = True

        feedback = "Верно!" if is_correct else "Неверно!"
        if is_correct:
            g["score"] = g.get("score", 0) + 1
        g["index"] = g.get("index", 0) + 1
        context.user_data["game"] = g

        next_m = next_question(context)
        if next_m is None:
            await update.message.reply_text(
                f"{feedback}\n\n" + finish_text(context),
                reply_markup=back_keyboard(),
            )
            reset_state(context)
        else:
            await update.message.reply_text(
                f"{feedback}\n\nСледующий вопрос:\nК какой группе относится: {next_m}?",
                reply_markup=in_game_keyboard(),
            )
        return

    await update.message.reply_text("Меню:", reply_markup=menu_keyboard())

async def on_unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await update.message.reply_text(
            "Я понимаю только текстовые сообщения. Выбери действие:",
            reply_markup=menu_keyboard(),
        )

# =======================
#  НАСТРОЙКА PTB + FASTAPI (WEBHOOK)
# =======================

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
PUBLIC_URL = os.environ.get("PUBLIC_URL", "").rstrip("/")
# На некоторых платформах Render выставляет RENDER_EXTERNAL_URL — можно использовать как запасной источник:
if not PUBLIC_URL:
    PUBLIC_URL = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")

if not TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")
if not PUBLIC_URL:
    raise RuntimeError("PUBLIC_URL is not set (или RENDER_EXTERNAL_URL недоступен). Укажи PUBLIC_URL вручную в переменных окружения.")

application = (
    Application.builder()
    .updater(None)      # мы сами обрабатываем вебхук
    .token(TOKEN)
    .build()
)

# Регистрация хендлеров
application.add_handler(CommandHandler("start", cmd_start))
application.add_handler(CallbackQueryHandler(on_callback))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
application.add_handler(MessageHandler(~filters.TEXT, on_unknown))

WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"{PUBLIC_URL}{WEBHOOK_PATH}"

@asynccontextmanager
async def lifespan(_: FastAPI):
    # Устанавливаем вебхук при старте приложения
    await application.bot.setWebhook(WEBHOOK_URL)
    async with application:
        await application.start()
        yield
        await application.stop()

app = FastAPI(lifespan=lifespan)

@app.post(WEBHOOK_PATH)
async def telegram_webhook(req: Request) -> Response:
    data = await req.json()
    update = Update.de_json(data, application.bot)
    # Важно: быстро отдавать 200. Обработка update — асинхронная, но здесь достаточно await.
    await application.process_update(update)
    return Response(status_code=HTTPStatus.OK)

@app.get("/healthz")
async def healthz():
    return {"ok": True}

@app.get("/")
async def root():
    return {"service": "kpop-telegram-bot", "ok": True}

@app.get("/set_webhook")
async def set_webhook():
    ok = await application.bot.setWebhook(WEBHOOK_URL)
    return {"set_webhook": ok, "url": WEBHOOK_URL}
