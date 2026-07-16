import sys
import unittest
from pathlib import Path

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from collect import extract_release_content


class ReleaseNotesFallbackTests(unittest.TestCase):
    def test_extract_release_content_uses_page_text_when_no_bullets_exist(self):
        html = """
        <html>
          <head><title>Platform Release Notes</title></head>
          <body>
            <main>
              <h1>Platform Release Notes</h1>
              <p>New capabilities were introduced for the platform.</p>
            </main>
          </body>
        </html>
        """
        soup = BeautifulSoup(html, "html.parser")

        title, bullets, full_content = extract_release_content(
            soup,
            {
                "content_selector": "main",
                "title_selector": "main h1",
                "bullet_selector": "div.release-content-wrapper ul > li",
            },
        )

        self.assertEqual(title, "Platform Release Notes")
        self.assertEqual(bullets, [])
        self.assertIn("New capabilities were introduced for the platform.", full_content)


if __name__ == "__main__":
    unittest.main()
