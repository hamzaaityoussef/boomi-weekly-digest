"""
Point d'entrée : collecte -> dédup -> résumé (Groq) -> envoi Teams -> mise à jour historique.
Usage : python src/main.py
"""
import json
import logging
import os
import sys

import yaml
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(__file__))
from collect import collect_all
from summarize import summarize_items
from notify import send_to_teams

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config.yaml")
SEEN_PATH = os.path.join(ROOT, "data", "seen_items.json")


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_seen_ids() -> set:
    if not os.path.exists(SEEN_PATH):
        return set()
    with open(SEEN_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return set(data.get("seen_ids", []))


def save_seen_ids(seen_ids: set) -> None:
    with open(SEEN_PATH, "w", encoding="utf-8") as f:
        json.dump({"seen_ids": sorted(seen_ids)}, f, ensure_ascii=False, indent=2)


def main():
    load_dotenv()  # utile en local ; en CI, les secrets sont déjà dans l'environnement

    config = load_config()

    logger.info("Chargement de l'historique...")
    seen_ids = load_seen_ids()

    logger.info("Collecte des sources Boomi...")
    all_items = collect_all(config)
    logger.info("%d items collectés au total (avant dédup).", len(all_items))

    new_items = [it for it in all_items if it["id"] not in seen_ids]
    logger.info("%d nouveaux items détectés.", len(new_items))

    if not new_items:
        logger.info("Rien de nouveau cette semaine, pas d'envoi.")
        return

    logger.info("Résumé et classification via Groq...")
    enriched_items = summarize_items(new_items, config.get("categories", []))

    logger.info("Envoi du digest vers Teams...")
    send_to_teams(enriched_items)

    # On ne marque comme "vu" qu'après un envoi réussi, pour ne rien perdre en cas d'erreur
    seen_ids.update(it["id"] for it in new_items)
    save_seen_ids(seen_ids)
    logger.info("Historique mis à jour (%d ids au total).", len(seen_ids))


if __name__ == "__main__":
    main()
