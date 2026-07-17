"""
Collecte des items depuis les flux RSS et les pages web configurées dans config.yaml.
Retourne une liste d'items normalisés : {id, title, link, source, published, description}
"""
import hashlib
import logging
from datetime import datetime

import feedparser
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (BoomiWatch/1.0; +internal-tool)"
}
TIMEOUT = 15


def make_id(link: str) -> str:
    """ID stable et court basé sur l'URL, utilisé pour la déduplication."""
    return hashlib.sha256(link.encode("utf-8")).hexdigest()[:16]


def resolve_url_template(url: str, now: datetime | None = None) -> str:
    """Remplace les placeholders {year} et {month} par la date courante."""
    current = now or datetime.now()
    month_name = current.strftime("%B")
    return url.format(year=current.year, month=month_name)


def collect_rss(feed_cfg: dict) -> list[dict]:
    items = []
    try:
        parsed = feedparser.parse(feed_cfg["url"])
        if parsed.bozo and not parsed.entries:
            logger.warning("Flux RSS invalide ou vide pour %s (%s)", feed_cfg["name"], feed_cfg["url"])
            return items

        for entry in parsed.entries:
            link = entry.get("link", "")
            title = entry.get("title", "").strip()
            if not link or not title:
                continue
            items.append({
                "id": make_id(link),
                "title": title,
                "link": link,
                "source": feed_cfg["name"],
                "published": entry.get("published", ""),
            })
    except Exception as exc:
        logger.error("Erreur lors du parsing RSS de %s : %s", feed_cfg["name"], exc)
    return items


def collect_scrape(page_cfg: dict, keep_keywords: list[str]) -> list[dict]:
    items = []
    try:
        page_url = resolve_url_template(page_cfg["url"]) if "{" in page_cfg["url"] else page_cfg["url"]
        resp = requests.get(page_url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        item_selector = page_cfg.get("item_selector")
        candidates = []
        if item_selector:
            candidates.extend(soup.select(item_selector))

        if not candidates:
            for fallback_selector in [
                page_cfg.get("link_selector", "a"),
                "main a",
                "a[href]",
                "li a",
                "article a",
            ]:
                if fallback_selector:
                    candidates.extend(soup.select(fallback_selector))

        seen = set()
        for block in candidates:
            if not getattr(block, "name", None):
                continue

            if item_selector:
                title_selector = page_cfg.get("title_selector", "h2")
                desc_selector = page_cfg.get("description_selector", "p")
                link_selector = page_cfg.get("link_selector", "a")

                title_el = block.select_one(title_selector)
                if title_el is None and title_selector and block.name and block.name == "a":
                    title_el = block

                desc_el = block.select_one(desc_selector)
                link_el = block.select_one(link_selector)
                if link_el is None and link_selector and block.name and block.name == "a":
                    link_el = block

                title = title_el.get_text(strip=True) if title_el else ""
                description = desc_el.get_text(" ", strip=True) if desc_el else ""
                href = link_el.get("href", "") if link_el else ""
            else:
                title = block.get_text(strip=True)
                href = block.get("href", "")
                description = ""

            if not title or not href:
                continue

            if keep_keywords:
                text_lower = title.lower()
                if not any(kw.lower() in text_lower for kw in keep_keywords):
                    continue

            if href.startswith("/"):
                base = "/".join(page_url.split("/")[:3])
                href = base + href
            elif not href.startswith("http"):
                continue

            if href in seen:
                continue
            seen.add(href)

            items.append({
                "id": make_id(href),
                "title": title,
                "link": href,
                "description": description,
                "source": page_cfg["name"],
                "published": "",
            })
    except Exception as exc:
        logger.error("Erreur lors du scraping de %s : %s", page_cfg["name"], exc)
    return items


def collect_all(config: dict) -> list[dict]:
    all_items = []

    for feed_cfg in config.get("rss_feeds", []):
        all_items.extend(collect_rss(feed_cfg))

    keep_keywords = config.get("keep_keywords", [])
    for page_cfg in config.get("scrape_pages", []):
        all_items.extend(collect_scrape(page_cfg, keep_keywords))

    # Déduplication intra-run (même item trouvé sur 2 sources)
    unique = {item["id"]: item for item in all_items}
    return list(unique.values())
