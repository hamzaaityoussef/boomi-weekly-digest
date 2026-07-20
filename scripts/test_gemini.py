"""
Diagnostic Gemini API — vérifie la clé et un appel minimal.

Usage (depuis la racine du projet) :
    python scripts/test_gemini.py
"""
import json
import os
import sys

import requests
from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
load_dotenv(os.path.join(ROOT, ".env"))

DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-lite-latest")
CANDIDATE_MODELS = [
    DEFAULT_MODEL,
    "gemini-flash-lite-latest",
    "gemini-flash-latest",
    "gemini-2.0-flash-lite",
    "gemini-2.0-flash",
]


def _test_model(api_key: str, model: str) -> tuple[int, str]:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = {
        "contents": [{"role": "user", "parts": [{"text": 'Réponds uniquement : {"ok": true}'}]}],
        "generationConfig": {"temperature": 0},
    }
    response = requests.post(
        url,
        headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
        json=payload,
        timeout=30,
    )
    if response.status_code == 200:
        return 200, "OK"
    try:
        msg = response.json().get("error", {}).get("message", response.text)
    except json.JSONDecodeError:
        msg = response.text
    return response.status_code, msg[:200]


def main() -> int:
    api_key = os.environ.get("GOOGLE_API_KEY", "").strip()
    if not api_key:
        print("ERREUR : GOOGLE_API_KEY absent du .env")
        print("  -> Créez une clé sur https://aistudio.google.com/apikey")
        print("  -> Format attendu : AIzaSy... (environ 39 caractères)")
        return 1

    prefix = api_key[:4]
    print(f"Clé détectée : préfixe={prefix!r}, longueur={len(api_key)}")
    if not api_key.startswith("AIza"):
        print("ATTENTION : la clé ne commence pas par 'AIza'.")
        print("  Les clés Google AI Studio commencent par AIzaSy...")
        print("  Si votre clé commence par 'AQ.', ce n'est probablement pas la bonne clé.")

    models_to_try = []
    for model in CANDIDATE_MODELS:
        if model not in models_to_try:
            models_to_try.append(model)

    print("\nTest des modèles Gemini disponibles...")
    working_model = None
    for model in models_to_try:
        try:
            status, detail = _test_model(api_key, model)
        except requests.RequestException as exc:
            print(f"  {model}: ERREUR réseau — {exc}")
            continue
        print(f"  {model}: HTTP {status} — {detail}")
        if status == 200:
            working_model = model
            break

    if working_model:
        print(f"\nOK — Gemini fonctionne avec le modèle {working_model!r}.")
        print(f"  Ajoutez dans .env : GEMINI_MODEL={working_model}")
        return 0

    print("\nAucun modèle Gemini disponible avec cette clé.")
    print("  Causes fréquentes :")
    print("  - Quota free tier epuise (limit: 0) -> attendez ou activez la facturation")
    print("  - Mauvaise clé → recréez sur https://aistudio.google.com/apikey")
    print("  - Clé entreprise sans accès au free tier Gemini")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
