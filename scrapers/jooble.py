# ============================================================
#  scrapers/jooble.py
# ============================================================
# Jooble est aussi un agrégateur d'offres. Son API permet de chercher par
# mot-clé et localisation, ce qui complète les sites bloqués en scraping direct.
#
# Pour l'activer:
#   JOOBLE_API_KEY=...

import os
import time
from html import unescape

import requests
from bs4 import BeautifulSoup

from config import REQUEST_DELAY, MAX_RESULTS_PER_QUERY


API_URL = "https://fr.jooble.org/api/{api_key}"


def _clean_html(text: str) -> str:
    """Transforme un extrait HTML en texte simple."""
    return BeautifulSoup(unescape(text or ""), "html.parser").get_text(" ", strip=True)


def _to_job(raw: dict, fallback_location: str) -> dict:
    """Convertit une annonce Jooble au format commun du projet."""
    return {
        "title": raw.get("title") or "Titre non précisé",
        "company": raw.get("company") or "Entreprise non précisée",
        "location": raw.get("location") or fallback_location,
        "contract": raw.get("type") or "Contrat",
        "description": _clean_html(raw.get("snippet", ""))[:2000],
        "url": raw.get("link") or "",
        "source": "jooble",
    }


def scrape(keywords: list[str], location: str, max_results: int = MAX_RESULTS_PER_QUERY) -> list[dict]:
    """Récupère des offres via l'API Jooble."""
    api_key = os.getenv("JOOBLE_API_KEY", "").strip()
    if not api_key:
        print("[Jooble] API non configuree: ajoute JOOBLE_API_KEY.")
        return []

    session = requests.Session()
    jobs = []
    seen_urls = set()

    for keyword in keywords:
        if len(jobs) >= max_results:
            break
        print(f"[Jooble] Recherche : '{keyword}' à '{location}'")

        for page in range(1, 4):
            if len(jobs) >= max_results:
                break
            payload = {
                "keywords": keyword,
                "location": location,
                "radius": "40",
                "page": str(page),
                "ResultOnPage": min(20, max_results),
                "companysearch": "false",
            }
            try:
                response = session.post(API_URL.format(api_key=api_key), json=payload, timeout=15)
                response.raise_for_status()
                results = response.json().get("jobs", [])
            except Exception as e:
                print(f"  [!] Erreur Jooble: {e}")
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
            print(f"  -> {added} offre(s) Jooble page {page}")
            time.sleep(REQUEST_DELAY)

    return jobs[:max_results]
