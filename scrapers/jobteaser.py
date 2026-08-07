# ============================================================
#  scrapers/jobteaser.py
# ============================================================
# JobTeaser - stages, alternances et premiers emplois étudiants.

import json
import time
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup

from config import USER_AGENT, REQUEST_DELAY, MAX_RESULTS_PER_QUERY


BASE_URL = "https://www.jobteaser.com/fr/job-offers"
HOST = "https://www.jobteaser.com"


def _build_url(keyword: str, location: str, page: int = 1) -> str:
    """Construit l'URL de recherche JobTeaser."""
    params = {
        "query": keyword,
        "location": location,
        "page": page,
    }
    return f"{BASE_URL}?{urlencode(params)}"


def _absolute_url(url: str) -> str:
    """Transforme une URL relative en URL complète."""
    if not url:
        return ""
    return f"{HOST}{url}" if url.startswith("/") else url


def _json_ld_jobs(soup: BeautifulSoup) -> list[dict]:
    """Extrait les offres présentes dans les balises JSON-LD structurées."""
    jobs = []
    for script in soup.select("script[type='application/ld+json']"):
        try:
            data = json.loads(script.string or "{}")
        except json.JSONDecodeError:
            continue

        items = data if isinstance(data, list) else [data]
        for item in items:
            graph = item.get("@graph", []) if isinstance(item, dict) else []
            candidates = graph or items
            for obj in candidates:
                if not isinstance(obj, dict) or obj.get("@type") != "JobPosting":
                    continue
                hiring = obj.get("hiringOrganization") or {}
                location = obj.get("jobLocation") or {}
                address = location.get("address") if isinstance(location, dict) else {}
                jobs.append({
                    "title": obj.get("title", "N/A"),
                    "company": hiring.get("name", "N/A") if isinstance(hiring, dict) else "N/A",
                    "location": address.get("addressLocality", "N/A") if isinstance(address, dict) else "N/A",
                    "contract": obj.get("employmentType", "Stage/Alternance"),
                    "description": BeautifulSoup(obj.get("description", ""), "html.parser").get_text(" ", strip=True)[:2000],
                    "url": _absolute_url(obj.get("url", "")),
                    "source": "jobteaser",
                })
    return jobs


def _parse_page(html: str) -> list[dict]:
    """Essaie JSON-LD d'abord, puis un parsing HTML classique en secours."""
    soup = BeautifulSoup(html, "html.parser")
    jobs = _json_ld_jobs(soup)
    if jobs:
        return jobs

    cards = soup.select("article, [data-testid*='job'], [class*='JobOffer'], [class*='job-offer']")
    for card in cards:
        title_tag = card.select_one("h2 a, h3 a, a[href*='/job-offers/']")
        if not title_tag:
            continue
        text = card.get_text(" ", strip=True)
        company_tag = card.select_one("[class*='company'], [data-testid*='company']")
        location_tag = card.select_one("[class*='location'], [data-testid*='location']")
        jobs.append({
            "title": title_tag.get_text(" ", strip=True) or "N/A",
            "company": company_tag.get_text(" ", strip=True) if company_tag else "N/A",
            "location": location_tag.get_text(" ", strip=True) if location_tag else "N/A",
            "contract": "Stage/Alternance",
            "description": text[:2000],
            "url": _absolute_url(title_tag.get("href", "")),
            "source": "jobteaser",
        })
    return jobs


def scrape(keywords: list[str], location: str, max_results: int = MAX_RESULTS_PER_QUERY) -> list[dict]:
    """Scrape JobTeaser sur quelques pages pour chaque mot-clé."""
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    all_jobs = []

    for keyword in keywords:
        print(f"[JobTeaser] Recherche : '{keyword}' à '{location}'")
        for page in range(1, 4):
            if len(all_jobs) >= max_results:
                break
            try:
                time.sleep(REQUEST_DELAY)
                resp = session.get(_build_url(keyword, location, page), timeout=12)
                resp.raise_for_status()
                page_jobs = _parse_page(resp.text)
            except Exception as e:
                print(f"  [!] Erreur JobTeaser : {e}")
                break
            if not page_jobs:
                break
            all_jobs.extend(page_jobs)

    return all_jobs[:max_results]
