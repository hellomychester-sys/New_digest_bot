"""
Генерация дайджеста новостей через Claude API со встроенным веб-поиском.

В отличие от предыдущей версии, здесь Claude возвращает не готовый markdown-текст,
а строго структурированные данные (JSON): плоский список новостей с полями
тема/саммари/ссылка плюс отдельный блок выводов. Из этих данных PDF собирает
модуль bot/pdf_render.py.

Требуется переменная окружения ANTHROPIC_API_KEY (ключ из console.anthropic.com).
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta
from typing import TypedDict

import anthropic
from zoneinfo import ZoneInfo

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")
MAX_TOKENS = 16000
TIMEZONE = ZoneInfo("Europe/Moscow")

# Фиксированный контекст продукта — виден модели всегда, независимо от /context.
BASE_PRODUCT_CONTEXT = (
    "Пользователь развивает собственный продукт в сфере ухода за полостью рта "
    "(oral care) — например, устройство, приложение или сервис, помогающие "
    "людям следить за здоровьем зубов и дёсен."
)

SYSTEM_PROMPT = f"""\
Ты — аналитик, который готовит еженедельный дайджест новостей для человека,
развивающего собственный продукт. {BASE_PRODUCT_CONTEXT}

Тебе на вход дают список тем/ключевых слов и диапазон дат (последние 7
календарных дней). Твоя задача:

1. Для КАЖДОЙ темы делай минимум 2 отдельных поисковых запроса:
   (а) на русском языке — специально, чтобы найти русскоязычные источники
       (российские и другие русскоязычные СМИ, отраслевые издания, Habr,
       VC.ru и т.п.), даже если сама тема сформулирована широко;
   (б) на английском языке (переведи суть темы) — чтобы найти мировые
       источники.
   Ищи новости, опубликованные строго в указанном диапазоне дат. Если по
   теме за неделю ничего значимого не нашлось ни на одном из языков —
   просто не включай её, не выдумывай новости.
2. Для каждой темы выбери до 4 самых релевантных и содержательных новостей,
   стараясь по возможности сохранить баланс между русскоязычными и
   зарубежными источниками, а не только зарубежные.
