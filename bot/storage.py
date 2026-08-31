"""
Простое хранилище состояния бота в JSON-файле.

Структура data/state.json:
{
    "chat_id": 123456789,       # куда слать дайджест (заполняется командой /start)
    "topics": ["тема 1", ...],  # список тем/ключевых слов
    "context": "текст"          # опционально: описание вашего продукта/интересов,
                                 # используется в разделе "Выводы" дайджеста
}
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import List, Optional

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
STATE_FILE = DATA_DIR / "state.json"

DEFAULT_TOPICS = [
    "e-commerce гипотезы и эксперименты",
    "здоровый образ жизни стартапы",
    "превентивная медицина wearable",
    "логистика инновации",
    "ритейл бизнес-модели",
    "стоматология технологии",
]

_lock = threading.Lock()


def _default_state() -> dict:
    return {"chat_id": None, "topics": list(DEFAULT_TOPICS), "context": ""}


def _ensure_file() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not STATE_FILE.exists():
        STATE_FILE.write_text(
            json.dumps(_default_state(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def load_state() -> dict:
    _ensure_file()
    with _lock:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
    # на случай апгрейда со старой версии state.json без поля "context"
    state.setdefault("context", "")
    return state


def save_state(state: dict) -> None:
    _ensure_file()
    with _lock:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)


def get_chat_id() -> Optional[int]:
    return load_state().get("chat_id")


def set_chat_id(chat_id: int) -> None:
    state = load_state()
    state["chat_id"] = chat_id
    save_state(state)


def get_topics() -> List[str]:
    return load_state().get("topics", [])


def add_topic(topic: str) -> bool:
    """Возвращает True, если тема добавлена, False — если уже была."""
    topic = topic.strip()
    state = load_state()
    topics = state.get("topics", [])
    if any(t.lower() == topic.lower() for t in topics):
        return False
    topics.append(topic)
    state["topics"] = topics
    save_state(state)
    return True


def remove_topic(topic: str) -> bool:
    """Возвращает True, если тема была найдена и удалена."""
    topic_norm = topic.strip().lower()
    state = load_state()
    topics = state.get("topics", [])
    new_topics = [t for t in topics if t.lower() != topic_norm]
    if len(new_topics) == len(topics):
        return False
    state["topics"] = new_topics
    save_state(state)
    return True


def get_context() -> str:
    return load_state().get("context", "")


def set_context(text: str) -> None:
    state = load_state()
    state["context"] = text.strip()
    save_state(state)
