import json
import os
import random
import urllib.parse
import urllib.request
from contextlib import asynccontextmanager
from http import HTTPStatus
from io import BytesIO
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Set

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
PHOTO_GAME_QUESTIONS = 20


def load_ai_kpop_groups(path: str = AI_GROUPS_FILE) -> Dict[str, List[str]]:
    """Load pre-generated AI groups from ``path``.

    The file can either contain a simple mapping of group names to members
    or an object with a ``groups`` list where each entry has ``name`` and
    ``members`` fields (as produced by the upstream AI script).
"""

    file = Path(path)
    if not file.exists():
        return {}
    with file.open("r", encoding="utf-8") as f:
        data = json.load(f)

    # Support both ``{"Group": [...]}`` and
    # ``{"groups": [{"name": "Group", "members": [...]}]}`` structures.
    if isinstance(data, dict) and "groups" in data and isinstance(data["groups"], list):
        return {item["name"]: item["members"] for item in data["groups"]}
    return data

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

# Stage names that require disambiguation on Wikipedia
WIKIMEDIA_TITLES: Dict[str, str] = {
    "Momo": "Momo (singer)",
}


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

def build_pretty_map(
    groups: Dict[str, List[str]], names_map: Optional[Dict[str, str]] = None
) -> Dict[str, str]:
    """Строит словарь допустимых названий групп -> ключ словаря."""
    mapping: Dict[str, str] = {}
    for k in groups.keys():
        low = k.lower()
        mapping[low] = k
        mapping[low.replace(" ", "")] = k
    if names_map:
        for key, pretty in names_map.items():
            low = pretty.lower()
            mapping[low] = key
            mapping[low.replace(" ", "")] = key
    return mapping


def build_member_map(groups: Dict[str, List[str]]) -> Dict[str, Set[str]]:
    """Создаёт словарь ``имя участника -> множество групп``,
    чтобы корректно обрабатывать случаи, когда одно и то же имя
    встречается в нескольких группах.
    Сопоставление выполняется в нижнем регистре."""
    member_map: Dict[str, Set[str]] = {}
    for group_key, members in groups.items():
        for member in members:
            member_map.setdefault(member.lower(), set()).add(group_key)
    return member_map

# --- Load and merge AI-generated groups ------------------------------------
ai_kpop_groups_raw: Optional[Dict[str, List[str]]] = load_ai_kpop_groups() or None
ai_kpop_groups: Optional[Dict[str, List[str]]]
ai_correct_grnames: Dict[str, str] = {}
if ai_kpop_groups_raw:
    ai_kpop_groups = {norm_group_key(name): members for name, members in ai_kpop_groups_raw.items()}
    ai_correct_grnames = {norm_group_key(name): name for name in ai_kpop_groups_raw.keys()}
else:
    ai_kpop_groups = None

for key, pretty in ai_correct_grnames.items():
    correct_grnames.setdefault(key, pretty)

ALL_GROUPS: Dict[str, List[str]] = {**kpop_groups}
if ai_kpop_groups:
    ALL_GROUPS.update(ai_kpop_groups)

# Быстрые словари для сопоставления "красивого" названия -> ключ группы
PRETTY_TO_KEY: Dict[str, str] = {v.lower(): k for k, v in correct_grnames.items()}

def menu_keyboard() -> InlineKeyboardMarkup:
    entries = [
        ("1. Угадай группу (базовый уровень)", "menu_play"),
        ("2. Угадай группу (ИИ)", "menu_ai_play"),
        ("3. Угадай по фото", "menu_photo"),
        ("4. Показать все группы", "menu_show_all"),
        ("5. Найти участника", "menu_find_member"),
        ("6. Режим обучения", "menu_learn"),
    ]
    kb = [[InlineKeyboardButton(text, callback_data=cb)] for text, cb in entries]
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

def _init_game(
    context: ContextTypes.DEFAULT_TYPE,
    groups: Dict[str, List[str]],
    names_map: Optional[Dict[str, str]] = None,
) -> None:
    all_members = dictionary_to_list(groups)
    sample_size = min(10, len(all_members))
    random_members = random.sample(all_members, sample_size)
    context.user_data["mode"] = "game"
    context.user_data["game"] = {
        "members": random_members,
        "index": 0,
        "score": 0,
        "current_member": None,
        "groups": groups,
        "pretty_map": build_pretty_map(groups, names_map),
        "member_map": build_member_map(groups),
        "total": sample_size,
    }


def start_game(context: ContextTypes.DEFAULT_TYPE) -> bool:
    _init_game(context, kpop_groups, correct_grnames)
    return True


