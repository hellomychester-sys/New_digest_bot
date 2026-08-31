"""
Рендер дайджеста в PDF: единая таблица (Тема | Краткое саммари | Ссылка на
источник) и блок выводов под ней.

Для кириллицы в PDF нужен TTF-шрифт с поддержкой русских букв — стандартные
шрифты reportlab (Helvetica и т.п.) их не содержат. Чтобы не тащить в проект
отдельный файл шрифта и не усложнять Docker-образ системными библиотеками,
используем шрифт DejaVu Sans, который уже идёт в комплекте с пакетом
matplotlib (используется только как источник файла шрифта, без графики
matplotlib).
"""

from __future__ import annotations

from pathlib import Path
from typing import List
from xml.sax.saxutils import escape

import matplotlib
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .ai_digest import DigestItem

_FONTS_REGISTERED = False


def _register_fonts() -> None:
    global _FONTS_REGISTERED
    if _FONTS_REGISTERED:
        return
    font_dir = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
    pdfmetrics.registerFont(TTFont("DejaVuSans", str(font_dir / "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", str(font_dir / "DejaVuSans-Bold.ttf")))
    _FONTS_REGISTERED = True


def _esc(text: str) -> str:
    return escape(text or "")


def _esc_attr(text: str) -> str:
    return escape(text or "", {'"': "&quot;"})


def build_pdf(items: List[DigestItem], insights: str, week_label: str, out_path: Path) -> None:
    _register_fonts()

    title_style = ParagraphStyle(
        "title", fontName="DejaVuSans-Bold", fontSize=16, leading=20, spaceAfter=10
    )
    cell_style = ParagraphStyle("cell", fontName="DejaVuSans", fontSize=9, leading=12)
    cell_header_style = ParagraphStyle(
        "cell_header",
        fontName="DejaVuSans-Bold",
        fontSize=9,
        leading=12,
        textColor=colors.white,
    )
    heading_style = ParagraphStyle(
        "heading", fontName="DejaVuSans-Bold", fontSize=13, leading=16, spaceBefore=14, spaceAfter=8
    )
    body_style = ParagraphStyle("body", fontName="DejaVuSans", fontSize=10, leading=14, spaceAfter=6)

    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
    )

    story = []
    story.append(Paragraph(f"Дайджест новостей — {_esc(week_label)}", title_style))
    story.append(Spacer(1, 6))

    header_row = [
        Paragraph("Тема", cell_header_style),
        Paragraph("Краткое саммари", cell_header_style),
        Paragraph("Ссылка на источник", cell_header_style),
    ]
    table_data = [header_row]

    for item in items:
        link = item.get("link", "")
        if link:
            link_html = f'<link href="{_esc_attr(link)}" color="blue">{_esc(link)}</link>'
        else:
            link_html = "—"
        table_data.append(
            [
                Paragraph(_esc(item.get("topic", "")), cell_style),
                Paragraph(_esc(item.get("summary", "")), cell_style),
                Paragraph(link_html, cell_style),
            ]
        )

    if len(table_data) == 1:
        table_data.append(
            [Paragraph("—", cell_style), Paragraph("Новостей за неделю не найдено.", cell_style), Paragraph("—", cell_style)]
        )

    col_widths = [32 * mm, 88 * mm, 60 * mm]
    table = Table(table_data, colWidths=col_widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2b3a55")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f4f8")]),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(table)

    story.append(Paragraph("Как это полезно для продукта в сфере oral care", heading_style))
    insight_lines = [line.strip() for line in (insights or "").split("\n") if line.strip()]
    if not insight_lines:
        insight_lines = ["Явных выводов на этой неделе не нашлось."]
    for line in insight_lines:
        story.append(Paragraph(f"• {_esc(line)}", body_style))

    doc.build(story)
