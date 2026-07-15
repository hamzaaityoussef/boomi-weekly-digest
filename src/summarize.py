"""
Résumé + classification des nouveaux items via l'API Groq (gratuite, sans carte bancaire).
Modèle : llama-3.3-70b-versatile
"""
import json
import logging
import os

from groq import Groq

logger = logging.getLogger(__name__)

MODEL = "llama-3.3-70b-versatile"

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


def summarize_items(items: list[dict], categories: list[str]) -> list[dict]:
    """Enrichit chaque item avec un résumé, une catégorie et un niveau d'importance."""
    if not items:
        return []

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
        model=MODEL,
        temperature=0.2,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Voici les items à traiter :\n{user_payload}"},
        ],
    )

    raw = completion.choices[0].message.content.strip()
    # Sécurité : au cas où le modèle ajoute des balises markdown malgré la consigne
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.error("Réponse LLM non-JSON, fallback sans résumé. Réponse brute : %s", raw[:500])
        return [
            {**it, "summary": it["title"], "category": "Autre", "importance": "moyenne"}
            for it in items
        ]

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
