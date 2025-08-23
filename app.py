import base64
import json
import logging
import os
import random
import re
from contextlib import asynccontextmanager
from datetime import date
from http import HTTPStatus
from io import BytesIO
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple

try:
    from fastapi import FastAPI, Request, Response
except Exception:  # pragma: no cover - used only when fastapi missing
    class FastAPI:
        def __init__(self, *args, **kwargs):
            pass

        def post(self, *args, **kwargs):
            def decorator(func):
                return func
            return decorator

        get = post

    class Request:
        pass

    class Response:
        def __init__(self, *args, **kwargs):
            pass

try:
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
except Exception:  # pragma: no cover - used only when telegram missing
    class Update:
        pass

    class InlineKeyboardButton:
        def __init__(self, text, callback_data=None):
            self.text = text
            self.callback_data = callback_data

    class InlineKeyboardMarkup:
        def __init__(self, inline_keyboard):
            self.inline_keyboard = inline_keyboard

    class Application:
        @classmethod
        def builder(cls):
            return cls()

        def updater(self, *args, **kwargs):
            return self

        def token(self, *args, **kwargs):
            return self

        def build(self, *args, **kwargs):
            return self

        def add_handler(self, *args, **kwargs):
            pass

    class CommandHandler:
        def __init__(self, *args, **kwargs):
            pass

    class MessageHandler:
        def __init__(self, *args, **kwargs):
            pass

    class CallbackQueryHandler:
        def __init__(self, *args, **kwargs):
            pass

    class ContextTypes:
        DEFAULT_TYPE = object

    class _DummyFilter:
        def __and__(self, other):
            return self

        __rand__ = __and__

        def __or__(self, other):
            return self

        __ror__ = __or__

        def __invert__(self):
            return self

    class filters:
        TEXT = _DummyFilter()
        COMMAND = _DummyFilter()
        PHOTO = _DummyFilter()

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
DROPBOX_ROOT = os.environ.get("DROPBOX_ROOT", "./dropbox_sync")
UPLOAD_PASSWORD = os.environ.get("UPLOAD_PASSWORD")

# Ограничение по количеству загружаемых фото в сутки для одного пользователя
UPLOAD_LIMIT_PER_DAY = 25
USER_UPLOADS: Dict[int, Tuple[date, int]] = {}

def has_reached_upload_limit(user_id: int) -> bool:
    """Возвращает True, если пользователь достиг лимита загрузок на сегодня."""
    today = date.today()
    last_date, count = USER_UPLOADS.get(user_id, (today, 0))
    if last_date != today:
        USER_UPLOADS[user_id] = (today, 0)
        return False
    return count >= UPLOAD_LIMIT_PER_DAY

def register_user_upload(user_id: int) -> None:
    """Увеличивает счетчик загрузок для пользователя на текущую дату."""
    today = date.today()
    last_date, count = USER_UPLOADS.get(user_id, (today, 0))
    if last_date != today:
        USER_UPLOADS[user_id] = (today, 1)
    else:
        USER_UPLOADS[user_id] = (today, count + 1)

# Remote location of the cover image within Dropbox
COVER_IMAGE_REMOTE_PATH = "/cover_image/cover1.png"
COVER_IMAGE_PATH = Path(DROPBOX_ROOT) / COVER_IMAGE_REMOTE_PATH.lstrip("/")

# Base64-encoded 1x1px transparent PNG used as a fallback cover image
_PLACEHOLDER_COVER_BYTES: bytes = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAAWgmWQ0AAAAASUVORK5CYII="
)


CHUNK_SIZE = 4 * 1024 * 1024  # 4MB used by Dropbox for content hashes


def _dropbox_content_hash(path: Path) -> str:
    """Compute the Dropbox content hash for ``path``."""
    import hashlib

    hasher = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                break
            hasher.update(hashlib.sha256(chunk).digest())
    return hasher.hexdigest()


