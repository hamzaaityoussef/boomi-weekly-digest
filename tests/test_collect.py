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
        "https://help.boomi.com/docs/Atomsphere/Release_Notes/Platform/?year={year}&month={month}",
        fixed_now,
    )

    assert url == "https://help.boomi.com/docs/Atomsphere/Release_Notes/Platform/?year=2026&month=July"


def test_collect_scrape_supports_item_and_nested_selectors(monkeypatch):
    html = """
    <html><body>
      <div class="rc-item">
        <h2 class="tc-title">Latest release</h2>
        <p class="rc-desc">A useful description</p>
        <a href="/releases/latest">Read more</a>
      </div>
      <div class="rc-item">
        <h2 class="tc-title">Another release</h2>
        <p class="rc-desc">Another useful description</p>
        <a href="https://example.com/another">Read more</a>
      </div>
    </body></html>
    """

    def fake_get(url, headers=None, timeout=None):
        return DummyResponse(html)

    monkeypatch.setattr("src.collect.requests.get", fake_get)

    page_cfg = {
        "name": "Boomi Product Updates",
        "url": "https://boomi.com/product-updates/",
        "item_selector": ".rc-item",
        "title_selector": "h2.tc-title",
        "description_selector": "p.rc-desc",
        "link_selector": "a",
    }

    items = collect_scrape(page_cfg, [])

    assert len(items) == 2
    assert items[0]["title"] == "Latest release"
    assert items[0]["description"] == "A useful description"
    assert items[0]["link"] == "https://boomi.com/releases/latest"
    assert items[1]["link"] == "https://example.com/another"
