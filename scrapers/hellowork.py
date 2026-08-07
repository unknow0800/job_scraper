# ============================================================
#  scrapers/hellowork.py
# ============================================================
# HelloWork a changé ses URLs: les anciennes routes /emplois?... renvoient
# maintenant souvent vers /fr-fr/... puis en 404. Ce scraper utilise donc les
# pages publiques actuelles par contrat et par ville.

import re
import time
import unicodedata
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from config import USER_AGENT, REQUEST_DELAY, MAX_RESULTS_PER_QUERY


HOST = "https://www.hellowork.com"

# Slugs observés sur les pages publiques HelloWork.
# Si une ville n'est pas connue, le scraper retombe sur la page nationale.
CITY_SLUGS = {
    "Paris": "paris-75000",
    "Marseille": "marseille-13000",
    "Le Havre": "le-havre-76620",
    "Bailleau-le-Pin": "bailleau-le-pin-28120",
}

TECH_TERMS = (
    "develop", "dev", "web", "data", "python", "javascript", "react",
    "informatique", "logiciel", "full stack", "frontend", "backend",
)


def _normalize(text: str) -> str:
    """Retire accents et majuscules pour comparer les textes simplement."""
    return unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii").lower()


def _build_urls(keyword: str, location: str) -> list[str]:
    """Construit les pages HelloWork actuelles à tester pour ce mot-clé."""
    normalized = _normalize(keyword)
    contracts = []
    if "alternance" in normalized:
        contracts.append("alternance")
    if "stage" in normalized:
        contracts.append("stage")
    if not contracts:
        contracts = ["stage", "alternance"]

    city_slug = CITY_SLUGS.get(location)
    urls = []
    for contract in contracts:
        if city_slug:
            urls.append(f"{HOST}/fr-fr/{contract}/ville_{city_slug}.html")
        urls.append(f"{HOST}/fr-fr/{contract}.html")
    return urls


def _matches_keyword(text: str, keyword: str) -> bool:
    """Garde surtout les offres tech/data pour éviter de remplir la base avec tout."""
    haystack = _normalize(text)
    keyword_norm = _normalize(keyword)
    if "data" in keyword_norm:
        return bool(re.search(r"\b(data|ia|python|analyse|analytics)\b", haystack))
    if "develop" in keyword_norm or "velop" in keyword_norm or "web" in keyword_norm:
        return bool(re.search(r"\b(develop\w*|dev|web|data|python|javascript|react|informatique|logiciel|frontend|backend)\b", haystack))
    return True


def _guess_contract(text: str, source_url: str) -> str:
    """Déduit le type de contrat depuis l'URL ou le texte de la carte."""
    haystack = _normalize(source_url + " " + text)
    if "alternance" in haystack:
        return "Alternance"
    if "stage" in haystack:
        return "Stage"
    return "Poste"


def _parse_page(html: str, source_url: str, keyword: str, expected_location: str = "") -> list[dict]:
    """Extrait les offres depuis les liens publics /fr-fr/emplois/*.html."""
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    seen_urls = set()

    for link in soup.select("a[href*='/fr-fr/emplois/']"):
        href = link.get("href", "")
        if not re.search(r"/fr-fr/emplois/\d+\.html", href):
            continue

        full_url = urljoin(HOST, href)
        if full_url in seen_urls:
            continue
        seen_urls.add(full_url)

        # On remonte au parent le plus proche pour récupérer lieu, contrat, avantages, etc.
        card = link.find_parent("li") or link.find_parent(["article", "section", "div"]) or link
        text = card.get_text(" ", strip=True)
        title = link.get_text(" ", strip=True)
        if not title or not _matches_keyword(f"{title} {text}", keyword):
            continue

        location = expected_location
        if expected_location:
            city_pattern = re.escape(expected_location).replace("\\ ", r"\s+")
            location_match = re.search(rf"\b({city_pattern}(?:\s+\d+[eè]?)?\s-\s\d{{2,3}})\b", text, flags=re.I)
            if location_match:
                location = location_match.group(1)

        jobs.append({
            "title": title,
            "company": "À vérifier sur HelloWork",
            "location": location,
            "contract": _guess_contract(text, source_url),
            "description": text[:2000],
            "url": full_url,
            "source": "hellowork",
        })

    return jobs


def run(keywords: list, locations: list, max_results: int = MAX_RESULTS_PER_QUERY) -> list[dict]:
    """Lance le scraping HelloWork sur les pages publiques encore accessibles."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    })

    jobs = []
    seen_urls = set()

    for keyword in keywords:
        for location in locations:
            if len(jobs) >= max_results:
                break

            print(f"[HelloWork] Recherche : '{keyword}' à '{location}'")
            for url in _build_urls(keyword, location):
                if len(jobs) >= max_results:
                    break
                try:
                    time.sleep(REQUEST_DELAY)
                    response = session.get(url, timeout=12)
                    response.raise_for_status()
                    page_jobs = _parse_page(response.text, url, keyword, location)
                except requests.HTTPError as e:
                    print(f"  [!] Page HelloWork indisponible ({response.status_code}) : {url}")
                    continue
                except Exception as e:
                    print(f"  [!] Erreur HelloWork : {e}")
                    continue

                added = 0
                for job in page_jobs:
                    if job["url"] in seen_urls:
                        continue
                    seen_urls.add(job["url"])
                    jobs.append(job)
                    added += 1
                    if len(jobs) >= max_results:
                        break
                print(f"  -> {added} offre(s) lues depuis {url}")

    return jobs[:max_results]
