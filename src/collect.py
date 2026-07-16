"""
Collecte les items depuis les flux RSS et les pages web configurées
dans config.yaml.

Types de sources pris en charge :

1. rss_feeds
2. scrape_pages avec type: cards
3. content_pages avec type: monthly_release_notes

Format normalisé retourné :

{
    "id": str,
    "title": str,
    "description": str,
    "content": str,
    "link": str,
    "source": str,
    "published": str,
    "topic": str,
    "summarize_with_llm": bool
}
"""

import hashlib
import logging
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

import feedparser
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

DEBUG_DIR = Path(__file__).resolve().parents[1] / "data" / "debug"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "Chrome/126.0 Safari/537.36 "
        "BoomiWatch/1.0"
    )
}

TIMEOUT = 30

ENGLISH_MONTHS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]


def make_id(value: str) -> str:
    """
    Génère un identifiant stable et court.

    Pour les cartes et flux RSS, la valeur est généralement l'URL.
    Pour les Release Notes, la valeur inclut la source, le topic,
    l'année et le mois.
    """
    return hashlib.sha256(
        value.encode("utf-8")
    ).hexdigest()[:16]


def clean_text(value: str) -> str:
    """
    Nettoie les espaces, tabulations et retours à la ligne.
    """
    if not value:
        return ""

    return " ".join(value.split()).strip()


def extract_text(
    parent,
    selector: str | None,
    fallback: str = "",
) -> str:
    """
    Extrait le texte du premier élément correspondant au sélecteur,
    à l'intérieur de l'élément parent.
    """
    if not selector:
        return clean_text(fallback)

    element = parent.select_one(selector)

    if not element:
        return clean_text(fallback)

    return clean_text(
        element.get_text(" ", strip=True)
    )


def extract_href(parent, selector: str | None) -> str:
    """
    Extrait href ou ng-href depuis un élément.

    ng-href est utilisé comme fallback pour certaines pages AngularJS.
    """
    if not selector:
        return ""

    element = parent.select_one(selector)

    if not element:
        return ""

    return (
        element.get("href")
        or element.get("ng-href")
        or ""
    ).strip()


def resolve_url(page_url: str, href: str) -> str:
    """
    Transforme une URL relative en URL absolue.

    urljoin conserve les URLs déjà absolues et prend également
    en charge les liens vers d'autres domaines.
    """
    if not href:
        return ""

    return urljoin(page_url, href)


def matches_keywords(
    title: str,
    description: str,
    link: str,
    keywords: list[str],
) -> bool:
    """
    Vérifie si un item correspond à au moins un mot-clé.

    Si la liste de mots-clés est vide, aucun filtrage n'est appliqué.
    """
    if not keywords:
        return True

    searchable_text = " ".join([
        title,
        description,
        link,
    ]).casefold()

    return any(
        keyword.casefold() in searchable_text
        for keyword in keywords
    )


def url_matches_patterns(
    url: str,
    allowed_patterns: list[str],
    excluded_patterns: list[str],
) -> bool:
    """
    Applique les filtres allowed_url_patterns et
    excluded_url_patterns d'une source.
    """
    normalized_url = url.casefold()

    if allowed_patterns:
        is_allowed = any(
            pattern.casefold() in normalized_url
            for pattern in allowed_patterns
        )

        if not is_allowed:
            return False

    is_excluded = any(
        pattern.casefold() in normalized_url
        for pattern in excluded_patterns
    )

    return not is_excluded


