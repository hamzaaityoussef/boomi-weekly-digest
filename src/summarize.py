"""
Résumé + classification des nouveaux items via un provider LLM configurable.
Supporte Groq et Gemini, avec fallback local si le provider échoue.
"""
import json
import logging
import os

from groq import Groq
import requests

logger = logging.getLogger(__name__)

GROQ_MODEL = "llama-3.3-70b-versatile"
GEMINI_MODEL = "gemini-2.0-flash"

SYSTEM_PROMPT = """Tu es un assistant qui aide une équipe de data engineers travaillant avec Boomi \
(iPaaS d'intégration) à suivre les nouveautés de la plateforme.

Pour chaque item fourni (titre + lien), tu dois produire :
- un résumé en français, 1 à 2 phrases, factuel, basé UNIQUEMENT sur le titre fourni \
  (ne pas halluciner de détails non présents dans le titre)
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


def _call_groq(items: list[dict], categories: list[str]) -> list[dict]:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY manquant dans l'environnement")

    client = Groq(api_key=api_key)
    user_payload = json.dumps(
        [{"id": it["id"], "title": it["title"], "source": it["source"]} for it in items],
        ensure_ascii=False,
    )
    system_prompt = SYSTEM_PROMPT.format(categories=", ".join(categories))

    completion = client.chat.completions.create(
        model=GROQ_MODEL,
        temperature=0.2,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Voici les items à traiter :\n{user_payload}"},
        ],
    )
    raw = completion.choices[0].message.content.strip()
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return _parse_llm_response(raw, items)


def _call_gemini(items: list[dict], categories: list[str]) -> list[dict]:
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY manquant dans l'environnement")

    user_payload = json.dumps(
        [{"id": it["id"], "title": it["title"], "source": it["source"]} for it in items],
        ensure_ascii=False,
    )
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

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={api_key}"
    response = requests.post(url, json=payload, timeout=30)
    response.raise_for_status()

    data = response.json()
    raw = data["candidates"][0]["content"]["parts"][0]["text"].strip()
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return _parse_llm_response(raw, items)


def _parse_llm_response(raw: str, items: list[dict]) -> list[dict]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
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
    """Enrichit chaque item avec un résumé, une catégorie et un niveau d'importance."""
    if not items:
        return []

    for provider_name, provider_func in (
        ("Gemini", _call_gemini),
        ("Groq", _call_groq),
    ):
        try:
            logger.info("Utilisation du provider %s", provider_name)
            return provider_func(items, categories)
        except Exception as exc:
            logger.warning("Échec de l'appel %s, utilisation du fallback local : %s", provider_name, exc)

    return _fallback_local(items, categories)

