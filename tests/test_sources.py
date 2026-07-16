from pathlib import Path
from urllib.parse import urljoin

import feedparser
import requests
import yaml
from bs4 import BeautifulSoup


ROOT_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT_DIR / "config.yaml"

TIMEOUT = 20

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/126.0 Safari/537.36 "
        "BoomiWatch/1.0"
    )
}


def load_config():
    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file)


def matches_keywords(text, keywords):
    if not keywords:
        return True

    normalized_text = text.casefold()
    return any(keyword.casefold() in normalized_text for keyword in keywords)


def test_rss_source(source):
    name = source["name"]
    url = source["url"]

    print("\n" + "=" * 80)
    print(f"RSS SOURCE: {name}")
    print(f"URL       : {url}")

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )

        content_type = response.headers.get("Content-Type", "unknown")

        print(f"HTTP status : {response.status_code}")
        print(f"Final URL   : {response.url}")
        print(f"Content-Type: {content_type}")
        print(f"Size        : {len(response.content)} bytes")

        parsed_feed = feedparser.parse(response.content)

        print(f"Feed title  : {parsed_feed.feed.get('title', 'N/A')}")
        print(f"Entries     : {len(parsed_feed.entries)}")
        print(f"Bozo        : {parsed_feed.bozo}")

        if parsed_feed.bozo:
            print(f"Parse error : {parsed_feed.get('bozo_exception')}")

        if parsed_feed.entries:
            print("\nFirst entries:")

            for entry in parsed_feed.entries[:5]:
                print(f"  - {entry.get('title', 'Sans titre')}")
                print(f"    {entry.get('link', 'Sans lien')}")

            print("\nRESULT: WORKING RSS")
        else:
            preview = response.text[:200].replace("\n", " ")

            print(f"\nContent preview: {preview}")
            print("\nRESULT: NOT AN RSS FEED OR EMPTY FEED")

    except requests.RequestException as error:
        print(f"\nRESULT: HTTP ERROR: {error}")


def test_scrape_source(source, keywords):
    name = source["name"]
    url = source["url"]
    selector = source.get("link_selector", "a")

    print("\n" + "=" * 80)
    print(f"SCRAPE SOURCE: {name}")
    print(f"URL          : {url}")
    print(f"CSS selector : {selector}")

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )

        content_type = response.headers.get("Content-Type", "unknown")

        print(f"HTTP status : {response.status_code}")
        print(f"Final URL   : {response.url}")
        print(f"Content-Type: {content_type}")
        print(f"Size        : {len(response.content)} bytes")

        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        selected_elements = soup.select(selector)

        valid_links = []
        filtered_links = []
        seen_urls = set()

        for element in selected_elements:
            title = element.get_text(" ", strip=True)
            href = element.get("href")

            if not title or not href:
                continue

            absolute_url = urljoin(response.url, href)

            if absolute_url in seen_urls:
                continue

            seen_urls.add(absolute_url)
            valid_links.append((title, absolute_url))

            searchable_value = f"{title} {absolute_url}"

            if matches_keywords(searchable_value, keywords):
                filtered_links.append((title, absolute_url))

        print(f"Selected elements : {len(selected_elements)}")
        print(f"Valid unique links: {len(valid_links)}")
        print(f"Links after filter: {len(filtered_links)}")

        if filtered_links:
            print("\nFirst retained links:")

            for title, link in filtered_links[:10]:
                print(f"  - {title}")
                print(f"    {link}")

            print("\nRESULT: WORKING")
        elif valid_links:
            print("\nRESULT: PAGE ACCESSIBLE, BUT KEYWORD FILTER REMOVED EVERYTHING")

            print("\nFirst unfiltered links:")

            for title, link in valid_links[:5]:
                print(f"  - {title}")
                print(f"    {link}")
        else:
            print("\nRESULT: PAGE ACCESSIBLE, BUT SELECTOR FOUND NO USABLE LINKS")

    except requests.RequestException as error:
        print(f"\nRESULT: HTTP ERROR: {error}")

    except Exception as error:
        print(f"\nRESULT: PARSING ERROR: {error}")


def main():
    config = load_config()
    keywords = config.get("keep_keywords", [])

    print(f"Configuration: {CONFIG_PATH}")
    print(f"Keywords     : {keywords}")

    rss_sources = config.get("rss_feeds", [])
    scrape_sources = config.get("scrape_pages", [])

    for source in rss_sources:
        test_rss_source(source)

    for source in scrape_sources:
        test_scrape_source(source, keywords)


if __name__ == "__main__":
    main()