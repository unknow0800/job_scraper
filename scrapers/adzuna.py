# ============================================================
#  scrapers/adzuna.py
# ============================================================
# Adzuna est un agrégateur d'offres: il récupère des annonces venant de
# plusieurs sites. C'est utile pour augmenter la couverture du dashboard sans
# scraper directement chaque plateforme bloquée.
#
# Pour l'activer:
#   ADZUNA_APP_ID=...
#   ADZUNA_APP_KEY=...

import os
import time
from html import unescape

import requests
from bs4 import BeautifulSoup

from config import REQUEST_DELAY, MAX_RESULTS_PER_QUERY


API_URL = "https://api.adzuna.com/v1/api/jobs/fr/search/{page}"


def _credentials() -> tuple[str, str]:
    """Lit les identifiants Adzuna depuis les variables d'environnement."""
    return os.getenv("ADZUNA_APP_ID", "").strip(), os.getenv("ADZUNA_APP_KEY", "").strip()


def _clean_html(text: str) -> str:
    """Transforme une description HTML en texte lisible."""
    return BeautifulSoup(unescape(text or ""), "html.parser").get_text(" ", strip=True)


def _to_job(raw: dict, fallback_location: str) -> dict:
    """Convertit une annonce Adzuna au format commun du projet."""
    company = raw.get("company") or {}
    location = raw.get("location") or {}
    area = location.get("area") or []
    location_text = ", ".join(area[-2:]) if area else fallback_location

    return {
        "title": raw.get("title") or "Titre non précisé",
        "company": company.get("display_name") or "Entreprise non précisée",
        "location": location_text,
        "contract": raw.get("contract_time") or raw.get("category", {}).get("label") or "Contrat",
        "description": _clean_html(raw.get("description", ""))[:2000],
        "url": raw.get("redirect_url") or "",
        "source": "adzuna",
    }


def scrape(keywords: list[str], location: str, max_results: int = MAX_RESULTS_PER_QUERY) -> list[dict]:
    """Récupère des offres via l'API Adzuna France."""
    app_id, app_key = _credentials()
    if not app_id or not app_key:
        print("[Adzuna] API non configuree: ajoute ADZUNA_APP_ID et ADZUNA_APP_KEY.")
        return []

    session = requests.Session()
    jobs = []
    seen_urls = set()

    for keyword in keywords:
        if len(jobs) >= max_results:
            break
        print(f"[Adzuna] Recherche : '{keyword}' à '{location}'")

        page = 1
        while len(jobs) < max_results and page <= 3:
            params = {
                "app_id": app_id,
                "app_key": app_key,
                "what": keyword,
                "where": location,
                "results_per_page": min(20, max_results),
                "content-type": "application/json",
                "sort_by": "date",
            }
            try:
                response = session.get(API_URL.format(page=page), params=params, timeout=15)
                response.raise_for_status()
                results = response.json().get("results", [])
            except Exception as e:
                print(f"  [!] Erreur Adzuna: {e}")
                break

            if not results:
                break

            added = 0
            for raw in results:
                job = _to_job(raw, location)
                key = job["url"] or f"{job['title']}|{job['company']}|{job['location']}"
                if key in seen_urls:
                    continue
                seen_urls.add(key)
                jobs.append(job)
                added += 1
                if len(jobs) >= max_results:
                    break
            print(f"  -> {added} offre(s) Adzuna page {page}")
            page += 1
            time.sleep(REQUEST_DELAY)

    return jobs[:max_results]
