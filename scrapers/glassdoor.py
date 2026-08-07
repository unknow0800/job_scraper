# ============================================================
#  scrapers/glassdoor.py
# ============================================================
# Glassdoor - Plateforme de recherche d'emploi avec avis

import time
import requests
from bs4 import BeautifulSoup
from config import USER_AGENT, REQUEST_DELAY, MAX_RESULTS_PER_QUERY


BASE_URL = "https://www.glassdoor.fr/Job/jobs.htm"


def _build_url(keyword: str, location: str, start: int = 0) -> str:
    """Construit l'URL de recherche Glassdoor avec pagination."""
    params = {
        "keyword": keyword,
        "location": location,
        "start": start,
    }
    from urllib.parse import urlencode
    return f"{BASE_URL}?{urlencode(params)}"


def _parse_page(html: str, source_url: str) -> list[dict]:
    """Lit le HTML Glassdoor et extrait les cartes d'offres."""
    soup = BeautifulSoup(html, "html.parser")
    jobs = []

    # Glassdoor encapsule les offres dans des div.JobCard
    cards = soup.select("div.JobCard")

    for card in cards:
        title_tag = card.select_one("a.jobTitle")
        company_tag = card.select_one("div.employer")
        location_tag = card.select_one("div.location")

        title = title_tag.get_text(strip=True) if title_tag else "N/A"
        company = company_tag.get_text(strip=True) if company_tag else "N/A"
        location = location_tag.get_text(strip=True) if location_tag else "N/A"

        link = title_tag["href"] if title_tag and title_tag.get("href") else ""
        full_url = f"https://www.glassdoor.fr{link}" if link.startswith("/") else link

        jobs.append({
            "title": title,
            "company": company,
            "location": location,
            "contract": "CDI/CDD",
            "description": "",
            "url": full_url,
            "source": "glassdoor",
        })

    return jobs


def run(keywords: list, locations: list, max_results: int = MAX_RESULTS_PER_QUERY) -> list[dict]:
    """Lance le scraping sur Glassdoor."""
    jobs = []
    results_count = 0
    query_index = 0

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
                    start += 30
                    page_count += 1
                    if page_count > 3:  # Limiter à 3 pages par requête
                        break

                except Exception as e:
                    print(f"[Glassdoor] Erreur pour {keyword} à {location}: {e}")
                    break

            query_index += 1
            if results_count >= max_results:
                break

    return jobs[:max_results]
