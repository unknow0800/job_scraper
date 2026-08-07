# ============================================================
#  main.py - Point d'entree du scraper
# ============================================================

import sys
from db import init_db, insert_job, get_stats
from config import KEYWORDS, LOCATION, LOCATIONS
from scrapers import (
    indeed,
    linkedin,
    wttj,
    apec,
    glassdoor,
    monster,
    regionsjob,
    hellowork,
    pole_emploi,
    jobteaser,
    meteojob,
    cadremploi,
    adzuna,
    jooble,
)

DEFAULT_SOURCES = [
    "linkedin",
    "hellowork",
    "meteojob",
    "adzuna",
    "jooble",
    "france-travail",
]


def run_scraper(sources: list[str] = None, locations: list[str] = None):
    """
    Lance le scraping sur les sources demandees.
    Par defaut, tourne sur tous les sites et toutes les zones configurees.
    """
    init_db()

    # Dictionnaire de dispatch: le nom texte de la source pointe vers
    # la fonction Python qui sait scraper ce site.
    available = {
        "indeed":      lambda keywords, location: indeed.scrape(keywords, location),
        "linkedin":    lambda keywords, location: linkedin.scrape(keywords, location),
        "wttj":        lambda keywords, location: wttj.scrape(keywords, location),
        "apec":        lambda keywords, location: apec.scrape(keywords, location),
        "glassdoor":   lambda keywords, location: glassdoor.run(keywords, [location]),
        "monster":     lambda keywords, location: monster.run(keywords, [location]),
        "regionsjob":  lambda keywords, location: regionsjob.run(keywords, [location]),
        "hellowork":   lambda keywords, location: hellowork.run(keywords, [location]),
        "pole-emploi": lambda keywords, location: pole_emploi.run(keywords, [location]),
        "france-travail": lambda keywords, location: pole_emploi.run(keywords, [location]),
        "jobteaser":   lambda keywords, location: jobteaser.scrape(keywords, location),
        "meteojob":    lambda keywords, location: meteojob.scrape(keywords, location),
        "cadremploi":  lambda keywords, location: cadremploi.scrape(keywords, location),
        "adzuna":      lambda keywords, location: adzuna.scrape(keywords, location),
        "jooble":      lambda keywords, location: jooble.scrape(keywords, location),
    }

    # Par defaut, on evite seulement France Travail/Pole Emploi, qui depend
    # d'une API OAuth parfois indisponible. Les sources utiles restent actives.
    sources = sources or DEFAULT_SOURCES
    search_locations = locations or LOCATIONS or [LOCATION]
    total_new = 0

    # Double boucle: chaque ville est testée sur chaque site choisi.
    for location in search_locations:
        print(f"\n[ZONE] Recherche autour de : {location}")
        for source_name in sources:
            if source_name not in available:
                print(f"[!] Source inconnue : {source_name}")
                continue

            scrape_fn = available[source_name]
            try:
                # Tous les scrapers retournent la même forme de données:
                # une liste de dictionnaires représentant des offres.
                jobs = scrape_fn(KEYWORDS, location)
            except Exception as e:
                print(f"[!] Erreur lors du scraping {source_name} a {location} : {e}")
                continue

            new_count = 0
            for job in jobs:
                # insert_job renvoie False si l'offre est déjà connue.
                if insert_job(job):
                    new_count += 1

            duplicates = len(jobs) - new_count
            print(f"[{source_name.upper()} / {location}] {new_count} nouvelles offres inserees ({duplicates} doublons ignores)\n")
            total_new += new_count

    stats = get_stats()
    print("=" * 50)
    print(f"Termine ! {total_new} nouvelles offres ajoutees.")
    print(f"Total en base : {stats['total']} offres")
    for source, count in stats["by_source"].items():
        print(f"   - {source}: {count}")
    print("=" * 50)


if __name__ == "__main__":
    # Usage :
    #   python main.py
    #   python main.py indeed wttj
    sources = sys.argv[1:] if len(sys.argv) > 1 else None
    # Exemple: python main.py indeed wttj ne lance que ces deux sources.
    run_scraper(sources)
