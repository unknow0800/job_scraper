# Job Scraper

**Pipeline d'automatisation de recherche d'emploi/alternance : scraping multi-plateformes, déduplication, matching CV, génération de candidatures par IA et dashboard de suivi.**

Conçu pour centraliser la veille sur une dizaine de plateformes d'emploi françaises, éviter les doublons, et accélérer la rédaction de lettres de motivation personnalisées grâce à l'API Claude.

## Fonctionnalités principales

- **Scraping multi-sources** : LinkedIn, Indeed, WTTJ, APEC, HelloWork, Meteojob, Cadremploi, Monster, RegionsJob, JobTeaser, Glassdoor, France Travail (API officielle), Adzuna, Jooble
- **Déduplication automatique** des offres via base SQLite
- **Recherche multi-villes et multi-mots-clés** configurable
- **Génération de lettres de motivation et emails** personnalisés par IA (Claude), adaptés à chaque offre
- **Dashboard web** (FastAPI) pour visualiser, filtrer et suivre les candidatures
- **Alertes email** automatiques sur nouvelles offres correspondantes
- **Upload de CV** et extraction de texte (PDF) pour le matching

## Stack technique

| Composant | Technologie |
|---|---|
| Backend / Dashboard | FastAPI + Uvicorn |
| Scraping | Requests + BeautifulSoup4 |
| Base de données | SQLite |
| Génération IA | Claude API |
| Extraction PDF | pypdf |
| Automatisation Windows | Scripts PowerShell (tâche planifiée / démarrage auto) |

## Structure du projet

```
job_scraper/
├── main.py                 # Point d'entrée du scraper (lance les sources configurées)
├── app.py                  # Serveur FastAPI (dashboard + API)
├── pipeline.py              # Orchestration scraping → dédup → alertes
├── db.py                    # Accès et initialisation SQLite
├── config.py                 # Mots-clés, villes, types de contrat, clés d'API
├── email_alerts.py          # Envoi d'alertes et de résumés par email
├── letter_generator.py      # Génération IA des lettres/emails de candidature
├── scrapers/                 # Un module par plateforme (linkedin.py, indeed.py, wttj.py, ...)
├── templates/                # Interface du dashboard (dashboard.html)
├── install_autostart_task.ps1   # Installation en tâche planifiée Windows
└── run_dashboard_server.ps1     # Lancement du serveur dashboard
```

## Installation

```bash
git clone https://github.com/unknow0800/job_scraper.git
cd job_scraper
python -m venv .venv
.venv\Scripts\activate       # Windows
pip install -r requirements.txt
```

## Configuration

Crée un fichier `.env` à la racine (jamais commité, voir `.gitignore`) :

```
CANDIDATE_NAME=Votre Nom
CANDIDATE_EMAIL=vous@example.com
CANDIDATE_PHONE=+33 6 00 00 00 00
CANDIDATE_CITY=Paris

# Sources optionnelles (à activer selon besoin)
FRANCE_TRAVAIL_CLIENT_ID=
FRANCE_TRAVAIL_CLIENT_SECRET=
ADZUNA_APP_ID=
ADZUNA_APP_KEY=
JOOBLE_API_KEY=

# Génération de lettres
ANTHROPIC_API_KEY=
```

Adapte ensuite tes critères de recherche dans `config.py` :
```python
KEYWORDS = ["stage développeur", "alternance développeur web"]
LOCATIONS = ["Paris", "Marseille"]
```

## Utilisation

**Lancer le scraping**
```bash
python main.py
```

**Lancer le dashboard**
```bash
uvicorn app:app --reload
```
Puis ouvrir `http://localhost:8000`

**Génération de lettres pour les nouvelles offres**
```bash
python letter_generator.py
```

**Automatisation (Windows)** — pour lancer le scraper au démarrage :
```powershell
./install_autostart_task.ps1
```

## Confidentialité

Ce dépôt ne contient **aucune donnée personnelle** : candidatures générées, CV, preuves de recherche de stage et base de données locale sont exclus via `.gitignore`. Toute information personnelle (nom, email, téléphone) est injectée via variables d'environnement, jamais codée en dur dans le code source.

## Cadre d'usage

Le scraping respecte un délai entre requêtes (`REQUEST_DELAY`) pour limiter la charge sur les sites ciblés et réduire le risque de blocage. Ce projet est un outil personnel de veille, pas destiné à un usage massif ou commercial.

## Licence

MIT
