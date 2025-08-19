import json
import os
import random
from contextlib import asynccontextmanager
from http import HTTPStatus
from pathlib import Path
from typing import Dict, List, Optional, Set, Iterable

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

AI_GROUPS_FILE = "top50_groups.json"


def load_ai_kpop_groups(path: str = AI_GROUPS_FILE) -> Dict[str, List[str]]:
    file = Path(path)
    if file.exists():
        with file.open("r", encoding="utf-8") as f:
            return json.load(f)
    return {}


ai_kpop_groups: Dict[str, List[str]] = load_ai_kpop_groups()

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
    """Normalize user-provided group names.

    Besides trimming leading/trailing whitespace and lowercasing, collapse
    any sequence of internal whitespace into a single space so that inputs
    like ``"Red   Velvet"`` match stored keys such as ``"red velvet"``.
    """
    return " ".join(s.lower().split())

def menu_keyboard() -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton("1. Угадай группу", callback_data="menu_play")],
        [InlineKeyboardButton("2. Показать все группы", callback_data="menu_show_all")],
        [InlineKeyboardButton("3. Найти участника", callback_data="menu_find_member")],
        [InlineKeyboardButton("4. Режим обучения", callback_data="menu_learn")],
        [InlineKeyboardButton("5. Угадай группу (ИИ)", callback_data="menu_play_adv")],
    ]
    return InlineKeyboardMarkup(kb)

def back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад в меню", callback_data="menu_back")]])

def in_game_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🏁 Прервать игру", callback_data="menu_back")]])

# ---- callback "префиксы" для режима обучения
CB_LEARN_PICK = "learn_pick:"       # выбор группы
CB_LEARN_TRAIN = "learn_train:"     # перейти к тренировке по группе
CB_LEARN_MENU = "menu_learn"        # показать меню обучения
CB_LEARN_EXIT = "learn_exit"        # выйти из обучения в главное меню

def groups_keyboard() -> InlineKeyboardMarkup:
    # Клавиатура со списком групп для обучения (2 в ряд)
    buttons: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []
    for key in correct_grnames.keys():
        title = correct_grnames[key]
        row.append(InlineKeyboardButton(title, callback_data=f"{CB_LEARN_PICK}{key}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    # Кнопка "Назад"
    buttons.append([InlineKeyboardButton("⬅️ Назад в меню", callback_data="menu_back")])
    return InlineKeyboardMarkup(buttons)

def learn_after_list_keyboard(group_key: str) -> InlineKeyboardMarkup:
    # После вывода списка участников — предложить тренироваться или вернуться
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("▶️ Тренировать эту группу", callback_data=f"{CB_LEARN_TRAIN}{group_key}")],
        [InlineKeyboardButton("⬅️ Выбрать другую группу", callback_data=CB_LEARN_MENU)],
        [InlineKeyboardButton("🏠 В главное меню", callback_data="menu_back")],
    ])

def learn_in_session_keyboard() -> InlineKeyboardMarkup:
    # Во время тренировки — только выход/назад
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏁 Завершить обучение", callback_data=CB_LEARN_MENU)],
        [InlineKeyboardButton("🏠 В главное меню", callback_data="menu_back")],
    ])

# =======================
#  СОСТОЯНИЕ ПОЛЬЗОВАТЕЛЯ
# =======================
# user_data схема:
# {
#   "mode": "idle" | "find" | "game" | "learn_menu" | "learn_train",
#   "game": {
#       "members": list[str],
#       "index": int,
#       "score": int,
#       "current_member": str | None
#   },
#   "learn": {
#       "group_key": str,
#       "to_learn": list[str],
#       "known": set[str],
#       "current": str | None
#   }
# }

def reset_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.clear()
    context.user_data["mode"] = "idle"

# ----- Игра «Угадай группу»

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


