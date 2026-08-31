"""
Точка входа бота.

Запуск локально:  python main.py
Требуются переменные окружения BOT_TOKEN и ANTHROPIC_API_KEY (см. .env.example).

Дайджест собирается только по команде /digest — никакого автоматического
расписания в этой версии нет (см. README, раздел "Как это работает").
"""

from __future__ import annotations

import logging
import os

from dotenv import load_dotenv
from telegram.ext import ApplicationBuilder, CommandHandler

from bot import handlers

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)


def main() -> None:
    load_dotenv()

    bot_token = os.environ.get("BOT_TOKEN")
    if not bot_token:
        raise SystemExit(
            "Не найдена переменная окружения BOT_TOKEN. "
            "Создайте .env по образцу .env.example и укажите токен от @BotFather."
        )

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit(
            "Не найдена переменная окружения ANTHROPIC_API_KEY. "
            "Получите ключ на console.anthropic.com и добавьте его в .env."
        )

    application = ApplicationBuilder().token(bot_token).build()

    application.add_handler(CommandHandler("start", handlers.start))
    application.add_handler(CommandHandler("help", handlers.help_command))
    application.add_handler(CommandHandler("add", handlers.add_topic))
    application.add_handler(CommandHandler("remove", handlers.remove_topic))
    application.add_handler(CommandHandler("list", handlers.list_topics))
    application.add_handler(CommandHandler("context", handlers.set_context))
    application.add_handler(CommandHandler("digest", handlers.run_digest))

    logging.info("Бот запущен, ждёт команд...")
    application.run_polling()


if __name__ == "__main__":
    main()
