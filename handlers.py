"""
Обработчики команд бота.

Команды:
  /start          — зарегистрировать текущий чат как получателя дайджеста
  /add <тема>     — добавить тему/ключевые слова для отслеживания
  /remove <тема>  — удалить тему
  /list           — показать список текущих тем
  /context <текст>— задать контекст о вашем продукте (для раздела "Выводы")
  /digest         — собрать и прислать дайджест прямо сейчас
  /help           — справка
"""

from __future__ import annotations

import logging
import tempfile
from datetime import datetime
from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes

from . import storage
from .ai_digest import generate_digest

logger = logging.getLogger(__name__)

HELP_TEXT = (
    "Я собираю новости по заданным темам за последнюю календарную неделю и "
    "присылаю дайджест по вашей команде.\n\n"
    "Команды:\n"
    "/digest — собрать и прислать дайджест прямо сейчас\n"
    "/add &lt;тема&gt; — добавить тему или ключевые слова\n"
    "/remove &lt;тема&gt; — удалить тему\n"
    "/list — показать текущие темы\n"
    "/context &lt;текст&gt; — описать ваш продукт/контекст, чтобы дайджест "
    "давал более прицельные выводы (необязательно)\n"
    "/help — эта справка"
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    storage.set_chat_id(chat_id)
    topics = storage.get_topics()
    topics_text = "\n".join(f"• {t}" for t in topics) if topics else "(пока пусто)"
    await update.message.reply_html(
        "Готово, этот чат подключён для получения дайджестов.\n\n"
        f"Текущие темы:\n{topics_text}\n\n" + HELP_TEXT
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_html(HELP_TEXT)


async def add_topic(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    topic = " ".join(context.args).strip()
    if not topic:
        await update.message.reply_text("Использование: /add <тема или ключевые слова>")
        return
    added = storage.add_topic(topic)
    if added:
        await update.message.reply_text(f"Тема добавлена: «{topic}»")
    else:
        await update.message.reply_text(f"Такая тема уже есть: «{topic}»")


async def remove_topic(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    topic = " ".join(context.args).strip()
    if not topic:
        await update.message.reply_text("Использование: /remove <тема>")
        return
    removed = storage.remove_topic(topic)
    if removed:
        await update.message.reply_text(f"Тема удалена: «{topic}»")
    else:
        await update.message.reply_text(f"Не нашёл такую тему: «{topic}». Посмотрите /list")


async def list_topics(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    topics = storage.get_topics()
    if not topics:
        await update.message.reply_text("Список тем пуст. Добавьте тему: /add <тема>")
        return
    text = "Текущие темы:\n" + "\n".join(f"• {t}" for t in topics)
    await update.message.reply_text(text)


async def set_context(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = " ".join(context.args).strip()
    if not text:
        current = storage.get_context()
        shown = current if current else "(не задан)"
        await update.message.reply_text(
            "Использование: /context <описание вашего продукта/интересов>\n\n"
            f"Текущий контекст: {shown}"
        )
        return
    storage.set_context(text)
    await update.message.reply_text("Контекст сохранён, буду учитывать его в разделе «Итоговые наблюдения».")


async def run_digest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    topics = storage.get_topics()
    if not topics:
        await update.message.reply_text("Список тем пуст. Сначала добавьте тему: /add <тема>")
        return

    await update.message.reply_text(
        f"Собираю дайджест по {len(topics)} темам за последнюю неделю — это может занять минуту..."
    )

    try:
        digest_text, week_label = generate_digest(topics, context=storage.get_context())
    except Exception as exc:  # noqa: BLE001 — сообщаем пользователю любую ошибку
        logger.exception("Ошибка при генерации дайджеста")
        await update.message.reply_text(f"Не получилось собрать дайджест: {exc}")
        return

    full_text = f"# Дайджест новостей — {week_label}\n\n{digest_text}\n"

    with tempfile.TemporaryDirectory() as tmp_dir:
        file_path = Path(tmp_dir) / f"digest_{datetime.now().strftime('%Y-%m-%d')}.md"
        file_path.write_text(full_text, encoding="utf-8")
        with open(file_path, "rb") as f:
            await update.message.reply_document(
                document=f,
                filename=file_path.name,
                caption=f"Дайджест по {len(topics)} темам, {week_label}",
            )
