# ============================================================
#  scrapers/indeed.py
# ============================================================
# Indeed charge ses résultats côté serveur → requests suffit.
# On parse les balises HTML de la page de résultats.
# ============================================================

import time
import requests
from bs4 import BeautifulSoup
from config import USER_AGENT, REQUEST_DELAY, MAX_RESULTS_PER_QUERY


BASE_URL = "https://fr.indeed.com/jobs"


def _build_url(keyword: str, location: str, start: int = 0) -> str:
    """Fabrique l'URL de recherche Indeed avec mot-clé, ville et pagination."""
    params = {
        "q": keyword,
        "l": location,
        "start": start,
        "fromage": 14,   # offres des 14 derniers jours
    }
    from urllib.parse import urlencode
    return f"{BASE_URL}?{urlencode(params)}"


def _parse_page(html: str, source_url: str) -> list[dict]:
    """Transforme le HTML Indeed en liste d'offres normalisées."""
    soup = BeautifulSoup(html, "html.parser")
    jobs = []

    # Indeed encapsule chaque offre dans un <div class="job_seen_beacon">
    cards = soup.select("div.job_seen_beacon")

    for card in cards:
        title_tag = card.select_one("h2.jobTitle span")
        company_tag = card.select_one("[data-testid='company-name']")
        location_tag = card.select_one("[data-testid='text-location']")
        link_tag = card.select_one("h2.jobTitle a")

        title = title_tag.get_text(strip=True) if title_tag else "N/A"
        company = company_tag.get_text(strip=True) if company_tag else "N/A"
        location = location_tag.get_text(strip=True) if location_tag else "N/A"

        relative_url = link_tag["href"] if link_tag and link_tag.get("href") else ""
        # Indeed renvoie parfois un lien relatif; on le transforme en lien complet.
        full_url = f"https://fr.indeed.com{relative_url}" if relative_url.startswith("/") else relative_url

        jobs.append({
            "title": title,
            "company": company,
            "location": location,
            "contract": "stage/alternance",
            "description": "",   # nécessite une 2e requête sur l'offre — voir ci-dessous
            "url": full_url,
            "source": "indeed",
        })

    return jobs


def fetch_job_description(url: str, session: requests.Session) -> str:
    """Récupère la description complète d'une offre Indeed."""
    try:
        resp = session.get(url, timeout=10)
        soup = BeautifulSoup(resp.text, "html.parser")
        desc_tag = soup.select_one("#jobDescriptionText")
        return desc_tag.get_text(separator="\n", strip=True)[:2000] if desc_tag else ""
    except Exception:
        return ""


def scrape(keywords: list[str], location: str) -> list[dict]:
    """Point d'entrée principal — retourne une liste de dicts job."""
    headers = {"User-Agent": USER_AGENT}
    session = requests.Session()
    session.headers.update(headers)

    all_jobs = []

    for keyword in keywords:
        print(f"[Indeed] Recherche : '{keyword}' à '{location}'")
        start = 0
        collected = 0

        while collected < MAX_RESULTS_PER_QUERY:
            url = _build_url(keyword, location, start)
            try:
                # Session garde les headers entre les requêtes et évite de les répéter.
                resp = session.get(url, timeout=10)
                resp.raise_for_status()
            except requests.RequestException as e:
                print(f"  [!] Erreur requête : {e}")
                break

            jobs = _parse_page(resp.text, url)
            if not jobs:
                break  # plus de résultats

            for job in jobs:
                # Optionnel : récupérer la description complète
                if job["url"]:
                    time.sleep(REQUEST_DELAY)
                    job["description"] = fetch_job_description(job["url"], session)
                all_jobs.append(job)
                collected += 1
                if collected >= MAX_RESULTS_PER_QUERY:
                    break

            start += 10
            # Indeed pagine par blocs de 10 résultats.
            time.sleep(REQUEST_DELAY)

        print(f"  → {collected} offres trouvées")

    return all_jobs
