# ============================================================
#  config.py — Paramètres de recherche
# ============================================================

# Mots-clés de recherche (modifie selon ton domaine)
# Liste des expressions que le programme tape sur les sites d'emploi.
# Pour changer le type d'offres recherchées, c'est souvent ici qu'il faut agir.
KEYWORDS = ["stage développeur", "alternance développeur web", "stage data"]

# Localisations de recherche
# Villes dans lesquelles les scrapers vont lancer les recherches.
# main.py parcourt cette liste ville par ville.
LOCATIONS = ["Paris", "Marseille", "Le Havre", "Bailleau-le-Pin"]

# Localisation principale gardee pour compatibilite avec les anciens scripts
# Ancienne variable gardée pour les scripts qui n'acceptent qu'une seule ville.
LOCATION = LOCATIONS[0]

# Type de contrat (utilisé selon les sites)
# Types de contrats visés. Certains scrapers l'utilisent directement,
# d'autres le gardent comme information de contexte.
CONTRACT_TYPES = ["stage", "alternance"]

# Nombre max d'offres à récupérer par site et par mot-clé
# Limite volontaire pour éviter de faire trop de requêtes sur un même site.
MAX_RESULTS_PER_QUERY = 20

# Délai entre les requêtes (secondes) — pour ne pas se faire bannir
# Pause entre deux requêtes HTTP. Elle rend le scraping moins agressif.
REQUEST_DELAY = 2

# User-Agent pour simuler un vrai navigateur
# User-Agent envoyé aux sites: il indique que la requête ressemble
# à celle d'un navigateur Chrome classique, pas à un robot vide.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# Chemin vers la base de données SQLite
# Fichier SQLite local qui stocke toutes les offres trouvées.
DB_PATH = "jobs.db"

# Identifiants optionnels pour l'API officielle France Travail.
# Laisse vide ici: mets-les plutôt en variables d'environnement pour éviter
# d'écrire des secrets dans le code.
FRANCE_TRAVAIL_CLIENT_ID_ENV = "FRANCE_TRAVAIL_CLIENT_ID"
FRANCE_TRAVAIL_CLIENT_SECRET_ENV = "FRANCE_TRAVAIL_CLIENT_SECRET"

# Identifiants optionnels pour les agrégateurs d'offres.
# Ces sources augmentent la couverture, car elles rassemblent des offres
# provenant de plusieurs plateformes.
ADZUNA_APP_ID_ENV = "ADZUNA_APP_ID"
ADZUNA_APP_KEY_ENV = "ADZUNA_APP_KEY"
JOOBLE_API_KEY_ENV = "JOOBLE_API_KEY"
