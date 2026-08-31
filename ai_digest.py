"""
Генерация дайджеста новостей через Claude API со встроенным веб-поиском.

В отличие от простого парсинга RSS-ленты, здесь Claude сам ищет новости в
интернете (server-side web_search tool), отбирает релевантные, группирует
по темам и оформляет в формате, аналогичном обычному ручному дайджесту:
заголовки разделов, даты, источники со ссылками и краткий блок выводов.

Требуется переменная окружения ANTHROPIC_API_KEY (ключ из console.anthropic.com —
это отдельный ключ, НЕ токен телеграм-бота).
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta

import anthropic
from zoneinfo import ZoneInfo

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")
MAX_TOKENS = 8000
TIMEZONE = ZoneInfo("Europe/Moscow")

SYSTEM_PROMPT = """\
Ты — аналитик, который готовит еженедельный дайджест новостей для человека,
развивающего собственный IT-продукт. Тебе на вход дают список тем/ключевых
слов и диапазон дат (последние 7 календарных дней). Твоя задача:

1. Через инструмент веб-поиска найти реальные новости по каждой теме,
   опубликованные строго в указанном диапазоне дат. Если по теме за неделю
   ничего значимого не нашлось — так и напиши, не выдумывай новости.
2. Для каждой темы выбрать до 5 самых релевантных и содержательных новостей.
3. Оформить результат в Markdown по следующей структуре:

## <номер>. <Название темы>

- **<Короткое, ёмкое описание сути новости своими словами>** (дата, источник).
  [Источник](ссылка)
- ... (до 5 пунктов)

После всех тем — добавь раздел:

## Итоговые наблюдения

3-5 пунктов: сквозные паттерны, повторяющиеся тренды или гипотезы, которые
видны сразу в нескольких темах за эту неделю. Если пользователь предоставил
контекст о своём продукте — обязательно свяжи 1-2 наблюдения с этим контекстом
и укажи, чем именно это может быть полезно.

Правила:
- Каждый пункт — это реальная новость с реальной рабочей ссылкой на источник,
  найденная через веб-поиск. Никогда не придумывай источники или даты.
- Пиши своими словами, не копируй большие фрагменты текста дословно.
- Если по какой-то теме за неделю почти ничего не произошло, честно напиши
  об этом одной строкой вместо того, чтобы притягивать нерелевантные новости.
- Не добавляй никаких вводных фраз до заголовка "## 1." и никаких заключений
  после раздела "## Итоговые наблюдения".
"""


def _date_range_label() -> tuple[str, str, str]:
    today = datetime.now(TIMEZONE).date()
    week_ago = today - timedelta(days=7)
    label = f"с {week_ago.strftime('%d.%m.%Y')} по {today.strftime('%d.%m.%Y')}"
    return week_ago.isoformat(), today.isoformat(), label


def generate_digest(topics: list[str], context: str = "") -> tuple[str, str]:
    """
    Возвращает (markdown_текст, week_label).
    Бросает исключение, если не задан ANTHROPIC_API_KEY или запрос не удался —
    вызывающий код должен это обработать и сообщить пользователю.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Не найдена переменная окружения ANTHROPIC_API_KEY. "
            "Получите ключ на console.anthropic.com и добавьте его в .env."
        )

    date_from, date_to, week_label = _date_range_label()

    topics_block = "\n".join(f"- {t}" for t in topics)
    context_block = (
        f"\nКонтекст о продукте пользователя (используй в разделе 'Итоговые наблюдения'):\n{context}\n"
        if context
        else ""
    )

    user_message = (
        f"Диапазон дат для поиска: {date_from} — {date_to} ({week_label}).\n\n"
        f"Темы для дайджеста:\n{topics_block}\n"
        f"{context_block}\n"
        "Собери дайджест по инструкциям из системного промпта."
    )

    client = anthropic.Anthropic(api_key=api_key)

    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 20}],
        messages=[{"role": "user", "content": user_message}],
    )

    text_parts = [block.text for block in response.content if getattr(block, "type", None) == "text"]
    digest_text = "\n".join(text_parts).strip()

    if not digest_text:
        raise RuntimeError("Claude не вернул текст дайджеста — попробуйте ещё раз.")

    return digest_text, week_label