def start_ai_game(context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Инициализирует режим игры с ИИ."""
    if not ai_kpop_groups:
        return False
    _init_game(context, ai_kpop_groups, ai_correct_grnames)
    context.user_data["mode"] = "ai_game"
    return True


def fetch_wikimedia_image(name: str) -> Optional[bytes]:
    """Скачивает изображение участника из Wikimedia.

    Возвращает байты файла или ``None``, если получить изображение не
    удалось.
    """
    title = WIKIMEDIA_TITLES.get(name, name)
    title = urllib.parse.quote(title)
    api_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
    try:
        with urllib.request.urlopen(api_url, timeout=10) as resp:
            if resp.status != 200:
                return None
            data = json.load(resp)
    except Exception:
        return None
    img_url = None
    if isinstance(data, dict):
        img_url = data.get("thumbnail", {}).get("source") or data.get("originalimage", {}).get("source")
    if not img_url:
        return None
    try:
        with urllib.request.urlopen(img_url, timeout=10) as img_resp:
            if img_resp.status != 200:
                return None
            return img_resp.read()
    except Exception:
        return None


def start_photo_game(context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Инициализирует игру "Угадай по фото" с загрузкой из Wikimedia."""
    all_members = list({m for members in ALL_GROUPS.values() for m in members})
    random.shuffle(all_members)
    items: List[Dict[str, bytes | str]] = []
    for name in all_members:
        img = fetch_wikimedia_image(name)
        if img:
            items.append({"image": img, "name": name})
        if len(items) >= PHOTO_GAME_QUESTIONS:
            break
    if len(items) < PHOTO_GAME_QUESTIONS:
        return False
    context.user_data["mode"] = "photo_game"
    context.user_data["game"] = {
        "items": items,
        "index": 0,
        "score": 0,
        "current": None,
        "total": len(items),
    }
    return True


def next_photo(context: ContextTypes.DEFAULT_TYPE) -> Optional[Dict[str, bytes | str]]:
    g = context.user_data.get("game", {})
    idx: int = g.get("index", 0)
    items: List[Dict[str, bytes | str]] = g.get("items", [])
    if idx >= len(items):
        return None
    item = items[idx]
    g["current"] = item
    context.user_data["game"] = g
    return item

def next_question(context: ContextTypes.DEFAULT_TYPE) -> Optional[str]:
    g = context.user_data.get("game", {})
    idx: int = g.get("index", 0)
    members: List[str] = g.get("members", [])
    total: int = g.get("total", len(members))
    if idx >= total:
        return None
    member = members[idx]
    g["current_member"] = member
    context.user_data["game"] = g
    return member


def finish_text(context: ContextTypes.DEFAULT_TYPE) -> str:
    g = context.user_data.get("game", {})
    score = g.get("score", 0)
    total = g.get("total", 10)
    return f"Игра окончена! Ты угадал {score} из {total}."


def progress_text(g: Dict[str, int]) -> str:
    """Return a text snippet with current score and remaining questions."""
    total = g.get("total", 0)
    score = g.get("score", 0)
    index = g.get("index", 0)
    remaining = max(total - index, 0)
    return f"Правильных ответов: {score} из {total}. Осталось вопросов: {remaining}."


async def launch_game(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    starter: Callable[[ContextTypes.DEFAULT_TYPE], bool],
    intro_text: str | None = None,
) -> None:
    """Запускает игру и отправляет первый вопрос.

    Если `starter` вернул False, сообщаем пользователю об ошибке.
    При наличии ``intro_text`` сначала выводит приветственное сообщение,
    а затем отдельным сообщением отправляет первый вопрос.
    """
    ok = starter(context)
    if not ok:
        await query.edit_message_text(
            (
                "AI-список групп недоступен.\n\n"
                "Создайте файл top50_groups.json, запустив generate_top_kpop_groups.py "
                "после установки переменной окружения OPENAI_API_KEY, и разместите его "
                "рядом с app.py."
            ),
            reply_markup=back_keyboard(),
        )
        return
    member = next_question(context)
    if member is None:
        await query.edit_message_text(
            finish_text(context), reply_markup=back_keyboard()
        )
        return

    question = f"К какой группе относится: {member}?\n\nНапиши название группы."

    if intro_text:
        await query.edit_message_text(
            intro_text,
            reply_markup=in_game_keyboard(),
            parse_mode="Markdown",
        )
        await query.message.reply_text(
            question,
            reply_markup=in_game_keyboard(),
            parse_mode="Markdown",
        )
    else:
        await query.edit_message_text(
            question,
            reply_markup=in_game_keyboard(),
            parse_mode="Markdown",
        )


async def launch_photo_game(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    ok = start_photo_game(context)
    if not ok:
        await query.edit_message_text(
            (
                "Фотографии недоступны.\n\n"
                "Не удалось получить достаточно изображений из Wikimedia."
            ),
            reply_markup=back_keyboard(),
        )
        return
    item = next_photo(context)
    await query.edit_message_text(
        "Угадай по фото! Назови айдола на снимке.",
        reply_markup=in_game_keyboard(),
    )
    if item:
        img: bytes = item["image"]  # type: ignore[assignment]
        await query.message.reply_photo(
            BytesIO(img),
            caption="Кто это?",
            reply_markup=in_game_keyboard(),
        )

# ----- Режим обучения

def start_learn_session(context: ContextTypes.DEFAULT_TYPE, group_key: str) -> None:
    members = list(ALL_GROUPS[group_key])
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
        await launch_game(query, context, start_game)
        return

    # --- Игра с группами от ИИ
    if data == "menu_ai_play":
        intro = (
            "⚔️ Это продвинутый уровень! Сразись с искусственным интеллектом.\n"
            "Тебя ждёт 10 вопросов о k-pop группах из топ-25 по популярности, "
            "включающем как мужские, так и женские команды и подготовленном AI.\n"
            "Попробуй набрать все 10 баллов!"
        )
        await launch_game(query, context, start_ai_game, intro_text=intro)
        return

    # --- Игра "Угадай по фото"
    if data == "menu_photo":
        await launch_photo_game(query, context)
        return

    # --- Показать все группы
    if data == "menu_show_all":
        lines: List[str] = []
        for key, members in ALL_GROUPS.items():
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
        if group_key not in ALL_GROUPS:
            await query.edit_message_text("Группа не найдена.", reply_markup=groups_keyboard())
            return
        members = ALL_GROUPS[group_key]
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
        if group_key not in ALL_GROUPS:
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
        masked = make_unique_mask_for_group_member(member, ALL_GROUPS[group_key])
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
        for group_key, members in ALL_GROUPS.items():
            if member in members:
                await update.message.reply_text(
                    f"{member} — участник группы *{correct_grnames.get(group_key, group_key)}*",
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
        pretty_map = g.get("pretty_map", PRETTY_TO_KEY)
        member_map = g.get("member_map", {})

        mapped_key = pretty_map.get(answer_key)
        is_correct = False
        if mapped_key and mapped_key in member_map.get(member.lower(), set()):
            is_correct = True

        feedback = "Верно!" if is_correct else "Неверно!"
        if is_correct:
            g["score"] = g.get("score", 0) + 1
        g["index"] = g.get("index", 0) + 1
        context.user_data["game"] = g

        stats = progress_text(g)
        next_m = next_question(context)
        if next_m is None:
            await update.message.reply_text(
                f"{feedback}\n{stats}\n\n" + finish_text(context),
                reply_markup=back_keyboard(),
            )
            reset_state(context)
        else:
            await update.message.reply_text(
                f"{feedback}\n{stats}\n\nСледующий вопрос:\nК какой группе относится: {next_m}?",
                reply_markup=in_game_keyboard(),
            )
        return

    # --- Игра "Угадай по фото"
    if mode == "photo_game":
        g = context.user_data.get("game", {})
        current = g.get("current")
        if current is None:
            item = next_photo(context)
            if item is None:
                await update.message.reply_text(
                    finish_text(context), reply_markup=back_keyboard()
                )
                reset_state(context)
                return
            img: bytes = item["image"]  # type: ignore[assignment]
            await update.message.reply_photo(
                BytesIO(img), caption="Кто это?", reply_markup=in_game_keyboard()
            )
            return
        answer = text.lower()
        correct = str(current["name"]).lower()
        is_correct = answer == correct
        feedback = "Верно!" if is_correct else f"Неверно! Это {current['name']}"
        if is_correct:
            g["score"] = g.get("score", 0) + 1
        g["index"] = g.get("index", 0) + 1
        context.user_data["game"] = g

        stats = progress_text(g)
        next_item = next_photo(context)
        if next_item is None:
            await update.message.reply_text(
                f"{feedback}\n{stats}\n\n" + finish_text(context),
                reply_markup=back_keyboard(),
            )
            reset_state(context)
        else:
            await update.message.reply_text(
                f"{feedback}\n{stats}\n\nСледующий вопрос:",
                reply_markup=in_game_keyboard(),
            )
            img: bytes = next_item["image"]  # type: ignore[assignment]
            await update.message.reply_photo(
                BytesIO(img), caption="Кто это?", reply_markup=in_game_keyboard()
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

        masked = make_unique_mask_for_group_member(next_member, ALL_GROUPS[group_key])  # type: ignore
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
