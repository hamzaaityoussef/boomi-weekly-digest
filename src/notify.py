"""
Envoi du digest vers Microsoft Teams.

IMPORTANT : les anciens "Incoming Webhooks" (connecteurs Office 365 / MessageCard)
sont retirés depuis avril 2026. Il faut utiliser le nouveau système Workflows
(Power Automate) avec le trigger "When a Teams webhook request is received",
qui attend un payload au format Adaptive Card. Voir README pour la config côté Teams.
"""
import logging
import os

import requests

logger = logging.getLogger(__name__)

IMPORTANCE_COLOR = {
    "haute": "Attention",
    "moyenne": "Warning",
    "basse": "Good",
}
IMPORTANCE_EMOJI = {
    "haute": "🔴",
    "moyenne": "🟠",
    "basse": "🟢",
}


def build_adaptive_card(items: list[dict]) -> dict:
    # Regroupement par catégorie
    by_category: dict[str, list[dict]] = {}
    for it in items:
        by_category.setdefault(it["category"], []).append(it)

    body = [
        {
            "type": "TextBlock",
            "text": " Veille Boomi — Nouveautés de la semaine",
            "size": "Large",
            "weight": "Bolder",
        },
        {
            "type": "TextBlock",
            "text": f"{len(items)} nouvel(le)s item(s) détecté(s)",
            "isSubtle": True,
            "spacing": "None",
        },
    ]

    for category, cat_items in by_category.items():
        body.append({
            "type": "TextBlock",
            "text": category,
            "weight": "Bolder",
            "size": "Medium",
            "spacing": "Medium",
        })
        for it in cat_items:
            emoji = IMPORTANCE_EMOJI.get(it["importance"], "⚪")
            body.append({
                "type": "TextBlock",
                "text": f"{emoji} [{it['title']}]({it['link']})",
                "wrap": True,
            })
            body.append({
                "type": "TextBlock",
                "text": it["summary"],
                "wrap": True,
                "isSubtle": True,
                "spacing": "None",
                "size": "Small",
            })

    card = {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.4",
        "body": body,
    }

    # Format attendu par le trigger "When a Teams webhook request is received"
    payload = {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": card,
            }
        ],
    }
    return payload


def _should_skip_ssl_verification() -> bool:
    return os.environ.get("TEAMS_SKIP_SSL_VERIFY", "").strip().lower() in {"1", "true", "yes", "on"}


def send_to_teams(items: list[dict]) -> None:
    if not items:
        logger.info("Aucun nouvel item, pas d'envoi Teams.")
        return

    webhook_url = os.environ.get("TEAMS_WEBHOOK_URL")
    if not webhook_url:
        raise RuntimeError("TEAMS_WEBHOOK_URL manquant dans l'environnement")

    if not webhook_url.startswith(("http://", "https://")):
        raise RuntimeError(
            f"TEAMS_WEBHOOK_URL invalide : {webhook_url!r}. Attendu une URL complète de type https://..."
        )

    payload = build_adaptive_card(items)
    try:
        if _should_skip_ssl_verification():
            logger.warning("Vérification SSL désactivée pour Teams via TEAMS_SKIP_SSL_VERIFY=1")
            resp = requests.post(webhook_url, json=payload, timeout=15, verify=False)
        else:
            resp = requests.post(webhook_url, json=payload, timeout=15)
    except requests.exceptions.SSLError as exc:
        logger.warning("Échec de vérification SSL avec Teams, nouvelle tentative avec verify=False : %s", exc)
        resp = requests.post(webhook_url, json=payload, timeout=15, verify=False)

    if resp.status_code >= 300:
        logger.error("Échec envoi Teams (%s) : %s", resp.status_code, resp.text[:500])
        resp.raise_for_status()

    logger.info("Digest envoyé à Teams avec succès (%d items).", len(items))