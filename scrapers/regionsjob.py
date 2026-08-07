# ============================================================
#  scrapers/regionsjob.py
# ============================================================
# RegionsJob redirige désormais vers HelloWork. Pour éviter de scraper une
# page d'accueil vide, on réutilise donc le scraper HelloWork actuel.

from config import MAX_RESULTS_PER_QUERY
from scrapers import hellowork


def run(keywords: list, locations: list, max_results: int = MAX_RESULTS_PER_QUERY) -> list[dict]:
    """Lance une recherche RegionsJob via le site HelloWork qui l'a remplacé."""
    print("[RegionsJob] Redirection détectée vers HelloWork: utilisation du scraper HelloWork.")
    jobs = hellowork.run(keywords, locations, max_results=max_results)
    # On garde source="hellowork", car les URLs et les données viennent réellement de HelloWork.
    return jobs[:max_results]
