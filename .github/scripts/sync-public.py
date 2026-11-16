"""Publish navigation from the public RSS only; never read the website source."""
from datetime import timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit, quote
from urllib.request import Request, urlopen
import html
import xml.etree.ElementTree as ET

ORIGIN = "https://jichangorigin.blog"
FEED = ORIGIN + "/rss.xml"
ROOT = Path(__file__).resolve().parents[2]


def safe_url(value):
    url = urlsplit(value)
    if (url.scheme != "https" or url.netloc != "jichangorigin.blog"
            or url.query or url.fragment or not url.path.startswith(("/knowledge/", "/ai/articles/"))):
        raise ValueError("RSS contains an unexpected article URL")
    return ORIGIN + quote(url.path, safe="/%-._~")


def render(data):
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ValueError("RSS entity declarations are not supported")
    channel = ET.fromstring(data).find("channel")
    if channel is None or channel.findtext("link", "").rstrip("/") != ORIGIN:
        raise ValueError("RSS is not the expected public website feed")
    rows = []
    seen = set()
    for item in channel.findall("item"):
        url = safe_url(item.findtext("link", ""))
        title = " ".join(item.findtext("title", "").split())
        if not title or len(title) > 200:
            raise ValueError("Invalid article title")
        if url in seen:
            continue
        seen.add(url)
        date = parsedate_to_datetime(item.findtext("pubDate", "")).astimezone(timezone.utc).date().isoformat()
        rows.append((date, title, url))
    if not 1 <= len(rows) <= 1000:
        raise ValueError("Unexpected RSS article count; retaining previous catalog")
    rows.sort(key=lambda row: (row[0], row[2]), reverse=True)
    output = ["# 机场ORG · 公开文章目录", "", "[返回网站](https://jichangorigin.blog/) · [RSS订阅](https://jichangorigin.blog/rss.xml)", "",
              f"共 {len(rows)} 篇 RSS 文章。以下日期为文章发布日期，完整内容请前往网站阅读。", "",
              "| 发布日期 | 分类 | 文章 |", "| --- | --- | --- |"]
    for date, title, url in rows:
        title = html.escape(title, quote=True)
        for char in "\\`*_[\u005d|":
            title = title.replace(char, f"&#{ord(char)};")
        category = "新手知识" if "/knowledge/beginner/" in url else "进阶知识" if "/knowledge/advanced/" in url else "AI知识"
        output.append(f'| {date} | {category} | <a href="{html.escape(url, quote=True)}">{title}</a> |')
    return "\n".join(output) + "\n"


def main():
    request = Request(FEED, headers={"User-Agent": "JichangORG-PublicCatalog/1.0"})
    with urlopen(request, timeout=30) as response:
        if response.geturl() != FEED:
            raise ValueError("Unexpected RSS redirect")
        data = response.read(2_000_001)
    if len(data) > 2_000_000:
        raise ValueError("RSS exceeds the public catalog size limit")
    output = ROOT / "ARTICLES.md"
    if output.is_symlink():
        raise ValueError("Catalog must not be a symlink")
    output.write_text(render(data), encoding="utf-8")
    print("Public article catalog updated from RSS.")


if __name__ == "__main__":
    main()
