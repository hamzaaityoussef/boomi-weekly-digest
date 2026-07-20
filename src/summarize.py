"""
Résumé + classification des nouveaux items via Gemini API.
Gère les rate limits avec retry exponentiel et traitement par lots.
"""
import json
import logging
import os
import time

import requests

logger = logging.getLogger(__name__)


DEFAULT_GEMINI_MODEL = "gemini-flash-lite-latest"
BATCH_SIZE = 8
MAX_RETRIES = 5

SYSTEM_PROMPT = """Tu es un assistant qui aide une équipe de data engineers travaillant avec Boomi \
(iPaaS d'intégration) à suivre les nouveautés de la plateforme.

Pour chaque item fourni, tu dois produire :
- un résumé en français, 2 à 3 phrases courtes, factuel, basé UNIQUEMENT sur le titre \
  et/ou la description fournie (ne pas halluciner de détails absents du texte source)
- une catégorie parmi : {categories}
- un niveau d'importance : "haute", "moyenne" ou "basse" \
  (haute = sécurité, breaking change, dépréciation ; moyenne = nouveau connecteur, nouvelle feature ; \
  basse = amélioration mineure)

Réponds UNIQUEMENT avec un objet JSON valide, sans texte avant/après, sans balises markdown, \
au format suivant :
{{
  "items": [
    {{"id": "...", "summary": "...", "category": "...", "importance": "..."}}
  ]
}}
"""


def _gemini_model() -> str:
    return os.environ.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL).strip() or DEFAULT_GEMINI_MODEL


def _fallback_local(items: list[dict], categories: list[str]) -> list[dict]:
    return [
        {
            **it,
            "summary": it.get("title", "Nouveau contenu Boomi"),
            "category": categories[0] if categories else "Autre",
            "importance": "moyenne",
        }
        for it in items
    ]


def _retry_after_seconds(response: requests.Response, attempt: int) -> float:
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            return max(float(retry_after), 1.0)
        except ValueError:
            pass

    try:
        message = response.json().get("error", {}).get("message", "")
        if "retry in" in message.lower():
            fragment = message.lower().split("retry in", 1)[1].strip()
            seconds = float(fragment.split("s", 1)[0].strip())
            return max(seconds, 1.0)
    except (ValueError, AttributeError, json.JSONDecodeError, IndexError):
        pass

    return float(2 ** attempt)


def _call_gemini_batch(items: list[dict], categories: list[str]) -> list[dict]:
    api_key = os.environ.get("GOOGLE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "GOOGLE_API_KEY manquant. Créez une clé sur https://aistudio.google.com/apikey"
        )

    model = _gemini_model()
    payload_items = []
    for it in items:
        entry = {"id": it["id"], "title": it["title"], "source": it["source"]}
        if it.get("use_description") and it.get("description"):
            entry["description"] = it["description"]
        payload_items.append(entry)

    user_payload = json.dumps(payload_items, ensure_ascii=False)
    system_prompt = SYSTEM_PROMPT.format(categories=", ".join(categories))
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": f"{system_prompt}\n\nVoici les items à traiter :\n{user_payload}"}],
            }
        ],
        "generationConfig": {"temperature": 0.2},
    }

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}

    for attempt in range(MAX_RETRIES):
        response = requests.post(url, headers=headers, json=payload, timeout=60)

        if response.status_code in (429, 503):
            wait_time = _retry_after_seconds(response, attempt)
            logger.warning(
                "Gemini %s (%s), attente %.1fs avant retry %d/%d...",
                response.status_code,
                model,
                wait_time,
                attempt + 1,
                MAX_RETRIES,
            )
            time.sleep(wait_time)
            continue

        if response.status_code >= 400:
            try:
                detail = response.json().get("error", {}).get("message", response.text)
            except json.JSONDecodeError:
                detail = response.text
            raise RuntimeError(f"Gemini HTTP {response.status_code}: {detail[:300]}")

        data = response.json()
        raw = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        return _parse_llm_response(raw, items)

    raise RuntimeError(f"Gemini indisponible après {MAX_RETRIES} tentatives (modèle {model})")


def _parse_llm_response(raw: str, items: list[dict]) -> list[dict]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.error("Réponse LLM non-JSON, fallback sans résumé. Réponse brute : %s", raw[:500])
        return _fallback_local(items, [])

    enrich_by_id = {e["id"]: e for e in parsed.get("items", [])}
    enriched = []
    for it in items:
        extra = enrich_by_id.get(it["id"], {})
        enriched.append({
            **it,
            "summary": extra.get("summary", it["title"]),
            "category": extra.get("category", "Autre"),
            "importance": extra.get("importance", "moyenne"),
        })
    return enriched


def summarize_items(items: list[dict], categories: list[str]) -> list[dict]:
    """Enrichit chaque item avec résumé, catégorie et importance via Gemini."""
    if not items:
        return []

    model = _gemini_model()
    logger.info("Résumé via Gemini (%s, %d items)...", model, len(items))

    enriched: list[dict] = []
    fallback_batches = 0
    for start in range(0, len(items), BATCH_SIZE):
        batch = items[start : start + BATCH_SIZE]
        try:
            enriched.extend(_call_gemini_batch(batch, categories))
        except Exception as exc:
            fallback_batches += 1
            logger.warning(
                "Échec Gemini sur le lot %d-%d : %s",
                start + 1,
                start + len(batch),
                exc,
            )
            enriched.extend(_fallback_local(batch, categories))

        if start + BATCH_SIZE < len(items):
            time.sleep(1)

    if fallback_batches:
        logger.warning(
            "%d lot(s) traité(s) en fallback local — lancez : python scripts/test_gemini.py",
            fallback_batches,
        )

    return enriched