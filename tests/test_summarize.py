import os
import unittest
from unittest.mock import patch

from src import summarize


class SummarizeTests(unittest.TestCase):
    def test_resolve_provider_prefers_google_when_google_key_present(self) -> None:
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "fake-google-key", "GROQ_API_KEY": ""}, clear=True):
            self.assertEqual(summarize.resolve_provider(), "google")

    def test_summarize_items_falls_back_without_provider(self) -> None:
        items = [{"id": "abc", "title": "New release", "source": "Test"}]
        with patch.dict(os.environ, {}, clear=True):
            result = summarize.summarize_items(items, ["Autre"])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["summary"], "New release")
        self.assertEqual(result[0]["category"], "Autre")
        self.assertEqual(result[0]["importance"], "moyenne")


if __name__ == "__main__":
    unittest.main()
