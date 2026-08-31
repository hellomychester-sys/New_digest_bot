"""
Обработчики команд бота.

Команды:
  /start          — зарегистрировать текущий чат как получателя дайджеста
  /add <тема>     — добавить тему/ключевые слова для отслеживания
  /remove <тема>  — удалить тему
  /list           — показать список текущих тем
  /context <текст>— задать дополнительный контекст (в дополнение к oral care)
  /digest         — собрать и прислать дайджест в PDF прямо сейчас
  /help           — справка
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from datetime import datetime
from pathlib import Path

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import ContextTypes

from . import storage
from .ai_digest import generate_digest
from .pdf_render import build_pdf

logger = logging.getLogger(__name__)

HELP_TEXT = (
    "Я собираю новости по заданным темам за последнюю календарную неделю и "
    "присылаю дайджест в виде PDF-таблицы (тема / саммари / ссылка) с блоком "
    "выводов для продукта в сфере oral care — по вашей команде.\n\n"
    "Команды:\n"
    "/digest — собрать и прислать дайджест прямо сейчас\n"
    "/add &lt;тема&gt; — добавить тему или ключевые слова\n"
    "/remove &lt;тема&gt; — удалить тему\n"
    "/list — показать текущие темы\n"
    "/context &lt;текст&gt; — добавить контекст сверх oral care (необязательно)\n"
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
            "Использование: /context <дополнительный контекст>\n\n"
            "Контекст про oral care уже учитывается всегда по умолчанию — "
            "здесь можно добавить что-то ещё сверху.\n\n"
            f"Текущий дополнительный контекст: {shown}"
        )
        return
    storage.set_context(text)
    await update.message.reply_text("Контекст сохранён, буду учитывать его в дайджесте.")


async def _show_progress(bot, chat_id: int, status_message) -> None:
    """
    Пока идёт долгая генерация дайджеста, раз в несколько секунд:
    - шлёт Telegram-индикатор "печатает..." (сам гаснет через ~5 сек, поэтому обновляем)
    - редактирует статусное сообщение, показывая, сколько уже прошло времени
    Работает до тех пор, пока задачу не отменят снаружи (asyncio.CancelledError).
    """
    start = datetime.now()
    dots_cycle = ["", ".", "..", "..."]
    i = 0
    try:
        while True:
            try:
                await bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_DOCUMENT)
            except Exception:
                pass
            elapsed = int((datetime.now() - start).total_seconds())
            try:
                await status_message.edit_text(
                    f"Собираю дайджест{dots_cycle[i % len(dots_cycle)]} ({elapsed} сек, обычно занимает 1-2 минуты)"
                )
            except Exception:
                pass  # например, "message is not modified" — не критично, просто пропускаем
            i += 1
            await asyncio.sleep(4)
    except asyncio.CancelledError:
        pass


async def run_digest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    topics = storage.get_topics()
    if not topics:
        await update.message.reply_text("Список тем пуст. Сначала добавьте тему: /add <тема>")
        return

    status_message = await update.message.reply_text(
        f"Собираю дайджест по {len(topics)} темам за последнюю неделю..."
    )

    progress_task = asyncio.create_task(
        _show_progress(context.bot, update.effective_chat.id, status_message)
    )

    try:
        # generate_digest — синхронный вызов (использует обычный anthropic-клиент),
        # выносим в отдельный поток, чтобы бот не "замирал" и мог отвечать на другие
        # сообщения / крутить индикатор прогресса, пока идёт долгий запрос.
        items, insights, week_label = await asyncio.to_thread(
            generate_digest, topics, storage.get_context()
        )
    except Exception as exc:  # noqa: BLE001 — сообщаем пользователю любую ошибку
        logger.exception("Ошибка при генерации дайджеста")
        progress_task.cancel()
        await status_message.edit_text(f"Не получилось собрать дайджест: {exc}")
        return

    progress_task.cancel()
    await status_message.edit_text("Дайджест собран, готовлю PDF...")

    with tempfile.TemporaryDirectory() as tmp_dir:
        file_path = Path(tmp_dir) / f"digest_{datetime.now().strftime('%Y-%m-%d')}.pdf"
        try:
            build_pdf(items, insights, week_label, file_path)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Ошибка при сборке PDF")
            await status_message.edit_text(f"Дайджест собран, но не получилось сделать PDF: {exc}")
            return

        await status_message.edit_text(f"Готово! {len(items)} новостей по {len(topics)} темам, {week_label}")

        with open(file_path, "rb") as f:
            await update.message.reply_document(
                document=f,
                filename=file_path.name,
                caption=f"Дайджест: {len(items)} новостей по {len(topics)} темам, {week_label}",
            )