def _dropbox_content_hash_bytes(data: bytes) -> str:
    """Compute the Dropbox content hash for raw ``data``."""
    import hashlib

    hasher = hashlib.sha256()
    bio = BytesIO(data)
    while True:
        chunk = bio.read(CHUNK_SIZE)
        if not chunk:
            break
        hasher.update(hashlib.sha256(chunk).digest())
    return hasher.hexdigest()


def _ensure_cover_image(dbx: Optional["dropbox.Dropbox"] = None) -> Path:
    """Download the cover image from Dropbox if needed.

    Only downloads when the local file is missing or has different content
    hash compared to Dropbox. Returns the local path to the image.
    """

    local_path = COVER_IMAGE_PATH
    local_path.parent.mkdir(parents=True, exist_ok=True)

    if dbx is None:
        try:
            import dropbox  # type: ignore
        except Exception:  # pragma: no cover - library missing
            return local_path
        app_key = os.environ.get("DROPBOX_APP_KEY")
        app_secret = os.environ.get("DROPBOX_APP_SECRET")
        refresh_token = os.environ.get("DROPBOX_REFRESH_TOKEN")
        if not all([app_key, app_secret, refresh_token]):
            return local_path
        try:
            dbx = dropbox.Dropbox(
                app_key=app_key,
                app_secret=app_secret,
                oauth2_refresh_token=refresh_token,
            )
        except Exception:  # pragma: no cover - network/auth errors
            return local_path

    try:
        metadata = dbx.files_get_metadata(COVER_IMAGE_REMOTE_PATH)
        if local_path.exists():
            try:
                if _dropbox_content_hash(local_path) == metadata.content_hash:
                    return local_path
            except OSError:
                pass
        _, res = dbx.files_download(COVER_IMAGE_REMOTE_PATH)
        with local_path.open("wb") as f:
            f.write(res.content)
    except Exception:  # pragma: no cover - network/auth errors
        pass
    return local_path


def _load_cover_image_bytes() -> bytes:
    path = _ensure_cover_image()
    try:
        return path.read_bytes()
    except OSError:
        return _PLACEHOLDER_COVER_BYTES


COVER_IMAGE_BYTES: bytes = _load_cover_image_bytes()


def _scan_dropbox_photos(root: Path = Path(DROPBOX_ROOT) / "kpop_images") -> Dict[str, List[str]]:
    """Обходит локальную синхронизацию Dropbox и строит карту
    ``нормализованное имя участника -> относительный путь к файлу``.

    Для каждого каталога участницы берётся первый попавшийся файл.
    В качестве ключей используются как полное имя папки, так и отдельные
    токены, разделённые пробелами, что позволяет поддерживать сокращённые
    варианты имён.
    """

    mapping: Dict[str, List[str]] = {}
    if not root.exists():
        return mapping

    for group_dir in root.iterdir():
        if not group_dir.is_dir():
            continue
        for member_dir in group_dir.iterdir():
            if not member_dir.is_dir():
                continue
            files = sorted(member_dir.iterdir())
            if not files:
                continue
            rel_paths = [
                str(f.relative_to(DROPBOX_ROOT)).replace("\\", "/")
                for f in files
            ]
            name = member_dir.name
            tokens = re.split(r"\s+", name)
            candidates = {name, *tokens}
            for cand in candidates:
                norm = re.sub(r"[-_\s]", "", cand.lower())
                lst = mapping.setdefault(norm, [])
                for rel in rel_paths:
                    lst.append(f"/{rel}")
    return mapping


DROPBOX_PHOTOS = _scan_dropbox_photos()


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
        ("7. Каталог фото", "menu_catalog"),
        ("[адм.] Добавить фото", "menu_upload"),
    ]
    kb = [[InlineKeyboardButton(text, callback_data=cb)] for text, cb in entries]
    return InlineKeyboardMarkup(kb)

def back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад в меню", callback_data="menu_back")]])

def in_game_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🏁 Прервать игру", callback_data="menu_back")]])