def start_ai_game(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Инициализирует режим игры с ИИ."""
    start_game(context)
    context.user_data["mode"] = "ai_game"

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

# ----- Режим обучения

def start_learn_session(context: ContextTypes.DEFAULT_TYPE, group_key: str) -> None:
    members = list(kpop_groups[group_key])
    random.shuffle(members)  # случайный порядок
    context.user_data["mode"] = "learn_train"
    context.user_data["learn"] = {
        "group_key": group_key,
        "to_learn": members,
        "known": set(),    # уже верно названные имена (в нижнем регистре)
        "current": None,
    }

def _alpha_positions(s: str) -> List[int]:
    return [i for i, ch in enumerate(s) if ch.isalpha()]

def _matches_with_reveals(candidate: str, target: str, reveals: Set[int]) -> bool:
    """Проверяет, подходит ли имя candidate под маску target,
    где в позициях из reveals буквы должны совпасть (регистронезависимо),
    в остальных позициях:
      - если в target буква -> в candidate тоже должна быть буква (любая),
      - если в target не буква -> символы должны совпасть 1-в-1.
    Длины строк должны совпадать.
    """
    if len(candidate) != len(target):
        return False
    for i, t_ch in enumerate(target):
        c_ch = candidate[i]
        if t_ch.isalpha():
            if i in reveals:
                if c_ch.lower() != t_ch.lower():
                    return False
            else:
                if not c_ch.isalpha():
                    return False
        else:
            if c_ch != t_ch:
                return False
    return True

def _build_mask(target: str, reveals: Set[int]) -> str:
    out = []
    for i, ch in enumerate(target):
        if ch.isalpha() and i not in reveals:
            out.append("*")
        else:
            out.append(ch)
    return "".join(out)

def _unique_with_reveals(group: Iterable[str], target: str, reveals: Set[int]) -> bool:
    """Есть ли в группе ровно один кандидат, удовлетворяющий заданным открытым позициям?"""
    cnt = 0
    for cand in group:
        if _matches_with_reveals(cand, target, reveals):
            cnt += 1
            if cnt > 1:
                return False
    return cnt == 1

def make_unique_mask_for_group_member(name: str, group_members: List[str]) -> str:
    """
    Делает маску для 'name' так, чтобы:
      - сначала пытаемся с 1 открытой буквой (случайная позиция);
      - если по одной букве остаётся >1 кандидата внутри группы — подбираем вторую позицию,
        добиваясь ровно одного кандидата; перебираем все возможные вторые позиции.
    Возвращает строку-маску (звёздочки и открытые буквы), НЕ меняет регистр символов.
    """
    alpha_idx = _alpha_positions(name)
    if not alpha_idx:
        return name  # ничего маскировать

    # случайная первая позиция
    first = random.choice(alpha_idx)
    one_reveal = {first}

    # если уже уникально — оставляем одну букву
    if _unique_with_reveals(group_members, name, one_reveal):
        return _build_mask(name, one_reveal)

    # иначе подбираем вторую букву
    remaining_positions = [i for i in alpha_idx if i != first]
    random.shuffle(remaining_positions)

    for second in remaining_positions:
        reveals = {first, second}
        if _unique_with_reveals(group_members, name, reveals):
            return _build_mask(name, reveals)

    # Теоретически сюда не попадём (имена в группе уникальны),
    # но на всякий случай — раскроем две первые буквы-алф позиции.
    fallback = {alpha_idx[0]}
    if len(alpha_idx) > 1:
        fallback.add(alpha_idx[1])
    return _build_mask(name, fallback)

def pick_next_to_guess(context: ContextTypes.DEFAULT_TYPE) -> Optional[str]:
    data = context.user_data.get("learn", {})
    to_learn: List[str] = data.get("to_learn", [])
    known: set[str] = data.get("known", set())  # type: ignore
    remaining = [m for m in to_learn if m.lower() not in known]
    if not remaining:
        return None
    member = random.choice(remaining)
    data["current"] = member
    context.user_data["learn"] = data
    return member

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

    # --- Назад в меню
    if data == "menu_back":
        reset_state(context)
        await query.edit_message_text("Меню:", reply_markup=menu_keyboard())
        return

    # --- Игра «Угадай группу»
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

    if data == "menu_play_adv":
        start_ai_game(context)
        member = next_question(context)
        if member is None:
            await query.edit_message_text(finish_text(context), reply_markup=back_keyboard())
            return
        await query.edit_message_text(
            f"К какой группе относится: {member}?\n\n",
            "Напиши название группы.",
            reply_markup=in_game_keyboard(),
            parse_mode="Markdown",
        )
        return

    # --- Показать все группы
    if data == "menu_show_all":
        lines: List[str] = []
        for key, members in kpop_groups.items():
            line = f"*{correct_grnames[key]}*: {', '.join(members)}"
            lines.append(line)
        text = "Все группы:\n\n" + "\n".join(lines)
        await query.edit_message_text(text, reply_markup=back_keyboard(), parse_mode="Markdown")
        return

    # --- Найти участника
    if data == "menu_find_member":
        context.user_data["mode"] = "find"
        await query.edit_message_text(
            "Введите имя участника k-pop группы:",
            reply_markup=back_keyboard(),
            parse_mode="Markdown",
        )
        return

    # === Режим обучения: меню выбора группы
    if data == CB_LEARN_MENU or data == "menu_learn":
        context.user_data["mode"] = "learn_menu"
        await query.edit_message_text(
            "Выберите k-pop группу для изучения:",
            reply_markup=groups_keyboard(),
        )
        return

    # === Режим обучения: выбранная группа — показать состав и предложить тренироваться
    if data.startswith(CB_LEARN_PICK):
        group_key = data.split(":", 1)[1]
        if group_key not in kpop_groups:
            await query.edit_message_text("Группа не найдена.", reply_markup=groups_keyboard())
            return
        members = kpop_groups[group_key]
        lines = [f"{correct_grnames[group_key]}: {', '.join(members)}"]
        text = "Состав группы:\n\n" + "\n".join(lines)
        await query.edit_message_text(
            text,
            reply_markup=learn_after_list_keyboard(group_key),
        )
        return

    # === Режим обучения: начать тренировку по группе
    if data.startswith(CB_LEARN_TRAIN):
        group_key = data.split(":", 1)[1]
        if group_key not in kpop_groups:
            await query.edit_message_text("Группа не найдена.", reply_markup=groups_keyboard())
            return
        start_learn_session(context, group_key)
        member = pick_next_to_guess(context)
        if member is None:
            await query.edit_message_text(
                "Кажется, вы уже знаете всех участников этой группы!",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Выбрать другую группу", callback_data=CB_LEARN_MENU)],
                    [InlineKeyboardButton("🏠 В главное меню", callback_data="menu_back")],
                ]),
            )
            return
        masked = make_unique_mask_for_group_member(member, kpop_groups[group_key])
        await query.edit_message_text(
            f"Группа: {correct_grnames[group_key]}\n"
            f"Угадайте участника: <code>{masked}</code>\n\n"
            f"(введите имя сообщением)",
            parse_mode="HTML",
            reply_markup=learn_in_session_keyboard(),
        )
        return

    # === Режим обучения: явный выход
    if data == CB_LEARN_EXIT:
        reset_state(context)
        await query.edit_message_text("Меню:", reply_markup=menu_keyboard())
        return

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    mode = context.user_data.get("mode", "idle")
    text = (update.message.text or "").strip()

    # --- Найти участника
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

    # --- Игра «Угадай группу»
    if mode in ("game", "ai_game"):
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
            mapped_key = PRETTY_TO_KEY.get(answer_key)
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

    # --- Режим обучения: пользователь вводит ответы
    if mode == "learn_train":
        learn = context.user_data.get("learn", {})
        group_key: Optional[str] = learn.get("group_key")
        current: Optional[str] = learn.get("current")

        # Страховка: если текущего нет — выбираем
        if not current:
            current = pick_next_to_guess(context)
            if not current:
                title = correct_grnames.get(group_key or "", group_key or "")
                await update.message.reply_text(
                    f"Поздравляем! Вы смогли назвать по памяти всех участников группы {title}! 🎉",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("📚 Учить другую группу", callback_data=CB_LEARN_MENU)],
                        [InlineKeyboardButton("🏠 В главное меню", callback_data="menu_back")],
                    ]),
                )
                reset_state(context)
                return

        answer = (text or "").strip().lower()
        correct = current.lower()

        known: set[str] = learn.get("known", set())  # type: ignore

        if answer == correct:
            known.add(correct)
            learn["known"] = known
            context.user_data["learn"] = learn
            feedback = "Верно! ✅"
        else:
            feedback = f"Неверно. Правильный ответ: {current}"

        # Следующий кандидат среди неотгаданных
        next_member = pick_next_to_guess(context)
        title = correct_grnames.get(group_key or "", group_key or "")

        if next_member is None:
            await update.message.reply_text(
                f"{feedback}\n\nПоздравляем! Вы смогли назвать по памяти всех участников группы {title}! 🎉",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📚 Учить другую группу", callback_data=CB_LEARN_MENU)],
                    [InlineKeyboardButton("🏠 В главное меню", callback_data="menu_back")],
                ]),
            )
            reset_state(context)
            return

        masked = make_unique_mask_for_group_member(next_member, kpop_groups[group_key])  # type: ignore
        await update.message.reply_text(
            f"{feedback}\n\nГруппа: {title}\n"
            f"Следующий участник: <code>{masked}</code>",
            parse_mode="HTML",
            reply_markup=learn_in_session_keyboard(),
        )
        return

    # --- По умолчанию: показать меню
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
