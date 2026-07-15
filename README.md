# Boomi Watch — Veille automatique des nouveautés Boomi

Veille hebdomadaire 100% gratuite : collecte les nouveautés Boomi (release notes,
blog, community), les résume et classe via l'API Groq (gratuite), et envoie un
digest dans un canal Teams. Le tout automatisé via GitHub Actions.

```
GitHub Actions (cron hebdo)
   → collect.py   : RSS + scraping (feedparser, requests, BeautifulSoup)
   → main.py      : dédup contre data/seen_items.json
   → summarize.py : résumé + classification via Groq (Llama 3.3 70B, gratuit)
   → notify.py    : envoi vers Teams (Workflows / Adaptive Card)
```

## Arborescence

```
boomi-watch/
├── .github/workflows/weekly-digest.yml   # le cron GitHub Actions
├── src/
│   ├── collect.py      # collecte RSS + scraping
│   ├── summarize.py     # appel Groq
│   ├── notify.py         # envoi Teams
│   └── main.py            # orchestrateur
├── data/seen_items.json  # historique de dédup (committé automatiquement)
├── config.yaml            # sources à surveiller — modifiable sans toucher au code
├── requirements.txt
├── .env.example
└── README.md
```

## Étape 1 — Créer le repo GitHub

```bash
cd boomi-watch
git init
git add .
git commit -m "Initial commit: Boomi Watch"
git branch -M main
git remote add origin https://github.com/<votre-org>/boomi-watch.git
git push -u origin main
```

Repo **privé** recommandé (les liens/résumés n'ont rien de secret, mais autant
rester discret sur votre outillage interne). Le tier gratuit GitHub Actions
(2000 min/mois sur repo privé) est très largement suffisant : un run hebdo
prend quelques secondes à quelques minutes.

## Étape 2 — Obtenir une clé Groq (gratuite, sans CB)

1. Aller sur https://console.groq.com
2. Se connecter (email ou Google)
3. Créer une clé API (`gsk_...`)
4. Garder cette clé de côté pour l'étape 4

## Étape 3 — Créer le Workflow Teams (remplace les anciens webhooks)

Les anciens "Incoming Webhooks" Teams sont retirés depuis avril 2026. Il faut
passer par l'app **Workflows** :

1. Dans Teams, ouvrir le canal cible → **⋯** (More options) → **Workflows**
2. Chercher le template **"Post to a channel when a webhook request is received"**
   (ou "Send webhook alerts to a channel")
3. Configurer le canal de destination, sauvegarder
4. Copier l'**URL du webhook** générée (`https://...webhook.office.com/webhookb2/...`)
5. Garder cette URL de côté pour l'étape 4

## Étape 4 — Configurer les secrets GitHub

Dans le repo GitHub : **Settings → Secrets and variables → Actions → New repository secret**

| Nom du secret       | Valeur                                  |
|----------------------|------------------------------------------|
| `GROQ_API_KEY`       | la clé obtenue à l'étape 2               |
| `TEAMS_WEBHOOK_URL`  | l'URL obtenue à l'étape 3                |

## Étape 5 — Tester en local (recommandé avant d'activer le cron)

```bash
python -m venv .venv
source .venv/bin/activate       # ou .venv\Scripts\activate sous Windows
pip install -r requirements.txt

cp .env.example .env
# éditez .env avec vos vraies valeurs GROQ_API_KEY et TEAMS_WEBHOOK_URL

python src/main.py
```

Si tout fonctionne, vous devriez voir un message Adaptive Card apparaître dans
votre canal Teams, et `data/seen_items.json` se remplir d'IDs.

**Astuce debug** : si `collect.py` ne remonte aucun item, le sélecteur CSS
(`link_selector` dans `config.yaml`) est probablement à ajuster — les sites
changent parfois leur structure HTML. Inspectez la page cible (F12 dans le
navigateur) et ajustez le sélecteur.

## Étape 6 — Activer le cron

Rien à faire de plus ! Le fichier `.github/workflows/weekly-digest.yml` est
déjà configuré pour tourner tous les lundis à 8h (heure de Paris, cron UTC à
ajuster si besoin). Vous pouvez aussi le déclencher manuellement depuis
l'onglet **Actions** du repo (bouton "Run workflow", grâce à `workflow_dispatch`).

## Personnalisation

- **Ajouter/retirer des sources** : éditez `config.yaml`, pas besoin de toucher
  au code Python.
- **Changer la fréquence** : modifiez la ligne `cron:` dans le workflow
  (ex: `"0 7 * * 1,4"` pour lundi ET jeudi).
- **Changer de LLM** : `summarize.py` utilise le SDK Groq (compatible OpenAI).
  Pour switcher vers un autre provider gratuit (Gemini, etc.), il suffit
  d'adapter cette fonction — le reste du pipeline ne change pas.
- **Ajouter une catégorie de priorité "urgente"** : vous pouvez dupliquer le
  workflow avec un cron quotidien et un filtre `importance == "haute"` dans
  `main.py` pour des alertes immédiates séparées du digest hebdo.

## Limites connues / points de vigilance

- Le tier gratuit Groq est soumis à des rate limits (requêtes/minute,
  tokens/minute) — largement suffisant pour un digest hebdo de quelques
  dizaines d'items, mais à surveiller si vous augmentez la fréquence ou le
  nombre de sources.
- Le scraping HTML (`collect_scrape`) est fragile par nature : si Boomi
  change la structure de ses pages, il faudra ajuster les sélecteurs CSS
  dans `config.yaml`.
- Pensez à ne jamais committer le fichier `.env` (déjà exclu via `.gitignore`).
