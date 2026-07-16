import sys
from pathlib import Path

import yaml
from bs4 import BeautifulSoup

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from collect import build_monthly_url, fetch_page_html  # noqa: E402

CONFIG_PATH = ROOT_DIR / "config.yaml"


def load_config():
    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file)


def print_card_preview(source, html):
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select(source.get("item_selector", "div"))
    print(f"  - cards found: {len(cards)}")
    for card in cards[:3]:
        title = card.get_text(" ", strip=True)[:160]
        print(f"    * {title}")


def print_release_preview(source, html):
    soup = BeautifulSoup(html, "html.parser")
    bullet_selector = source.get("bullet_selector", "main li")
    bullets = soup.select(bullet_selector)
    print(f"  - bullets found: {len(bullets)}")
    for bullet in bullets[:3]:
        text = bullet.get_text(" ", strip=True)[:200]
        print(f"    * {text}")


def main():
    config = load_config()
    print(f"Configuration: {CONFIG_PATH}")

    for source in config.get("scrape_pages", []):
        print("\n" + "=" * 80)
        print(f"SCRAPE SOURCE: {source['name']}")
        print(f"URL: {source['url']}")
        try:
            html, resolved_url = fetch_page_html(source["url"], source, config)
            print(f"Resolved URL: {resolved_url}")
            print_card_preview(source, html)
        except Exception as error:  # pragma: no cover - diagnostic script
            print(f"ERROR: {error}")

    for source in config.get("content_pages", []):
        if source.get("type") != "monthly_release_notes":
            continue
        print("\n" + "=" * 80)
        print(f"RELEASE SOURCE: {source['name']}")
        url, year, month = build_monthly_url(source.get("url_template", ""))
        print(f"Generated URL: {url}")
        print(f"Contains &month=: {'&month=' in url}")
        print(f"Contains &amp;month=: {'&amp;month=' in url}")
        try:
            html, resolved_url = fetch_page_html(url, source, config)
            print(f"Resolved URL: {resolved_url}")
            print_release_preview(source, html)
        except Exception as error:  # pragma: no cover - diagnostic script
            print(f"ERROR: {error}")


if __name__ == "__main__":
    main()
