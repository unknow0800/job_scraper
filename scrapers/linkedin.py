# ============================================================
#  scrapers/linkedin.py
# ============================================================
# LinkedIn bloque agressivement le scraping authentifié.
# On utilise l'endpoint PUBLIC (sans login) qui retourne du HTML
# limité mais suffisant pour titre / entreprise / lien.
#
# ⚠️  Pour aller plus loin (description complète), il faudrait
#     Playwright + un compte. C'est couvert dans les commentaires.
# ============================================================

import time
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlencode
from config import USER_AGENT, REQUEST_DELAY, MAX_RESULTS_PER_QUERY


PUBLIC_SEARCH = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"


def _build_url(keyword: str, location: str, start: int = 0) -> str:
    """Construit l'URL de l'endpoint public LinkedIn avec pagination."""
    params = {
        "keywords": keyword,
        "location": location,
        "f_TPR": "r604800",    # 7 derniers jours
        "f_JT": "I",           # I = Internship (inclut stages & alternances)
        "start": start,
    }
    return f"{PUBLIC_SEARCH}?{urlencode(params)}"


def _parse_cards(html: str) -> list[dict]:
    """Parse les cartes HTML renvoyées par LinkedIn public."""
    soup = BeautifulSoup(html, "html.parser")
    jobs = []

    for card in soup.select("li"):
        title_tag = card.select_one("h3.base-search-card__title")
        company_tag = card.select_one("h4.base-search-card__subtitle")
        location_tag = card.select_one("span.job-search-card__location")
        link_tag = card.select_one("a.base-card__full-link")
        time_tag = card.select_one("time")

        title = title_tag.get_text(strip=True) if title_tag else "N/A"
        company = company_tag.get_text(strip=True) if company_tag else "N/A"
        location = location_tag.get_text(strip=True) if location_tag else "N/A"
        url = link_tag["href"].split("?")[0] if link_tag else ""
        posted_text = time_tag.get_text(" ", strip=True) if time_tag else ""
        posted_date = time_tag.get("datetime", "") if time_tag else ""
        # On garde la date dans description pour que le filtre d'ancienneté puisse l'utiliser.
        description = " ".join(
            part for part in [
                f"Date publication LinkedIn: {posted_date}" if posted_date else "",
                f"Age publication LinkedIn: {posted_text}" if posted_text else "",
            ]
            if part
        )

        if title != "N/A":
            jobs.append({
                "title": title,
                "company": company,
                "location": location,
                "contract": "stage/alternance",
                "description": description,
                "url": url,
                "source": "linkedin",
            })

    return jobs


def scrape(keywords: list[str], location: str) -> list[dict]:
    """
    Utilise l'API publique LinkedIn (sans login).
    Description vide — pour la récupérer, utiliser Playwright avec session.
    """
    headers = {
        "User-Agent": USER_AGENT,
        "Accept-Language": "fr-FR,fr;q=0.9",
    }
    session = requests.Session()
    session.headers.update(headers)

    all_jobs = []

    for keyword in keywords:
        print(f"[LinkedIn] Recherche : '{keyword}' à '{location}'")
        start = 0
        collected = 0

        while collected < MAX_RESULTS_PER_QUERY:
            url = _build_url(keyword, location, start)
            try:
                resp = session.get(url, timeout=10)
                resp.raise_for_status()
            except requests.RequestException as e:
                print(f"  [!] Erreur : {e}")
                break

            jobs = _parse_cards(resp.text)
            if not jobs:
                break

            all_jobs.extend(jobs)
            collected += len(jobs)
            start += 25
            # LinkedIn renvoie généralement les résultats par blocs d'environ 25.
            time.sleep(REQUEST_DELAY)

        print(f"  → {collected} offres trouvées")

    return all_jobs


# ============================================================
# 💡 VERSION PLAYWRIGHT (avec description complète)
# Décommente et adapte si tu veux l'authentification LinkedIn.
# ============================================================
#
# from playwright.sync_api import sync_playwright
#
# def scrape_with_playwright(keywords, location, li_at_cookie):
#     with sync_playwright() as p:
#         browser = p.chromium.launch(headless=True)
#         context = browser.new_context()
#         context.add_cookies([{
#             "name": "li_at", "value": li_at_cookie,
#             "domain": ".linkedin.com", "path": "/"
#         }])
#         page = context.new_page()
#         # ... navigation et scraping ...
#         browser.close()
