# ============================================================
#  scrapers/monster.py
# ============================================================
# Monster - Plateforme historique de recherche d'emploi

import time
import requests
from bs4 import BeautifulSoup
from config import USER_AGENT, REQUEST_DELAY, MAX_RESULTS_PER_QUERY


BASE_URL = "https://www.monster.fr/emplois"


def _build_url(keyword: str, location: str, start: int = 0) -> str:
    """Construit l'URL de recherche Monster avec pagination."""
    params = {
        "q": keyword,
        "where": location,
        "page": start // 25 + 1,
    }
    from urllib.parse import urlencode
    return f"{BASE_URL}?{urlencode(params)}"


def _parse_page(html: str, source_url: str) -> list[dict]:
    """Lit le HTML Monster et extrait les cartes d'offres."""
    soup = BeautifulSoup(html, "html.parser")
    jobs = []

    # Monster encapsule les offres dans des div.job-listing-item
    cards = soup.select("div.job-listing-item")

    for card in cards:
        title_tag = card.select_one("h2.job-title a")
        company_tag = card.select_one("p.company-name")
        location_tag = card.select_one("p.job-location")

        title = title_tag.get_text(strip=True) if title_tag else "N/A"
        company = company_tag.get_text(strip=True) if company_tag else "N/A"
        location = location_tag.get_text(strip=True) if location_tag else "N/A"

        link = title_tag["href"] if title_tag and title_tag.get("href") else ""
        full_url = f"https://www.monster.fr{link}" if link.startswith("/") else link

        jobs.append({
            "title": title,
            "company": company,
            "location": location,
            "contract": "Contrat",
            "description": "",
            "url": full_url,
            "source": "monster",
        })

    return jobs


def run(keywords: list, locations: list, max_results: int = MAX_RESULTS_PER_QUERY) -> list[dict]:
    """Lance le scraping sur Monster."""
    jobs = []
    results_count = 0

    for keyword in keywords:
        for location in locations:
            if results_count >= max_results:
                break

            start = 0
            page_count = 0
            while results_count < max_results:
                try:
                    # Chaque itération correspond à une page de résultats.
                    url = _build_url(keyword, location, start)
                    time.sleep(REQUEST_DELAY)
                    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=10)
                    response.raise_for_status()

                    page_jobs = _parse_page(response.text, url)
                    if not page_jobs:
                        break

                    jobs.extend(page_jobs)
                    results_count += len(page_jobs)
                    start += 25
                    page_count += 1
                    if page_count > 3:
                        break

                except Exception as e:
                    print(f"[Monster] Erreur pour {keyword} à {location}: {e}")
                    break

            if results_count >= max_results:
                break

    return jobs[:max_results]
