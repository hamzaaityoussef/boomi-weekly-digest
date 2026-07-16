"""
Résumé + classification des nouveaux items via une API LLM.
Support : Groq (si GROQ_API_KEY est défini) ou Google Gemini (si GOOGLE_API_KEY est défini).
En cas d'échec, un fallback local simple est utilisé.
"""
import json
import logging
import os

import httpx
import requests
from groq import Groq

logger = logging.getLogger(__name__)

GROQ_MODEL = "llama-3.3-70b-versatile"
GOOGLE_MODEL = os.environ.get("GOOGLE_MODEL", "gemini-2.0-flash")

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


def _should_skip_ssl_verification() -> bool:
    return os.environ.get("GROQ_SKIP_SSL_VERIFY", "").strip().lower() in {"1", "true", "yes", "on"}


def _is_ssl_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(token in message for token in ["ssl", "certificate", "verify failed", "self-signed"])


def create_groq_client(api_key: str):
    if _should_skip_ssl_verification():
        logger.warning("Vérification SSL désactivée pour Groq via GROQ_SKIP_SSL_VERIFY=1")
        return Groq(api_key=api_key, http_client=httpx.Client(verify=False))

    try:
        return Groq(api_key=api_key)
    except Exception as exc:
        if _is_ssl_error(exc):
            logger.warning("Échec de vérification SSL avec Groq, tentative avec verification SSL désactivée.")
            return Groq(api_key=api_key, http_client=httpx.Client(verify=False))
        raise


def _infer_category(title: str, categories: list[str]) -> str:
    text = title.lower()
    if any(k in text for k in ["connector", "connecteur"]):
        return next((c for c in categories if "connecteur" in c.lower()), "Autre")
    if any(k in text for k in ["agent", "ai", "genai", "llm"]):
        return next((c for c in categories if "ia" in c.lower() or "agent" in c.lower()), "Autre")
    if any(k in text for k in ["security", "sécurité", "secure", "vuln"]):
        return next((c for c in categories if "sécurité" in c.lower() or "security" in c.lower()), "Autre")
    if any(k in text for k in ["deprec", "breaking", "obsolete", "retired"]):
        return next((c for c in categories if "dépréci" in c.lower() or "breaking" in c.lower()), "Autre")
    if any(k in text for k in ["api", "management"]):
        return next((c for c in categories if "api" in c.lower()), "Autre")
    return next((c for c in categories if c.lower() == "autre"), "Autre")


def _infer_importance(title: str) -> str:
    text = title.lower()
    if any(k in text for k in ["security", "sécurité", "deprec", "breaking", "obsolete", "retired"]):
        return "haute"
    if any(k in text for k in ["connector", "agent", "ai", "api", "update", "release"]):
        return "moyenne"
    return "basse"


def _fallback_enrichment(items: list[dict], categories: list[str]) -> list[dict]:
    return [
        {
            **it,
            "summary": it["title"],
            "category": _infer_category(it["title"], categories),
            "importance": _infer_importance(it["title"]),
        }
        for it in items
    ]


def resolve_provider() -> str | None:
    if os.environ.get("GOOGLE_API_KEY"):
        return "google"
    if os.environ.get("GROQ_API_KEY"):
        return "groq"
    return None


def _call_google(api_key: str, prompt: str) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GOOGLE_MODEL}:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "responseMimeType": "application/json",
        },
    }
    response = requests.post(url, json=payload, timeout=60)
    response.raise_for_status()
    data = response.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]


def summarize_items(items: list[dict], categories: list[str]) -> list[dict]:
    """Enrichit chaque item avec un résumé, une catégorie et un niveau d'importance."""
    if not items:
        return []

    provider = resolve_provider()
    if provider is None:
        logger.warning("Aucune clé API fournie, utilisation du fallback local")
        return _fallback_enrichment(items, categories)

    try:
        user_payload = json.dumps(
            [{"id": it["id"], "title": it["title"], "source": it["source"]} for it in items],
            ensure_ascii=False,
        )

        system_prompt = SYSTEM_PROMPT.format(categories=", ".join(categories))
        prompt = f"{system_prompt}\n\nVoici les items à traiter :\n{user_payload}"

        if provider == "google":
            logger.info("Utilisation du provider Google Gemini")
            raw = _call_google(os.environ["GOOGLE_API_KEY"], prompt)
        else:
            logger.info("Utilisation du provider Groq")
            client = create_groq_client(os.environ["GROQ_API_KEY"])
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

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            logger.error("Réponse LLM non-JSON, fallback sans résumé. Réponse brute : %s", raw[:500])
            return _fallback_enrichment(items, categories)

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
    except Exception as exc:
        logger.warning("Échec de l'appel LLM, utilisation du fallback local : %s", exc)
        return _fallback_enrichment(items, categories)
