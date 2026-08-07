# ============================================================
#  scrapers/apec.py — APEC
# ============================================================
# L'APEC expose une API REST JSON non documentée mais stable.
# On la requête directement avec les bons paramètres.
# ============================================================

import time
import requests
from config import USER_AGENT, REQUEST_DELAY, MAX_RESULTS_PER_QUERY


SEARCH_URL = "https://www.apec.fr/cms/webservices/rechercheOffre/rechercherOffres"
DETAIL_URL = "https://www.apec.fr/candidat/recherche-emploi.html/emploi/detail-offre/"


def _build_payload(keyword: str, location_code: str = None, start: int = 0) -> dict:
    """
    location_code : code département APEC (ex: "75" pour Paris).
    Laisse None pour France entière.
    """
    # L'APEC attend un corps JSON plutôt que des paramètres dans l'URL.
    payload = {
        "motsCles": keyword,
        "typeContrat": [141700],   # 141700 = stage, 141703 = alternance
        "nbResultatsParPage": 20,
        "debut": start,
        "tri": 1,  # tri par date
    }
    if location_code:
        payload["lieu"] = [{"type": "departement", "code": location_code}]
    return payload


def scrape(keywords: list[str], location: str) -> list[dict]:
    """Appelle l'API APEC et convertit ses résultats en format commun."""
    # Correspondance simple ville → code département
    CITY_TO_DEPT = {
        "Paris": "75", "Lyon": "69", "Marseille": "13",
        "Toulouse": "31", "Bordeaux": "33", "Nantes": "44",
        "Lille": "59", "Strasbourg": "67", "Rennes": "35",
        "Le Havre": "76", "Bailleau-le-Pin": "28",
    }
    dept_code = CITY_TO_DEPT.get(location)

    headers = {
        "User-Agent": USER_AGENT,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    session = requests.Session()
    session.headers.update(headers)

    all_jobs = []

    for keyword in keywords:
        print(f"[APEC] Recherche : '{keyword}' à '{location}'")
        start = 0
        collected = 0

        while collected < MAX_RESULTS_PER_QUERY:
            payload = _build_payload(keyword, dept_code, start)
            try:
                resp = session.post(SEARCH_URL, json=payload, timeout=10)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                print(f"  [!] Erreur : {e}")
                break

            offers = data.get("resultats", [])
            if not offers:
                break

            for offer in offers:
                # numOffre permet de reconstruire l'URL publique de l'annonce.
                numero = offer.get("numOffre", "")
                url = f"{DETAIL_URL}{numero}" if numero else ""

                all_jobs.append({
                    "title": offer.get("intitule", "N/A"),
                    "company": offer.get("nomEntreprise", "N/A"),
                    "location": offer.get("lieuTravail", location),
                    "contract": offer.get("libelleTypeContrat", "N/A"),
                    "description": offer.get("texteHtml", "")[:2000],
                    "url": url,
                    "source": "apec",
                })
                collected += 1
                if collected >= MAX_RESULTS_PER_QUERY:
                    break

            start += 20
            time.sleep(REQUEST_DELAY)

        print(f"  → {collected} offres trouvées")

    return all_jobs
