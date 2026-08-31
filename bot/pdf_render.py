"""
Рендер дайджеста в виде PDF-презентации (16:9, один слайд = одна новость),
оформленной в стиле референсного мобильного приложения пользователя:
диагональный градиент фиолетовый → розовый → коралловый, скруглённые
"стеклянные" белые карточки поверх, крупные жирные белые заголовки, красные
кнопки-пилюли.

Кириллица — через шрифт DejaVu Sans из пакета matplotlib (см. комментарий
в предыдущей версии файла): используется только как источник .ttf-файла,
без графики matplotlib.

Слайды:
1. Обложка — заголовок, диапазон дат, две статистические плашки.
2. По одному слайду на каждую новость: тема-плашка, крупный заголовок,
   источник, карточка с саммари и красной кнопкой-ссылкой на источник.
3. Заключительный слайд с "Итоговыми наблюдениями".
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse

import matplotlib
from reportlab.lib.colors import HexColor, white
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from .ai_digest import DigestItem
from .thumbnails import fetch_thumbnails

# ---- Геометрия слайда (16:9, как в PowerPoint Widescreen) -----------------
PAGE_W, PAGE_H = 960, 540
MARGIN = 48

# ---- Палитра, вдохновлённая референсами ------------------------------------
GRADIENT_STOPS = ["#5B3E96", "#9B4B93", "#C9506F", "#E2634C"]  # фиолетовый → коралловый
CARD_BG = HexColor("#FFFFFF")
TEXT_DARK = HexColor("#241B2F")
TEXT_MUTED = HexColor("#6B6577")
ACCENT_RED = HexColor("#D6294B")
PILL_LIGHT = HexColor("#FFFFFF")

FONT_REGULAR = "DejaVuSans"
FONT_BOLD = "DejaVuSans-Bold"

_FONTS_REGISTERED = False


def _register_fonts() -> None:
    global _FONTS_REGISTERED
    if _FONTS_REGISTERED:
        return
    font_dir = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
    pdfmetrics.registerFont(TTFont(FONT_REGULAR, str(font_dir / "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont(FONT_BOLD, str(font_dir / "DejaVuSans-Bold.ttf")))
    _FONTS_REGISTERED = True


# ---- Низкоуровневые хелперы -------------------------------------------------------

def _hex_to_rgb(hex_color: str) -> tuple[float, float, float]:
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i : i + 2], 16) / 255 for i in (0, 2, 4))


def _interpolate(stops: List[str], t: float) -> tuple[float, float, float]:
    t = min(max(t, 0.0), 1.0)
    n = len(stops) - 1
    segment = min(int(t * n), n - 1)
    local_t = (t * n) - segment
    r1, g1, b1 = _hex_to_rgb(stops[segment])
    r2, g2, b2 = _hex_to_rgb(stops[segment + 1])
    return (r1 + (r2 - r1) * local_t, g1 + (g2 - g1) * local_t, b1 + (b2 - b1) * local_t)


def _draw_gradient_background(c: canvas.Canvas) -> None:
    steps = 160
    band_h = PAGE_H / steps
    for i in range(steps):
        t = i / (steps - 1)
        r, g, b = _interpolate(GRADIENT_STOPS, t)
        c.setFillColorRGB(r, g, b)
        y = PAGE_H - (i + 1) * band_h
        c.rect(0, y, PAGE_W, band_h + 1, stroke=0, fill=1)


def _wrap_text(c: canvas.Canvas, text: str, font: str, size: float, max_width: float) -> List[str]:
    words = (text or "").split()
    lines: List[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if c.stringWidth(candidate, font, size) <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _draw_wrapped(
    c: canvas.Canvas,
    text: str,
    x: float,
    top_y: float,
    font: str,
    size: float,
    leading: float,
    max_width: float,
    color,
    max_lines: int | None = None,
) -> float:
    """Рисует текст с переносом строк, возвращает y-координату после последней строки."""
    c.setFont(font, size)
    c.setFillColor(color)
    lines = _wrap_text(c, text, font, size, max_width)
    if max_lines is not None and len(lines) > max_lines:
        lines = lines[:max_lines]
        if lines:
            last = lines[-1]
            while c.stringWidth(last + "…", font, size) > max_width and len(last) > 1:
                last = last[:-1]
            lines[-1] = last + "…"
    y = top_y
    for line in lines:
        c.drawString(x, y, line)
        y -= leading
    return y


def _pill(c: canvas.Canvas, x: float, y: float, w: float, h: float, fill_color) -> None:
    c.setFillColor(fill_color)
    c.roundRect(x, y, w, h, h / 2, stroke=0, fill=1)


def _domain(url: str) -> str:
    try:
        netloc = urlparse(url).netloc
        return netloc.replace("www.", "") if netloc else url
    except Exception:
        return url


def _stat_card(
    c: canvas.Canvas,
    x: float,
    y: float,
    w: float,
    h: float,
    value: str,
    label: str,
    value_size: int | None = None,
) -> None:
    """Белая карточка с крупной цифрой и подписью — как 80%/75% в референсе."""
    c.setFillColor(CARD_BG)
    c.roundRect(x, y, w, h, 16, stroke=0, fill=1)
    if value_size is None:
        value_size = 26 if len(value) <= 6 else 18
    c.setFont(FONT_BOLD, value_size)
    c.setFillColor(ACCENT_RED)
    c.drawString(x + 16, y + h - value_size - 10, value)
    _draw_wrapped(c, label, x + 16, y + h - value_size - 26, FONT_REGULAR, 10, 13, w - 32, TEXT_MUTED, max_lines=2)


def _draw_image_box(c: canvas.Canvas, image_bytes: bytes, x: float, y: float, w: float, h: float) -> bool:
    """Рисует картинку, вписанную в скруглённый белый контейнер. True — если получилось."""
    try:
        img = ImageReader(BytesIO(image_bytes))
        c.setFillColor(CARD_BG)
        c.roundRect(x, y, w, h, 16, stroke=0, fill=1)
        pad = 5
        c.saveState()
        clip_path = c.beginPath()
        clip_path.roundRect(x + pad, y + pad, w - 2 * pad, h - 2 * pad, 11)
        c.clipPath(clip_path, stroke=0, fill=0)
        c.drawImage(
            img,
            x + pad,
            y + pad,
            width=w - 2 * pad,
            height=h - 2 * pad,
            preserveAspectRatio=True,
            anchor="c",
            mask="auto",
        )
        c.restoreState()
        return True
    except Exception:
        return False


# ---- Слайды ------------------------------------------------------------

def _draw_cover(c: canvas.Canvas, week_label: str, total_items: int, total_topics: int) -> None:
    _draw_gradient_background(c)

    c.setFont(FONT_BOLD, 40)
    c.setFillColor(white)
    c.drawString(MARGIN, PAGE_H - 150, "Дайджест новостей")

    c.setFont(FONT_REGULAR, 16)
    c.setFillColor(white)
    c.drawString(MARGIN, PAGE_H - 185, week_label)

    # две статистические плашки в духе референса (80% / 75%)
    card_w, card_h = 190, 110
    gap = 24
    y = 110

    for i, (value, label) in enumerate(
        [(str(total_items), "новостей за неделю"), (str(total_topics), "тем в подборке")]
    ):
        x = MARGIN + i * (card_w + gap)
        _stat_card(c, x, y, card_w, card_h, value, label, value_size=34)

    c.setFont(FONT_REGULAR, 11)
    c.setFillColorRGB(1, 1, 1)
    c.drawRightString(PAGE_W - MARGIN, MARGIN / 2, "Продукт: oral care")


def _draw_news_slide(
    c: canvas.Canvas,
    item: DigestItem,
    index: int,
    total: int,
    thumbnail: Optional[bytes],
) -> None:
    _draw_gradient_background(c)

    # верхний бейдж-логотип (плейсхолдер бренда)
    logo_size = 40
    c.setFillColor(white)
    c.roundRect(MARGIN, PAGE_H - MARGIN - logo_size, logo_size, logo_size, 12, stroke=0, fill=1)
    c.setFont(FONT_BOLD, 16)
    c.setFillColor(ACCENT_RED)
    c.drawCentredString(MARGIN + logo_size / 2, PAGE_H - MARGIN - logo_size / 2 - 5, "Д")

    # счётчик "N / total" справа сверху
    counter_text = f"{index} / {total}"
    c.setFont(FONT_BOLD, 12)
    counter_w = c.stringWidth(counter_text, FONT_BOLD, 12) + 28
    _pill(c, PAGE_W - MARGIN - counter_w, PAGE_H - MARGIN - 30, counter_w, 30, PILL_LIGHT)
    c.setFillColor(TEXT_DARK)
    c.drawCentredString(PAGE_W - MARGIN - counter_w / 2, PAGE_H - MARGIN - 20, counter_text)

    # плашка темы
    topic_text = (item.get("topic") or "").upper()
    row_top = PAGE_H - MARGIN - logo_size - 34
    if topic_text:
        c.setFont(FONT_BOLD, 11)
        topic_w = c.stringWidth(topic_text, FONT_BOLD, 11) + 28
        _pill(c, MARGIN, row_top, topic_w, 26, ACCENT_RED)
        c.setFillColor(white)
        c.drawString(MARGIN + 14, row_top + 8, topic_text)
        headline_top = row_top - 30
    else:
        headline_top = row_top

    # белая карточка внизу с саммари и кнопкой — считаем геометрию заранее,
    # чтобы знать, где заканчивается свободное место сверху
    card_h = 210
    card_y = 40
    card_top = card_y + card_h

    # --- правая колонка: картинка статьи и/или карточка со статистикой ---
    has_stat = bool(item.get("stat_value"))
    right_col_w = 300
    right_col_x = PAGE_W - MARGIN - right_col_w
    right_col_top = row_top + 26  # верх выровнен по плашке темы/счётчику
    available_h = right_col_top - card_top - 16

    thumbnail_drawn = False
    if thumbnail and available_h > 60:
        image_h = available_h - (74 if has_stat else 0) - (10 if has_stat else 0)
        image_h = max(image_h, 60)
        image_y = right_col_top - image_h
        thumbnail_drawn = _draw_image_box(c, thumbnail, right_col_x, image_y, right_col_w, image_h)

    if has_stat:
        stat_h = 74
        stat_y = (
            right_col_top - (image_h + 10 if thumbnail_drawn else 0) - stat_h
        )
        _stat_card(
            c,
            right_col_x,
            stat_y,
            right_col_w,
            stat_h,
            item.get("stat_value", ""),
            item.get("stat_label", "") or "ключевой показатель",
        )

    has_right_column = thumbnail_drawn or has_stat
    headline_max_w = (right_col_x - 24 - MARGIN) if has_right_column else (PAGE_W - 2 * MARGIN)

    # крупный заголовок
    title = item.get("title") or item.get("summary", "")
    headline_bottom = _draw_wrapped(
        c,
        title,
        MARGIN,
        headline_top,
        FONT_BOLD,
        30,
        36,
        headline_max_w,
        white,
        max_lines=3,
    )

    # источник (домен) под заголовком
    domain = _domain(item.get("link", ""))
    if domain:
        c.setFont(FONT_REGULAR, 13)
        c.setFillColor(white)
        c.drawString(MARGIN, headline_bottom - 8, domain)

    c.setFillColor(CARD_BG)
    c.roundRect(MARGIN, card_y, PAGE_W - 2 * MARGIN, card_h, 24, stroke=0, fill=1)

    text_x = MARGIN + 32
    text_max_w = PAGE_W - 2 * MARGIN - 64
    _draw_wrapped(
        c,
        item.get("summary", ""),
        text_x,
        card_y + card_h - 40,
        FONT_REGULAR,
        15,
        21,
        text_max_w,
        TEXT_DARK,
        max_lines=6,
    )

    # красная кнопка-ссылка "Читать источник"
    link = item.get("link", "")
    btn_w, btn_h = 210, 40
    btn_x = text_x
    btn_y = card_y + 24
    if link:
        _pill(c, btn_x, btn_y, btn_w, btn_h, ACCENT_RED)
        c.setFont(FONT_BOLD, 13)
        c.setFillColor(white)
        c.drawCentredString(btn_x + btn_w / 2, btn_y + 14, "Читать источник →")
        c.linkURL(link, (btn_x, btn_y, btn_x + btn_w, btn_y + btn_h), relative=0)
    else:
        c.setFont(FONT_REGULAR, 12)
        c.setFillColor(TEXT_MUTED)
        c.drawString(btn_x, btn_y + 14, "Источник не указан")


def _draw_insights_slide(c: canvas.Canvas, insights: str) -> None:
    _draw_gradient_background(c)

    c.setFont(FONT_BOLD, 30)
    c.setFillColor(white)
    _draw_wrapped(
        c,
        "Как это полезно для продукта в сфере oral care",
        MARGIN,
        PAGE_H - MARGIN - 30,
        FONT_BOLD,
        28,
        34,
        PAGE_W - 2 * MARGIN,
        white,
        max_lines=2,
    )

    card_h = 340
    card_y = 40
    c.setFillColor(CARD_BG)
    c.roundRect(MARGIN, card_y, PAGE_W - 2 * MARGIN, card_h, 24, stroke=0, fill=1)

    lines = [line.strip() for line in (insights or "").split("\n") if line.strip()]
    if not lines:
        lines = ["Явных выводов на этой неделе не нашлось."]

    text_x = MARGIN + 32
    dot_r = 4
    max_w = PAGE_W - 2 * MARGIN - 80
    y = card_y + card_h - 44

    for line in lines:
        c.setFillColor(ACCENT_RED)
        c.circle(text_x - 14, y + 6, dot_r, stroke=0, fill=1)
        y = _draw_wrapped(c, line, text_x, y, FONT_REGULAR, 14, 19, max_w, TEXT_DARK, max_lines=3)
        y -= 10
        if y < card_y + 20:
            break


# ---- Точка входа ------------------------------------------------------------

def build_pdf(items: List[DigestItem], insights: str, week_label: str, out_path: Path) -> None:
    _register_fonts()

    topics_count = len({item.get("topic", "") for item in items if item.get("topic")})

    # Картинки грузим один раз, параллельно, до начала отрисовки страниц.
    thumbnails = fetch_thumbnails([item.get("link", "") for item in items])

    c = canvas.Canvas(str(out_path), pagesize=(PAGE_W, PAGE_H))

    _draw_cover(c, week_label, len(items), topics_count)
    c.showPage()

    for idx, (item, thumb) in enumerate(zip(items, thumbnails), start=1):
        _draw_news_slide(c, item, idx, len(items), thumb)
        c.showPage()

    _draw_insights_slide(c, insights)
    c.showPage()

    c.save()
