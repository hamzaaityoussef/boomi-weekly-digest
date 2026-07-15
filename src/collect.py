"""
Collecte des items depuis les flux RSS et les pages web configurées dans config.yaml.
Retourne une liste d'items normalisés : {id, title, link, source, published}
"""
import hashlib
import logging

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
        resp = requests.get(page_cfg["url"], headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        links = soup.select(page_cfg.get("link_selector", "a"))
        for a in links:
            title = a.get_text(strip=True)
            href = a.get("href", "")
            if not title or not href:
                continue

            # Filtrage par mots-clés pour réduire le bruit (nav, footer, etc.)
            if keep_keywords:
                text_lower = title.lower()
                if not any(kw.lower() in text_lower for kw in keep_keywords):
                    continue

            # Résolution des URLs relatives
            if href.startswith("/"):
                base = "/".join(page_cfg["url"].split("/")[:3])  # https://domaine.com
                href = base + href
            elif not href.startswith("http"):
                continue

            items.append({
                "id": make_id(href),
                "title": title,
                "link": href,
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