def get_request_settings(config: dict) -> tuple[int, dict]:
    """
    Récupère les paramètres HTTP définis dans config.yaml.
    """
    collection_config = config.get("collection", {})

    timeout = collection_config.get(
        "request_timeout_seconds",
        TIMEOUT,
    )

    user_agent = collection_config.get(
        "user_agent",
        HEADERS["User-Agent"],
    )

    headers = {
        "User-Agent": user_agent,
        "Accept": (
            "text/html,application/xhtml+xml,"
            "application/xml;q=0.9,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }

    return timeout, headers


def _save_debug_html(source_name: str, topic: str, year: int, month: str, html: str) -> Path:
    """
    Sauvegarde le HTML rendu quand aucune bullet point n'a été trouvé.
    """
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", f"{topic or source_name}_{year}_{month}")
    debug_path = DEBUG_DIR / f"{safe_name}.html"
    debug_path.write_text(html, encoding="utf-8")
    return debug_path


def fetch_page_html(url: str, page_cfg: dict, config: dict) -> tuple[str, str]:
    """
    Charge une page HTML avec requests + BeautifulSoup.
    """
    timeout, headers = get_request_settings(config)
    page_name = page_cfg.get("name", "source inconnue")

    logger.info("Chargement HTML statique via requests pour '%s' depuis %s", page_name, url)
    response = requests.get(
        url,
        headers=headers,
        timeout=timeout,
        allow_redirects=True,
    )
    response.raise_for_status()
    return response.text, response.url


def collect_rss(
    feed_cfg: dict,
    config: dict,
) -> list[dict]:
    """
    Collecte les entrées d'un flux RSS.
    """
    items = []
    name = feed_cfg["name"]
    url = feed_cfg["url"]

    timeout, headers = get_request_settings(config)

    try:
        logger.info(
            "Collecte RSS de '%s' depuis %s",
            name,
            url,
        )

        response = requests.get(
            url,
            headers=headers,
            timeout=timeout,
            allow_redirects=True,
        )
        response.raise_for_status()

        parsed = feedparser.parse(response.content)

        logger.info(
            "Source RSS '%s': status=%s, "
            "content_type=%s, entries=%d",
            name,
            response.status_code,
            response.headers.get(
                "Content-Type",
                "unknown",
            ),
            len(parsed.entries),
        )

        if parsed.bozo and not parsed.entries:
            logger.warning(
                "Flux RSS invalide ou vide pour %s. "
                "URL finale: %s",
                name,
                response.url,
            )
            return items

        for entry in parsed.entries:
            link = clean_text(
                entry.get("link", "")
            )
            title = clean_text(
                entry.get("title", "")
            )

            if not link or not title:
                continue

            description = clean_text(
                entry.get("summary", "")
                or entry.get("description", "")
            )

            items.append({
                "id": make_id(link),
                "title": title,
                "description": description,
                "content": description,
                "link": link,
                "source": name,
                "published": clean_text(
                    entry.get("published", "")
                ),
                "topic": "",
                "summarize_with_llm": True,
            })

    except requests.RequestException as exc:
        logger.error(
            "Erreur HTTP lors de la collecte RSS de '%s': %s",
            name,
            exc,
        )

    except Exception as exc:
        logger.exception(
            "Erreur lors du parsing RSS de '%s': %s",
            name,
            exc,
        )

    return items


def collect_cards(
    page_cfg: dict,
    keep_keywords: list[str],
    config: dict,
) -> list[dict]:
    """
    Collecte une page composée de cartes.

    Exemple Boomi Community :

    item_selector: div.card.ng-scope
    title_selector: h3.card-title.ng-binding
    description_selector: p.card-excerpt.ng-binding
    link_selector: a.card-link

    Exemple Product Updates :

    item_selector: div.rc-item
    title_selector: h2.tc-title
    description_selector: div.rc-desc p
    link_selector: a[href]
    """
    items = []

    name = page_cfg["name"]
    page_url = page_cfg["url"]

    item_selector = page_cfg.get(
        "item_selector",
        "div.card",
    )

    title_selector = page_cfg.get(
        "title_selector"
    )

    description_selector = page_cfg.get(
        "description_selector"
    )

    link_selector = page_cfg.get(
        "link_selector"
    )

    max_items = page_cfg.get("max_items")

    title_from_item_text = page_cfg.get(
        "title_from_item_text",
        False,
    )

    link_from_item_href = page_cfg.get(
        "link_from_item_href",
        False,
    )

    allowed_patterns = page_cfg.get(
        "allowed_url_patterns",
        [],
    )

    excluded_patterns = page_cfg.get(
        "excluded_url_patterns",
        [],
    )

    try:
        logger.info(
            "Scraping des cartes de '%s' depuis %s (mode=requests)",
            name,
            page_url,
        )

        html, resolved_url = fetch_page_html(
            page_url,
            page_cfg,
            config,
        )

        soup = BeautifulSoup(
            html,
            "html.parser",
        )

        cards = soup.select(item_selector)

        logger.info(
            "Source '%s': %d cartes trouvées avec '%s', URL finale=%s",
            name,
            len(cards),
            item_selector,
            resolved_url,
        )

        for card in cards:
            if title_from_item_text:
                title = clean_text(
                    card.get_text(" ", strip=True)
                )
            else:
                title = extract_text(
                    card,
                    title_selector,
                )

            description = extract_text(
                card,
                description_selector,
            )

            if link_from_item_href:
                href = (
                    card.get("href")
                    or card.get("ng-href")
                    or ""
                ).strip()
            else:
                href = extract_href(
                    card,
                    link_selector,
                )

            link = resolve_url(
                resolved_url,
                href,
            )

            if not title:
                logger.debug(
                    "Carte ignorée dans '%s': titre vide",
                    name,
                )
                continue

            if not link:
                logger.debug(
                    "Carte ignorée dans '%s': "
                    "lien vide pour '%s'",
                    name,
                    title,
                )
                continue

            if not url_matches_patterns(
                link,
                allowed_patterns,
                excluded_patterns,
            ):
                logger.debug(
                    "Lien rejeté par les patterns pour '%s': %s",
                    name,
                    link,
                )
                continue

            # Par défaut, le filtre global est appliqué.
            # Une source peut le désactiver avec:
            # apply_keyword_filter: false
            apply_keyword_filter = page_cfg.get(
                "apply_keyword_filter",
                True,
            )

            if (
                apply_keyword_filter
                and not matches_keywords(
                    title,
                    description,
                    link,
                    keep_keywords,
                )
            ):
                logger.debug(
                    "Carte rejetée par mots-clés dans '%s': %s",
                    name,
                    title,
                )
                continue

            items.append({
                "id": make_id(link),
                "title": title,
                "description": description,
                "content": description,
                "link": link,
                "source": name,
                "published": "",
                "topic": "",
                "summarize_with_llm": True,
            })

            if max_items and len(items) >= max_items:
                break

        logger.info(
            "Source '%s': %d cartes trouvées, "
            "%d items retenus",
            name,
            len(cards),
            len(items),
        )

    except requests.RequestException as exc:
        logger.error(
            "Erreur HTTP lors du scraping de '%s': %s",
            name,
            exc,
        )

    except Exception as exc:
        logger.exception(
            "Erreur lors du scraping de '%s': %s",
            name,
            exc,
        )

    return items


def collect_generic_links(
    page_cfg: dict,
    keep_keywords: list[str],
    config: dict,
) -> list[dict]:
    """
    Conserve la compatibilité avec l'ancien format config.yaml,
    où scrape_pages utilisait seulement link_selector.
    """
    items = []

    name = page_cfg["name"]
    page_url = page_cfg["url"]
    link_selector = page_cfg.get(
        "link_selector",
        "a",
    )

    max_items = page_cfg.get("max_items")

    allowed_patterns = page_cfg.get(
        "allowed_url_patterns",
        [],
    )

    excluded_patterns = page_cfg.get(
        "excluded_url_patterns",
        [],
    )

    try:
        logger.info(
            "Scraping des liens de '%s' depuis %s",
            name,
            page_url,
        )

        html, resolved_url = fetch_page_html(
            page_url,
            page_cfg,
            config,
        )

        soup = BeautifulSoup(
            html,
            "html.parser",
        )

        links = soup.select(link_selector)

        for element in links:
            title = clean_text(
                element.get_text(" ", strip=True)
            )

            href = (
                element.get("href")
                or element.get("ng-href")
                or ""
            ).strip()

            link = resolve_url(
                resolved_url,
                href,
            )

            if not title or not link:
                continue

            if not url_matches_patterns(
                link,
                allowed_patterns,
                excluded_patterns,
            ):
                continue

            if not matches_keywords(
                title,
                "",
                link,
                keep_keywords,
            ):
                continue

            items.append({
                "id": make_id(link),
                "title": title,
                "description": "",
                "content": "",
                "link": link,
                "source": name,
                "published": "",
                "topic": "",
                "summarize_with_llm": True,
            })

            if max_items and len(items) >= max_items:
                break

        logger.info(
            "Source '%s': %d liens trouvés, %d retenus",
            name,
            len(links),
            len(items),
        )

    except requests.RequestException as exc:
        logger.error(
            "Erreur HTTP lors du scraping de '%s': %s",
            name,
            exc,
        )

    except Exception as exc:
        logger.exception(
            "Erreur lors du scraping de '%s': %s",
            name,
            exc,
        )

    return items


def build_monthly_url(
    url_template: str,
    current_date: datetime | None = None,
) -> tuple[str, int, str]:
    """
    Remplace automatiquement {year} et {month} dans l'URL.

    Exemple :

    Platform?year={year}&month={month}

    devient :

    Platform?year=2026&month=July
    """
    if current_date is None:
        current_date = datetime.now()

    year = current_date.year
    month = ENGLISH_MONTHS[
        current_date.month - 1
    ]

    final_url = url_template.replace("&amp;", "&").replace("&#38;", "&")
    final_url = final_url.format(
        year=year,
        month=month,
    )

    return final_url, year, month


def extract_release_content(
    soup: BeautifulSoup,
    page_cfg: dict,
) -> tuple[str, list[str], str]:
    """
    Extrait le titre, les bullet points et le contenu principal
    d'une page de Release Notes.
    """
    content_selector = page_cfg.get(
        "content_selector",
        "main",
    )

    title_selector = page_cfg.get(
        "title_selector",
        "main h1",
    )

    bullet_selector = page_cfg.get(
        "bullet_selector",
        "main li",
    )

    excluded_selectors = page_cfg.get(
        "excluded_selectors",
        [],
    )

    for selector in excluded_selectors:
        for element in soup.select(selector):
            element.decompose()

    title_element = soup.select_one(
        title_selector
    )

    title = (
        clean_text(
            title_element.get_text(
                " ",
                strip=True,
            )
        )
        if title_element
        else ""
    )

    bullets = []
    for bullet in soup.select(bullet_selector):
        bullet_text = clean_text(
            bullet.get_text(" ", strip=True)
        )
        if bullet_text:
            bullets.append(bullet_text)

    if not bullets:
        for candidate in soup.select("article, main, .markdown, .theme-doc-markdown"):
            for li in candidate.select("li"):
                bullet_text = clean_text(li.get_text(" ", strip=True))
                if bullet_text and len(bullet_text.split()) >= 3:
                    bullets.append(bullet_text)

    bullets = list(dict.fromkeys(bullets))

    content_element = soup.select_one(
        content_selector
    )

    full_content = (
        clean_text(
            content_element.get_text(
                " ",
                strip=True,
            )
        )
        if content_element
        else ""
    )

    if not full_content and not bullets:
        full_content = clean_text(soup.get_text(" ", strip=True))

    if not title:
        title = clean_text(soup.title.get_text(" ", strip=True)) if soup.title else ""

    return title, bullets, full_content


def collect_monthly_release_notes(
    page_cfg: dict,
    config: dict,
) -> list[dict]:
    """
    Collecte une page mensuelle de Boomi Release Notes.

    Un seul item est créé par topic et par mois.
    Le contenu des bullet points est envoyé ensuite au LLM.
    """
    items = []

    name = page_cfg["name"]
    topic = page_cfg.get("topic", name)

    url_template = page_cfg.get(
        "url_template"
    )

    if not url_template:
        logger.error(
            "url_template absent pour '%s'",
            name,
        )
        return items

    final_url, year, month = build_monthly_url(
        url_template
    )

    collection_config = config.get(
        "collection",
        {},
    )

    max_content_characters = collection_config.get(
        "max_content_characters_per_page",
        15000,
    )

    require_bullets = collection_config.get(
        "require_bullet_items_for_release_notes",
        True,
    )

    try:
        logger.info(
            "Collecte des Release Notes '%s' pour %s %d",
            topic,
            month,
            year,
        )

        logger.info(
            "URL mensuelle générée: %s",
            final_url,
        )

        html, resolved_url = fetch_page_html(
            final_url,
            page_cfg,
            config,
        )

        soup = BeautifulSoup(
            html,
            "html.parser",
        )

        title, bullets, full_content = (
            extract_release_content(
                soup,
                page_cfg,
            )
        )

        logger.info(
            "Release Notes '%s': %d bullet points trouvés, URL finale=%s",
            topic,
            len(bullets),
            resolved_url,
        )

        if not bullets and require_bullets:
            debug_path = _save_debug_html(
                name,
                topic,
                year,
                month,
                html,
            )
            logger.warning(
                "Aucun bullet point trouvé pour '%s' avec le sélecteur '%s'. HTML enregistré dans %s",
                name,
                page_cfg.get(
                    "bullet_selector",
                    "main li",
                ),
                debug_path,
            )

        if bullets:
            content = "\n".join(
                f"- {bullet}"
                for bullet in bullets
            )
        else:
            content = full_content or title or f"Release notes for {month} {year}"

        content = content[
            :max_content_characters
        ]

        if not title:
            title = (
                f"{topic} Release Notes "
                f"for {month} {year}"
            )

        stable_id_value = (
            f"{name}|{topic}|{year}|{month}"
        )

        items.append({
            "id": make_id(stable_id_value),
            "title": title or f"{topic} Release Notes for {month} {year}",
            "description": content,
            "content": content,
            "link": resolved_url or final_url,
            "source": name,
            "published": f"{month} {year}",
            "topic": topic,
            "summarize_with_llm": page_cfg.get(
                "summarize_with_llm",
                True,
            ),
        })

        logger.info(
            "Source '%s': %d items retournés pour %s %d",
            name,
            len(items),
            month,
            year,
        )

    except requests.RequestException as exc:
        logger.error(
            "Erreur HTTP pour les Release Notes '%s': %s",
            name,
            exc,
        )

    except Exception as exc:
        logger.exception(
            "Erreur pendant la collecte des "
            "Release Notes '%s': %s",
            name,
            exc,
        )

    return items


def collect_scrape(
    page_cfg: dict,
    keep_keywords: list[str],
    config: dict,
) -> list[dict]:
    """
    Oriente la source scrape_pages vers le collecteur correspondant.
    """
    page_type = page_cfg.get(
        "type",
        "links",
    ).casefold()

    if page_type == "cards":
        return collect_cards(
            page_cfg,
            keep_keywords,
            config,
        )

    return collect_generic_links(
        page_cfg,
        keep_keywords,
        config,
    )


def collect_content_page(
    page_cfg: dict,
    config: dict,
) -> list[dict]:
    """
    Oriente une entrée content_pages vers le collecteur approprié.
    """
    page_type = page_cfg.get(
        "type",
        "",
    ).casefold()

    if page_type == "monthly_release_notes":
        return collect_monthly_release_notes(
            page_cfg,
            config,
        )

    logger.warning(
        "Type content_pages non reconnu pour '%s': %s",
        page_cfg.get("name", "source inconnue"),
        page_type,
    )

    return []


def collect_all(config: dict) -> list[dict]:
    """
    Collecte toutes les sources configurées et effectue
    une déduplication intra-run.
    """
    all_items = []

    rss_sources = config.get(
        "rss_feeds",
        [],
    )

    scrape_sources = config.get(
        "scrape_pages",
        [],
    )

    content_sources = config.get(
        "content_pages",
        [],
    )

    keep_keywords = config.get(
        "keep_keywords",
        [],
    )

    logger.info(
        "Sources configurées: %d RSS, "
        "%d pages scrape, %d pages de contenu",
        len(rss_sources),
        len(scrape_sources),
        len(content_sources),
    )

    for feed_cfg in rss_sources:
        all_items.extend(
            collect_rss(
                feed_cfg,
                config,
            )
        )

    for page_cfg in scrape_sources:
        all_items.extend(
            collect_scrape(
                page_cfg,
                keep_keywords,
                config,
            )
        )

    for page_cfg in content_sources:
        all_items.extend(
            collect_content_page(
                page_cfg,
                config,
            )
        )

    logger.info(
        "%d items collectés avant déduplication",
        len(all_items),
    )

    # Déduplication intra-run.
    # Le premier item rencontré est conservé.
    unique_items = {}

    for item in all_items:
        item_id = item["id"]

        if item_id not in unique_items:
            unique_items[item_id] = item

    result = list(unique_items.values())

    logger.info(
        "%d items conservés après déduplication intra-run",
        len(result),
    )

    return result




if __name__ == "__main__":
    import json
    from pathlib import Path

    import yaml

    root_dir = Path(__file__).resolve().parents[1]
    config_path = root_dir / "config.yaml"

    with config_path.open(
        "r",
        encoding="utf-8",
    ) as file:
        configuration = yaml.safe_load(file)

    collected_items = collect_all(configuration)

    print(
        json.dumps(
            collected_items,
            ensure_ascii=False,
            indent=2,
        )
    )