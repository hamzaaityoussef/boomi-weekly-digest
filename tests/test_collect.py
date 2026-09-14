import os
import sys
from datetime import datetime
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.collect import collect_scrape, resolve_url_template


class DummyResponse:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_resolve_url_template_uses_current_month_and_year(monkeypatch):
    fixed_now = datetime(2026, 7, 15)
    url = resolve_url_template(
      "https://boomi.com/blog/{month_slug}-{month}-{year}",
        fixed_now,
    )

    assert url == "https://boomi.com/blog/july-July-2026"


def test_collect_scrape_supports_item_and_nested_selectors(monkeypatch):
    html = """
    <html><body>
      <div class="rc-slide-item">
        <div class="rc-item">
          <h2 class="rc-title">Latest release</h2>
          <p class="rc-summary">A useful description</p>
          <a href="/releases/latest">Read more</a>
        </div>
      </div>
      <div class="rc-slide-item">
        <div class="rc-item">
          <h2 class="rc-title">Another release</h2>
          <p class="rc-summary">Another useful description</p>
          <a href="https://example.com/another">Read more</a>
        </div>
      </div>
    </body></html>
    """

    def fake_get(url, headers=None, timeout=None):
        return DummyResponse(html)

    monkeypatch.setattr("src.collect.requests.get", fake_get)

    page_cfg = {
        "name": "Boomi Product Updates",
        "url": "https://boomi.com/product-updates/",
        "item_selector": ".rc-slide-item .rc-item",
        "title_selector": "h2.rc-title",
        "description_selector": "p.rc-summary",
        "link_selector": "a",
        "no_fallback": True,
    }

    items = collect_scrape(page_cfg, [])

    assert len(items) == 2
    assert items[0]["title"] == "Latest release"
    assert items[0]["description"] == "A useful description"
    assert items[0]["link"] == "https://boomi.com/releases/latest"
    assert items[1]["link"] == "https://example.com/another"


def test_collect_scrape_supports_blog_release_article(monkeypatch):
    html = """
    <html><body>
      <div class="post-detail">
        <div class="post-content">
          <h1>Boomi Integration and Automation Platform Release - September 2026</h1>
          <section class="blog-content-wrapper">
            <p>The September 2026 release includes new platform capabilities.</p>
          </section>
        </div>
      </div>
    </body></html>
    """

    def fake_get(url, headers=None, timeout=None):
        return DummyResponse(html)

    monkeypatch.setattr("src.collect.requests.get", fake_get)

    page_cfg = {
        "name": "Boomi Blog - Platform Release",
        "url": "https://boomi.com/blog/everything-you-want-to-know-about-the-september-2026-boomi-integration-and-automation-platform-release/",
        "item_selector": ".post-detail .post-content",
        "title_selector": "h1",
        "description_selector": ".blog-content-wrapper",
        "page_link": True,
        "use_description": True,
        "keep_keywords": [],
        "no_fallback": True,
    }

    items = collect_scrape(page_cfg, [])

    assert len(items) == 1
    assert items[0]["title"] == "Boomi Integration and Automation Platform Release - September 2026"
    assert "new platform capabilities" in items[0]["description"]
    assert items[0]["link"] == page_cfg["url"]