3. В самом конце ответить СТРОГО ОДНИМ JSON-объектом — без пояснений до или
   после, без markdown-обёртки в ```, без каких-либо других слов вне JSON.
   Формат:

{{
  "items": [
    {{"topic": "<название темы ровно как в списке тем>", "title": "<короткий цепляющий заголовок новости, до 9 слов, без кликбейта, по сути>", "summary": "<2-3 предложения своими словами о сути новости>", "link": "<полная рабочая ссылка на источник>", "stat_value": "<если в статье есть яркая ключевая цифра/показатель — например объём сделки, процент роста, число пользователей — укажи её здесь коротко, например \\"$700M\\" или \\"42%\\"; если такой цифры нет — пустая строка>", "stat_label": "<короткая подпись к этой цифре, 2-4 слова, например \\"объём сделки\\"; если stat_value пустой — тоже пустая строка>"}},
    ...
  ],
  "insights": "<3-5 пунктов с новой строки каждый — как находки этой недели можно применить к продукту в сфере oral care: что взять на вооружение, от чего предостеречься, какие гипотезы стоит протестировать>"
}}

Правила:
- items[].title — короткий заголовок для крупного текста на слайде (не более
  9 слов), должен точно отражать суть новости, без кликбейта и восклицаний.
- items[].stat_value/stat_label заполняй ТОЛЬКО если в самой статье
  действительно фигурирует конкретная яркая цифра. Не выдумывай и не
  притягивай статистику искусственно — пустые строки лучше, чем неточная
  цифра.
- items[].link — копируй ТОЧНО, посимвольно, ту ссылку, что дана в
  результатах веб-поиска (в tool_result). НИКОГДА не переписывай, не
  сокращай, не "чини" и не восстанавливай URL по памяти — если ты не
  уверен(а) в точном адресе конкретного результата, лучше не включай эту
  новость вообще, чем дать нерабочую ссылку.
- Каждая новость должна быть реально найдена через веб-поиск в этом же
  запросе. Никогда не изобретай источники или даты.
- summary пиши своими словами, без длинных дословных цитат.
- insights должен быть конкретным и явно опираться на находки из items, а не
  быть общими рассуждениями об oral care вообще.
- Финальное сообщение должно содержать ТОЛЬКО валидный JSON, без обрамляющего
  текста — это критично, ответ парсится программой автоматически.
- НИКОГДА не вставляй в значения полей теги вида <cite>, <cite index="...">,
  </cite>, <link> или любую другую XML/HTML-разметку цитирования — только
  обычный чистый текст без тегов.
"""


class DigestItem(TypedDict):
    topic: str
    title: str
    summary: str
    link: str
    stat_value: str
    stat_label: str


def _date_range_label() -> tuple[str, str, str]:
    today = datetime.now(TIMEZONE).date()
    week_ago = today - timedelta(days=7)
    label = f"с {week_ago.strftime('%d.%m.%Y')} по {today.strftime('%d.%m.%Y')}"
    return week_ago.isoformat(), today.isoformat(), label


def _strip_stray_tags(text: str) -> str:
    """
    Подстраховка: убирает теги вида <cite ...>...</cite>, <link ...>...</link>
    и т.п., если модель всё же вставила их в текст, оставляя только
    содержимое внутри тегов.
    """
    if not text:
        return text
    text = re.sub(r"</?(?:cite|link)[^>]*>", "", text)
    return text.strip()


def _extract_json(text: str) -> dict:
    """Достаёт JSON-объект из ответа модели, даже если она добавила лишний текст вокруг."""
    text = text.strip()
    # убираем возможные ```json ... ``` обёртки
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # запасной вариант: вырезаем от первой { до последней }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(text[start : end + 1])
    raise ValueError("Не удалось найти JSON в ответе модели")


def generate_digest(topics: list[str], context: str = "") -> tuple[list[DigestItem], str, str]:
    """
    Возвращает (items, insights, week_label).
    Бросает исключение, если не задан ANTHROPIC_API_KEY или запрос/парсинг не удались.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Не найдена переменная окружения ANTHROPIC_API_KEY. "
            "Получите ключ на console.anthropic.com и добавьте его в переменные окружения."
        )

    date_from, date_to, week_label = _date_range_label()

    topics_block = "\n".join(f"- {t}" for t in topics)
    context_block = f"\nДополнительный контекст от пользователя: {context}\n" if context else ""

    user_message = (
        f"Диапазон дат для поиска: {date_from} — {date_to} ({week_label}).\n\n"
        f"Темы для дайджеста:\n{topics_block}\n"
        f"{context_block}\n"
        "Собери дайджест по инструкциям из системного промпта и верни только JSON."
    )

    client = anthropic.Anthropic(api_key=api_key)

    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 18}],
        messages=[{"role": "user", "content": user_message}],
    )

    text_parts = [block.text for block in response.content if getattr(block, "type", None) == "text"]
    raw_text = "\n".join(text_parts).strip()

    if not raw_text:
        reason = getattr(response, "stop_reason", "неизвестна")
        raise RuntimeError(
            f"Claude не вернул текст ответа (причина остановки: {reason}) — попробуйте ещё раз "
            "или сократите число тем."
        )

    data = _extract_json(raw_text)

    items: list[DigestItem] = []
    for raw_item in data.get("items", []):
        items.append(
            DigestItem(
                topic=_strip_stray_tags(str(raw_item.get("topic", "")).strip()),
                title=_strip_stray_tags(str(raw_item.get("title", "")).strip()),
                summary=_strip_stray_tags(str(raw_item.get("summary", "")).strip()),
                link=str(raw_item.get("link", "")).strip(),
                stat_value=_strip_stray_tags(str(raw_item.get("stat_value", "")).strip()),
                stat_label=_strip_stray_tags(str(raw_item.get("stat_label", "")).strip()),
            )
        )

    insights = _strip_stray_tags(str(data.get("insights", "")).strip())

    return items, insights, week_label