# ---- callback префиксы для загрузки фото
CB_UPLOAD_GROUP = "upload_group:"    # выбор группы для загрузки
CB_UPLOAD_MEMBER = "upload_member:"  # выбор участника для загрузки
CB_UPLOAD_MORE = "upload_more"       # добавить ещё фото


def upload_success_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Добавить ещё фото", callback_data=CB_UPLOAD_MORE)],
        [InlineKeyboardButton("⬅️ Назад в меню", callback_data="menu_back")],
    ])

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

def upload_groups_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура со списком групп, доступных для загрузки фото."""
    root = Path(DROPBOX_ROOT) / "kpop_images"
    buttons: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []
    if root.exists():
        for dir in sorted(p for p in root.iterdir() if p.is_dir()):
            key = dir.name.lower()
            title = correct_grnames.get(key, dir.name)
            row.append(InlineKeyboardButton(title, callback_data=f"{CB_UPLOAD_GROUP}{key}"))
            if len(row) == 2:
                buttons.append(row)
                row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("⬅️ Назад в меню", callback_data="menu_back")])
    return InlineKeyboardMarkup(buttons)

def upload_members_keyboard(group_key: str) -> InlineKeyboardMarkup:
    """Клавиатура со списком участников выбранной группы."""
    members = ALL_GROUPS.get(group_key, [])
    buttons: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []
    for member in members:
        row.append(InlineKeyboardButton(member, callback_data=f"{CB_UPLOAD_MEMBER}{member}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("⬅️ Выбрать другую группу", callback_data="menu_upload")])
    buttons.append([InlineKeyboardButton("🏠 В главное меню", callback_data="menu_back")])
    return InlineKeyboardMarkup(buttons)


def _next_member_filename(group_key: str, member: str, suffix: str) -> str:
    """Возвращает имя файла вида ``{member}__NN{suffix}`` с незанятым номером."""
    member_dir = Path(DROPBOX_ROOT) / "kpop_images" / group_key / member
    member_dir.mkdir(parents=True, exist_ok=True)

    used: Set[int] = set()
    pattern = re.compile(rf"^{re.escape(member)}__([0-9]{{2}})")

    # локальные файлы
    for file in member_dir.glob(f"{member}__*"):
        m = pattern.match(file.stem)
        if m:
            try:
                used.add(int(m.group(1)))
            except ValueError:
                continue

    # файлы в Dropbox (если доступно API)
    try:
        import dropbox  # type: ignore

        app_key = os.environ.get("DROPBOX_APP_KEY")
        app_secret = os.environ.get("DROPBOX_APP_SECRET")
        refresh_token = os.environ.get("DROPBOX_REFRESH_TOKEN")
        if all([app_key, app_secret, refresh_token]):
            dbx = dropbox.Dropbox(
                app_key=app_key,
                app_secret=app_secret,
                oauth2_refresh_token=refresh_token,
            )
            remote_folder = f"/kpop_images/{group_key}/{member}"
            try:
                res = dbx.files_list_folder(remote_folder)
                while True:
                    for entry in res.entries:
                        if isinstance(entry, dropbox.files.FileMetadata):
                            m = pattern.match(Path(entry.name).stem)
                            if m:
                                try:
                                    used.add(int(m.group(1)))
                                except ValueError:
                                    continue
                    if res.has_more:
                        res = dbx.files_list_folder_continue(res.cursor)
                    else:
                        break
            except Exception:
                pass
    except Exception:
        pass

    idx = 1
    while idx in used:
        idx += 1
    return f"{member}__{idx:02d}{suffix}"


def save_user_photo(group_key: str, member: str, data: bytes, suffix: str) -> bool:
    """Сохраняет фото локально и в Dropbox.

    Raises ``FileExistsError`` если в каталоге уже есть файл с таким же
    содержимым. Возвращает ``True`` при успешном сохранении.
    """
    local_dir = Path(DROPBOX_ROOT) / "kpop_images" / group_key / member
    local_dir.mkdir(parents=True, exist_ok=True)

    # Проверяем, нет ли уже такого файла по content hash
    new_hash = _dropbox_content_hash_bytes(data)
    for file in local_dir.iterdir():
        try:
            existing_hash = _dropbox_content_hash(file)
        except OSError:
            continue
        if existing_hash == new_hash:
            raise FileExistsError

    filename = _next_member_filename(group_key, member, suffix)
    local_path = local_dir / filename
    try:
        with local_path.open("wb") as f:
            f.write(data)
    except OSError:
        return False

    # Обновляем локальную карту
    rel_path = str(local_path.relative_to(DROPBOX_ROOT)).replace("\\", "/")
    norm = re.sub(r"[-_\s]", "", member.lower())
    DROPBOX_PHOTOS.setdefault(norm, []).append(f"/{rel_path}")

    # Попытка загрузить в Dropbox
    try:
        import dropbox  # type: ignore
        app_key = os.environ.get("DROPBOX_APP_KEY")
        app_secret = os.environ.get("DROPBOX_APP_SECRET")
        refresh_token = os.environ.get("DROPBOX_REFRESH_TOKEN")
        if all([app_key, app_secret, refresh_token]):
            dbx = dropbox.Dropbox(
                app_key=app_key,
                app_secret=app_secret,
                oauth2_refresh_token=refresh_token,
            )
            remote_path = f"/kpop_images/{group_key}/{member}/{filename}"
            dbx.files_upload(data, remote_path, mode=dropbox.files.WriteMode.overwrite)
    except Exception:
        pass
    return True

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


def fetch_dropbox_images(name: str) -> List[bytes]:
    """Возвращает все изображения участника из локальной папки Dropbox."""
    norm = re.sub(r"[-_\s]", "", name.lower())
    rel_paths = DROPBOX_PHOTOS.get(norm, [])
    images: List[bytes] = []
    for rel_path in rel_paths:
        file_path = Path(DROPBOX_ROOT) / rel_path.lstrip("/")
        try:
            with open(file_path, "rb") as f:
                images.append(f.read())
        except OSError:
            continue
    return images


def fetch_dropbox_image(name: str) -> Optional[bytes]:
    """Возвращает случайное изображение участника или ``None``."""
    images = fetch_dropbox_images(name)
    if not images:
        return None
    return random.choice(images)


def start_photo_game(context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Инициализирует игру "Угадай по фото" с загрузкой из Dropbox."""
    all_members = list({m for members in ALL_GROUPS.values() for m in members})
    items: List[Dict[str, bytes | str]] = []
    missing: List[str] = []
    for name in all_members:
        imgs = fetch_dropbox_images(name)
        if imgs:
            for img in imgs:
                items.append({"image": img, "name": name})
        else:
            missing.append(name)
    if len(items) < PHOTO_GAME_QUESTIONS:
        if missing:
            logging.warning("Missing Dropbox images for: %s", ", ".join(missing))
        return False
    # выбираем ровно PHOTO_GAME_QUESTIONS уникальных случайных фото
    items = random.sample(items, PHOTO_GAME_QUESTIONS)
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
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass
    ok = starter(context)
    if not ok:
        await query.message.reply_text(
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
        await query.message.reply_text(
            finish_text(context), reply_markup=back_keyboard()
        )
        return

    question = f"К какой группе относится: {member}?\n\nНапиши название группы."

    if intro_text:
        await query.message.reply_text(
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
        await query.message.reply_text(
            question,
            reply_markup=in_game_keyboard(),
            parse_mode="Markdown",
        )


async def launch_photo_game(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass
    ok = start_photo_game(context)
    if not ok:
        await query.message.reply_text(
            (
                "Фотографии недоступны.\n\n"
                "Не удалось получить достаточно изображений из Dropbox."
            ),
            reply_markup=back_keyboard(),
        )
        return
    item = next_photo(context)
    await query.message.reply_text(
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

# ----- Каталог фото --------------------------------------------------------

CB_CATALOG_PICK = "catalog_group:"  # выбор группы для каталога


def catalog_menu_keyboard() -> InlineKeyboardMarkup:
    """Главное меню каталога с выбором режима просмотра."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Просмотр по группам", callback_data="catalog_by_group")],
            [InlineKeyboardButton("Просмотр в случайном порядке", callback_data="catalog_random")],
            [InlineKeyboardButton("⬅️ Назад в меню", callback_data="menu_back")],
        ]
    )


def catalog_nav_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура навигации при показе фотографий."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("▶️ Следующее фото", callback_data="catalog_next")],
            [InlineKeyboardButton("📁 Обратно в меню каталога", callback_data="menu_catalog")],
            [InlineKeyboardButton("🏠 В главное меню", callback_data="menu_back")],
        ]
    )


def catalog_groups_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура со списком групп для каталога."""
    buttons: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []
    for key in correct_grnames.keys():
        members = ALL_GROUPS.get(key, [])
        has_photo = any(
            re.sub(r"[-_\s]", "", m.lower()) in DROPBOX_PHOTOS for m in members
        )
        if not has_photo:
            continue
        title = correct_grnames[key]
        row.append(InlineKeyboardButton(title, callback_data=f"{CB_CATALOG_PICK}{key}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("⬅️ В каталог", callback_data="menu_catalog")])
    return InlineKeyboardMarkup(buttons)


def build_catalog_for_group(
    group_key: str, groups: Dict[str, List[str]] = ALL_GROUPS
) -> List[Dict[str, bytes | str]]:
    """Собирает фотографии участников выбранной группы в случайном порядке."""
    items: List[Dict[str, bytes | str]] = []
    for name in groups.get(group_key, []):
        imgs = fetch_dropbox_images(name)
        for img in imgs:
            items.append({"image": img, "name": name, "group": group_key})
    random.shuffle(items)
    return items


def build_catalog_random(
    groups: Dict[str, List[str]] = ALL_GROUPS,
) -> List[Dict[str, bytes | str]]:
    """Собирает фотографии всех участников во всех группах в случайном порядке."""
    items: List[Dict[str, bytes | str]] = []
    for group_key, members in groups.items():
        for name in members:
            imgs = fetch_dropbox_images(name)
            for img in imgs:
                items.append({"image": img, "name": name, "group": group_key})
    random.shuffle(items)
    return items


def start_random_catalog(context: ContextTypes.DEFAULT_TYPE) -> bool:
    items = build_catalog_random()
    if not items:
        return False
    context.user_data["mode"] = "catalog"
    context.user_data["catalog"] = {
        "items": items,
        "index": 0,
        "mode": "random",
    }
    return True


def start_group_catalog(
    context: ContextTypes.DEFAULT_TYPE, group_key: str
) -> bool:
    items = build_catalog_for_group(group_key)
    if not items:
        return False
    context.user_data["mode"] = "catalog"
    context.user_data["catalog"] = {
        "items": items,
        "index": 0,
        "mode": "group",
        "group": group_key,
    }
    return True


def next_catalog_item(
    context: ContextTypes.DEFAULT_TYPE,
) -> Optional[Dict[str, bytes | str]]:
    catalog = context.user_data.get("catalog", {})
    idx: int = catalog.get("index", 0)
    items: List[Dict[str, bytes | str]] = catalog.get("items", [])
    if idx >= len(items):
        return None
    item = items[idx]
    catalog["index"] = idx + 1
    context.user_data["catalog"] = catalog
    return item

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
    await update.message.reply_photo(
        BytesIO(COVER_IMAGE_BYTES),
        caption="Добро пожаловать в K-pop игру!! Выбери действие:",
        reply_markup=menu_keyboard(),
    )

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data

    # --- Назад в меню
    if data == "menu_back":
        reset_state(context)
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        await query.message.reply_photo(
            BytesIO(COVER_IMAGE_BYTES),
            caption="Меню:",
            reply_markup=menu_keyboard(),
        )
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

    # --- Каталог фото
    if data == "menu_catalog":
        reset_state(context)
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        await query.message.reply_text(
            "Каталог фото:", reply_markup=catalog_menu_keyboard()
        )
        return

    if data == "catalog_by_group":
        await query.edit_message_text(
            "Выберите группу:", reply_markup=catalog_groups_keyboard()
        )
        return

    if data.startswith(CB_CATALOG_PICK):
        group_key = data.split(":", 1)[1]
        ok = start_group_catalog(context, group_key)
        if not ok:
            await query.edit_message_text(
                "Нет доступных фото для этой группы.",
                reply_markup=catalog_menu_keyboard(),
            )
            return
        item = next_catalog_item(context)
        await query.edit_message_text(
            f"Фото участников группы {correct_grnames.get(group_key, group_key)}:",
            reply_markup=catalog_nav_keyboard(),
        )
        if item:
            img: bytes = item["image"]  # type: ignore[assignment]
            await query.message.reply_photo(
                BytesIO(img),
                caption=item["name"],
                reply_markup=catalog_nav_keyboard(),
            )
        return

    if data == "catalog_random":
        ok = start_random_catalog(context)
        if not ok:
            await query.edit_message_text(
                "Фото недоступны.", reply_markup=catalog_menu_keyboard()
            )
            return
        item = next_catalog_item(context)
        await query.edit_message_text(
            "Случайные фото айдолов:",
            reply_markup=catalog_nav_keyboard(),
        )
        if item:
            cap = (
                f"{item['name']} из группы "
                f"{correct_grnames.get(item['group'], item['group'])}"
            )
            img: bytes = item["image"]  # type: ignore[assignment]
            await query.message.reply_photo(
                BytesIO(img), caption=cap, reply_markup=catalog_nav_keyboard()
            )
        return

    if data == "catalog_next":
        item = next_catalog_item(context)
        if item is None:
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text(
                "Больше нет фото.", reply_markup=catalog_menu_keyboard()
            )
            return
        await query.edit_message_reply_markup(reply_markup=None)
        mode = context.user_data.get("catalog", {}).get("mode")
        caption = (
            item["name"]
            if mode == "group"
            else f"{item['name']} из группы {correct_grnames.get(item['group'], item['group'])}"
        )
        img: bytes = item["image"]  # type: ignore[assignment]
        await query.message.reply_photo(
            BytesIO(img), caption=caption, reply_markup=catalog_nav_keyboard()
        )
        return

    # --- Загрузка пользовательских фото
    if data == "menu_upload":
        context.user_data["mode"] = "upload_password"
        await query.message.reply_text(
            "Введите пароль для загрузки фото:", reply_markup=back_keyboard()
        )
        return

    if data.startswith(CB_UPLOAD_GROUP):
        group_key = data.split(":", 1)[1]
        context.user_data["upload_group"] = group_key
        context.user_data["mode"] = "upload_member"
        title = correct_grnames.get(group_key, group_key)
        await query.message.reply_text(
            f"Выберите участника группы {title}:",
            reply_markup=upload_members_keyboard(group_key),
        )
        return

    if data.startswith(CB_UPLOAD_MEMBER):
        member = data.split(":", 1)[1]
        context.user_data["upload_member"] = member
        context.user_data["mode"] = "upload_wait_photo"
        await query.message.reply_text(
            f"Отправьте фото для {member} (до 8 МБ)",
            reply_markup=back_keyboard(),
        )
        return

    if data == CB_UPLOAD_MORE:
        member = context.user_data.get("upload_member")
        if not member:
            await query.message.reply_text(
                "Не выбран участник.", reply_markup=back_keyboard()
            )
            return
        context.user_data["mode"] = "upload_wait_photo"
        await query.message.reply_text(
            f"Отправьте фото для {member} (до 8 МБ)",
            reply_markup=back_keyboard(),
        )
        return

    # --- Показать все группы
    if data == "menu_show_all":
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        lines: List[str] = []
        for key, members in ALL_GROUPS.items():
            line = f"*{correct_grnames[key]}*: {', '.join(members)}"
            lines.append(line)
        text = "Все группы:\n\n" + "\n".join(lines)
        await query.message.reply_text(text, reply_markup=back_keyboard(), parse_mode="Markdown")
        return

    # --- Найти участника
    if data == "menu_find_member":
        context.user_data["mode"] = "find"
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        await query.message.reply_text(
            "Введите имя участника k-pop группы:",
            reply_markup=back_keyboard(),
            parse_mode="Markdown",
        )
        return

    # === Режим обучения: меню выбора группы
    if data == CB_LEARN_MENU or data == "menu_learn":
        context.user_data["mode"] = "learn_menu"
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        await query.message.reply_text(
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

    # --- Проверка пароля для загрузки фото
    if mode == "upload_password":
        if UPLOAD_PASSWORD and text == UPLOAD_PASSWORD:
            context.user_data["mode"] = "upload_group"
            await update.message.reply_text(
                "Выберите группу:", reply_markup=upload_groups_keyboard()
            )
        else:
            await update.message.reply_text(
                "Неверный пароль. Попробуйте снова:", reply_markup=back_keyboard()
            )
        return

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

async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    mode = context.user_data.get("mode", "idle")
    if mode == "upload_wait_photo":
        group_key = context.user_data.get("upload_group")
        member = context.user_data.get("upload_member")
        if not group_key or not member:
            await update.message.reply_text("Не выбрана группа или участник.", reply_markup=back_keyboard())
            reset_state(context)
            return
        user = update.effective_user
        if user and has_reached_upload_limit(user.id):
            await update.message.reply_text(
                f"Достигнут лимит загрузок в день, равный {UPLOAD_LIMIT_PER_DAY} фото.",
                reply_markup=back_keyboard(),
            )
            reset_state(context)
            return
        photo = update.message.photo[-1]
        if photo.file_size and photo.file_size > 8 * 1024 * 1024:
            await update.message.reply_text(
                "Допустимый объем фото — до 8Мб.", reply_markup=back_keyboard()
            )
            return
        file = await photo.get_file()
        data = await file.download_as_bytearray()
        suffix = Path(file.file_path or "").suffix or ".jpg"
        try:
            ok = save_user_photo(group_key, member, bytes(data), suffix)  # type: ignore[arg-type]
        except FileExistsError:
            await update.message.reply_text(
                "Такое фото уже существует.", reply_markup=back_keyboard()
            )
        else:
            if ok:
                if update.effective_user:
                    register_user_upload(update.effective_user.id)
                await update.message.reply_text(
                    "Фото успешно загружено!", reply_markup=upload_success_keyboard()
                )
            else:
                await update.message.reply_text(
                    "Не удалось сохранить фото.", reply_markup=back_keyboard()
                )
        return
    await on_unknown(update, context)

# =======================
#  НАСТРОЙКА PTB + FASTAPI (WEBHOOK)
# =======================

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
PUBLIC_URL = os.environ.get("PUBLIC_URL", "").rstrip("/")
# На некоторых платформах Render выставляет RENDER_EXTERNAL_URL — можно использовать как запасной источник:
if not PUBLIC_URL:
    PUBLIC_URL = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")

application = None
if TOKEN and PUBLIC_URL:
    application = (
        Application.builder()
        .updater(None)      # мы сами обрабатываем вебхук
        .token(TOKEN)
        .build()
    )

    # Регистрация хендлеров
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CallbackQueryHandler(on_callback))
    application.add_handler(MessageHandler(filters.PHOTO, on_photo))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    application.add_handler(MessageHandler(~(filters.TEXT | filters.PHOTO), on_unknown))

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
