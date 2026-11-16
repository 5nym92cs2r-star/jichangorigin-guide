"""Publish navigation from the public RSS only; never read the website source."""
from datetime import timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit, quote
from urllib.request import Request, urlopen
import html
import xml.etree.ElementTree as ET

ORIGIN = "https://jichangorigin.blog"
FEED = ORIGIN + "/rss.xml"
ROOT = Path(__file__).resolve().parents[2]


def md_text(text):
    text = html.escape(" ".join(text.split()), quote=True)
    for char in "\\`*_[]|":
        text = text.replace(char, f"&#{ord(char)};")
    return text


def fetch_public(url):
    request = Request(url, headers={"User-Agent": "JichangORG-PublicCatalog/1.0"})
    with urlopen(request, timeout=30) as response:
        if response.geturl() != url:
            raise ValueError("Unexpected public page redirect")
        data = response.read(2_000_001)
    if len(data) > 2_000_000:
        raise ValueError("Public page exceeds size limit")
    return data


class AirportTable(HTMLParser):
    """Read only the visible airport list, never scripts or source files."""
    def __init__(self):
        super().__init__()
        self.rows = []
        self.row = None
        self.billing = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "tr" and "data-airport" in attrs:
            self.row = {"id": attrs["data-airport"], "name": attrs.get("data-name", ""),
                        "price": attrs.get("data-price", ""), "billing": ""}
        if self.row is not None and tag == "td":
            self.billing = attrs.get("data-label") == "计费选择"

    def handle_data(self, data):
        if self.row is not None and self.billing:
            self.row["billing"] += data

    def handle_endtag(self, tag):
        if tag == "td":
            self.billing = False
        if tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None


def airport_markdown(data):
    parser = AirportTable()
    parser.feed(data.decode("utf-8"))
    if not 1 <= len(parser.rows) <= 100:
        raise ValueError("Airport table is missing; retaining the previous README")
    output = ["| 机场 | 月付起价 | 计费选择 | 介绍与套餐 |", "| --- | --- | --- | --- |"]
    seen = set()
    for row in parser.rows:
        slug = row["id"]
        if not slug or not all(c in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in slug) or slug in seen:
            raise ValueError("Invalid airport identifier")
        seen.add(slug)
        price = Decimal(row["price"])
        if not price.is_finite() or price <= 0 or price > 100000:
            raise ValueError("Invalid public price")
        if not row["name"] or not row["billing"].strip():
            raise ValueError("Missing public table fields")
        price_text = format(price.normalize(), 'f')
        output.append(f'| **{md_text(row["name"])}** | ¥{price_text}/月起 | {md_text(row["billing"])} | [查看介绍与套餐]({ORIGIN}/airports/{slug}/) |')
    return "\n".join(output)


def replace_section(text, name, content):
    start, end = f"<!-- {name}:start -->", f"<!-- {name}:end -->"
    if text.count(start) != 1 or text.count(end) != 1:
        raise ValueError("README update markers are missing or duplicated")
    before, rest = text.split(start)
    _, after = rest.split(end)
    return before + start + "\n" + content + "\n" + end + after


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
    data = fetch_public(FEED)
    catalog = render(data)
    table = airport_markdown(fetch_public(ORIGIN + "/airports/"))
    output = ROOT / "ARTICLES.md"
    readme = ROOT / "README.md"
    if output.is_symlink() or readme.is_symlink():
        raise ValueError("Public documents must not be symlinks")
    text = replace_section(readme.read_text(encoding="utf-8"), "airport-table", table)
    article_rows = [line for line in catalog.splitlines() if line.startswith("| 20")][:6]
    recent = "\n".join(["| 发布日期 | 分类 | 文章 |", "| --- | --- | --- |", *article_rows])
    text = replace_section(text, "recent-articles", recent)
    output.write_text(catalog, encoding="utf-8")
    readme.write_text(text, encoding="utf-8")
    print("Public airport table and article navigation updated.")


if __name__ == "__main__":
    main()
