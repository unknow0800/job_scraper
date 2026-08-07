# ============================================================
#  scrapers/wttj.py — Welcome to the Jungle
# ============================================================
# L'ancienne API /api/v1/jobs renvoie parfois 404. Le scraper garde l'API
# comme premier essai, puis bascule sur les pages publiques HTML de WTTJ.

import re
import time
import unicodedata
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from config import USER_AGENT, REQUEST_DELAY, MAX_RESULTS_PER_QUERY


HOST = "https://www.welcometothejungle.com"
API_URL = "https://api.welcometothejungle.com/api/v1/jobs"

FALLBACK_PAGES = {
    "stage développeur": [
        f"{HOST}/fr/pages/stage-developpeur-web",
        f"{HOST}/fr/pages/stage-developpeur-full-stack",
        f"{HOST}/fr/jobs",
    ],
    "alternance développeur web": [
        f"{HOST}/fr/jobs",
    ],
    "stage data": [
        f"{HOST}/fr/jobs",
    ],
}


def _normalize(text: str) -> str:
    """Retire accents et majuscules pour comparer les textes simplement."""
    return unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii").lower()


def _build_params(keyword: str, location: str, page: int = 1) -> dict:
    """Prépare les paramètres envoyés à l'ancienne API JSON de WTTJ."""
    return {
        "query": keyword,
        "page": page,
        "per_page": 20,
        "contract_type[]": ["internship", "apprenticeship"],
        "location": location,
    }


def _job_matches(text: str, keyword: str, location: str) -> bool:
    """Filtre localement les cartes récupérées sur les pages publiques."""
    haystack = _normalize(text)
    keyword_norm = _normalize(keyword)
    location_norm = _normalize(location)

    if location_norm and location_norm not in haystack and "remote" not in haystack and "teletravail" not in haystack:
        return False
    if "alternance" in keyword_norm and "alternance" not in haystack and "apprentissage" not in haystack:
        return False
    if "stage" in keyword_norm and "stage" not in haystack and "internship" not in haystack:
        return False
    if "data" in keyword_norm:
        return any(term in haystack for term in ("data", "analytics", "python", "ia"))
    if "develop" in keyword_norm or "web" in keyword_norm:
        return any(term in haystack for term in ("develop", "software", "web", "full stack", "frontend", "backend", "python"))
    return True


def _parse_html_jobs(html: str, keyword: str, location: str) -> list[dict]:
    """Parse les liens d'offres WTTJ présents dans une page HTML publique."""
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    seen_urls = set()

    for link in soup.select("a[href*='/fr/companies/'][href*='/jobs/']"):
        href = link.get("href", "")
        full_url = urljoin(HOST, href.split("?")[0])
        if full_url in seen_urls:
            continue
        seen_urls.add(full_url)

        card = link.find_parent(["li", "article", "section", "div"]) or link
        text = card.get_text(" ", strip=True)
        title = link.get_text(" ", strip=True)
        if not title:
            # Certaines cartes placent le titre dans un parent plutôt que dans le lien.
            title = text.split("  ")[0].strip()[:120]
        if not title or not _job_matches(f"{title} {text}", keyword, location):
            continue

        company = "À vérifier sur WTTJ"
        company_match = re.search(r"\b([A-Z][\w&@'.\- ]{2,40})\s+(Stage|Alternance|CDI|CDD|Internship)\b", text)
        if company_match:
            company = company_match.group(1).strip()

        contract = "Stage/Alternance"
        text_norm = _normalize(text)
        if "alternance" in text_norm or "apprentissage" in text_norm:
            contract = "Alternance"
        elif "stage" in text_norm or "internship" in text_norm:
            contract = "Stage"

        location_value = location if _normalize(location) in text_norm else ""
        jobs.append({
            "title": title,
            "company": company,
            "location": location_value,
            "contract": contract,
            "description": text[:2000],
            "url": full_url,
            "source": "wttj",
        })

    return jobs


def _scrape_api(session: requests.Session, keyword: str, location: str) -> list[dict]:
    """Essaie l'ancienne API; retourne une liste vide si elle est indisponible."""
    api_jobs = []
    page = 1

    while len(api_jobs) < MAX_RESULTS_PER_QUERY:
        params = _build_params(keyword, location, page)
        try:
            resp = session.get(API_URL, params=params, timeout=10)
            if resp.status_code == 404:
                print("  [i] API WTTJ indisponible (404), fallback HTML.")
                return []
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"  [i] API WTTJ non exploitable, fallback HTML: {e}")
            return []

        offers = data.get("jobs", [])
        if not offers:
            break

        for offer in offers:
            company = offer.get("organization", {}).get("name", "N/A")
            slug_company = offer.get("organization", {}).get("slug", "")
            slug_job = offer.get("slug", "")
            url = f"{HOST}/fr/companies/{slug_company}/jobs/{slug_job}"
            api_jobs.append({
                "title": offer.get("name", "N/A"),
                "company": company,
                "location": offer.get("office", {}).get("city", location),
                "contract": offer.get("contract_type", "N/A"),
                "description": offer.get("description", "")[:2000],
                "url": url,
                "source": "wttj",
            })
            if len(api_jobs) >= MAX_RESULTS_PER_QUERY:
                break

        page += 1
        time.sleep(REQUEST_DELAY)

    return api_jobs


def _fallback_urls(keyword: str) -> list[str]:
    """Choisit les pages HTML publiques à consulter selon le mot-clé."""
    key = _normalize(keyword)
    if "velop" in key or "develop" in key or "web" in key:
        if "stage" in key:
            return FALLBACK_PAGES["stage développeur"]
        if "alternance" in key:
            return FALLBACK_PAGES["alternance développeur web"]
    if "data" in key:
        return FALLBACK_PAGES["stage data"]
    for known, urls in FALLBACK_PAGES.items():
        if _normalize(known) == key:
            return urls
    return [f"{HOST}/fr/jobs"]


def scrape(keywords: list[str], location: str) -> list[dict]:
    """Interroge WTTJ via API puis fallback HTML public."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.7",
        "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
        "Referer": f"{HOST}/fr/jobs",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
    })

    all_jobs = []
    seen_urls = set()

    for keyword in keywords:
        print(f"[WTTJ] Recherche : '{keyword}' à '{location}'")

        collected_jobs = _scrape_api(session, keyword, location)
        if not collected_jobs:
            for url in _fallback_urls(keyword):
                if len(collected_jobs) >= MAX_RESULTS_PER_QUERY:
                    break
                try:
                    time.sleep(REQUEST_DELAY)
                    resp = session.get(url, timeout=12)
                    resp.raise_for_status()
                    collected_jobs.extend(_parse_html_jobs(resp.text, keyword, location))
                except Exception as e:
                    print(f"  [!] Fallback WTTJ impossible sur {url}: {e}")

        added = 0
        for job in collected_jobs:
            if job["url"] in seen_urls:
                continue
            seen_urls.add(job["url"])
            all_jobs.append(job)
            added += 1
            if len(all_jobs) >= MAX_RESULTS_PER_QUERY:
                break

        print(f"  -> {added} offres trouvées")

    return all_jobs[:MAX_RESULTS_PER_QUERY]
