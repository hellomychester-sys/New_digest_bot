"""
Загрузка превью-картинки статьи (og:image / twitter:image) для отображения
на слайде дайджеста.

Картинки не берём из ответа модели — веб-поиск не даёт надёжных прямых
ссылок на изображения, и просить модель "угадать" URL картинки означало бы
рисковать нерабочими/придуманными ссылками. Вместо этого мы сами один раз
заходим на страницу статьи и читаем стандартный мета-тег og:image, который
почти все новостные сайты используют для превью при шаринге в соцсетях.

Работает "на лучшее усилие": если картинку получить не удалось (сайт
заблокировал бота, нет тега og:image, таймаут, устройство недоступно и
т.п.) — просто возвращаем None, и слайд рисуется без картинки. Это не
считается ошибкой дайджеста в целом.
"""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional
from urllib.parse import urljoin

import requests

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}
_TIMEOUT = 5
_MAX_HTML_BYTES = 300_000  # страницу целиком не грузим, достаточно начала с <head>
_MAX_WORKERS = 6

_OG_IMAGE_PATTERNS = [
    re.compile(
        r'<meta[^>]+(?:property|name)=["\'](?:og:image|twitter:image)["\'][^>]+content=["\']([^"\']+)["\']',
        re.IGNORECASE,
    ),
    re.compile(
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\'](?:og:image|twitter:image)["\']',
        re.IGNORECASE,
    ),
]


def fetch_thumbnail(article_url: str) -> Optional[bytes]:
    """Пытается получить байты превью-картинки статьи. При любой проблеме — None."""
    if not article_url:
        return None
    try:
        resp = requests.get(article_url, headers=_HEADERS, timeout=_TIMEOUT, stream=True)
        resp.raise_for_status()

        html_bytes = b""
        for chunk in resp.iter_content(8192):
            html_bytes += chunk
            if len(html_bytes) >= _MAX_HTML_BYTES or b"</head>" in html_bytes:
                break
        html_text = html_bytes.decode("utf-8", errors="ignore")

        image_url = None
        for pattern in _OG_IMAGE_PATTERNS:
            match = pattern.search(html_text)
            if match:
                image_url = match.group(1)
                break
        if not image_url:
            return None

        if image_url.startswith("//"):
            image_url = "https:" + image_url
        elif image_url.startswith("/"):
            image_url = urljoin(article_url, image_url)

        img_resp = requests.get(image_url, headers=_HEADERS, timeout=_TIMEOUT)
        img_resp.raise_for_status()
        if "image" not in img_resp.headers.get("Content-Type", ""):
            return None
        return img_resp.content
    except Exception as exc:  # noqa: BLE001 — картинка необязательна, просто пропускаем
        logger.info("Не удалось получить превью для %s: %s", article_url, exc)
        return None


def fetch_thumbnails(urls: List[str]) -> List[Optional[bytes]]:
    """Параллельно загружает превью для списка ссылок, сохраняя порядок."""
    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as executor:
        return list(executor.map(fetch_thumbnail, urls))
