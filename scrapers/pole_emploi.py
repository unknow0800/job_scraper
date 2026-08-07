# ============================================================
#  scrapers/pole_emploi.py
# ============================================================
# France Travail (ancien Pôle Emploi) bloque/retire les anciennes pages HTML.
# La bonne méthode est donc l'API officielle Offres d'emploi v2.
#
# Pour l'activer:
#   1. Crée une application sur le portail France Travail / Emploi Store.
#   2. Abonne cette application à "API Offres d'emploi v2".
#   3. Mets les identifiants dans les variables d'environnement:
#        FRANCE_TRAVAIL_CLIENT_ID
#        FRANCE_TRAVAIL_CLIENT_SECRET
#
# Sans ces identifiants, le scraper explique quoi configurer et retourne 0 offre.

import os
import time
from html import unescape
from typing import Any

import requests

from config import REQUEST_DELAY, MAX_RESULTS_PER_QUERY


AUTH_URLS = [
    "https://entreprise.francetravail.fr/connexion/oauth2/access_token?realm=/partenaire",
    "https://entreprise.pole-emploi.fr/connexion/oauth2/access_token?realm=/partenaire",
]
SEARCH_URLS = [
    "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search",
]

# Codes commune acceptes par l'API Offres d'emploi.
# Paris et Marseille doivent utiliser un arrondissement, pas le code global INSEE.
CITY_TO_COMMUNE = {
    "Paris": "75101",
    "Marseille": "13201",
    "Le Havre": "76351",
    "Bailleau-le-Pin": "28024",
}


def _credentials() -> tuple[str, str]:
    """Lit les identifiants API depuis les variables d'environnement."""
    return (
        os.getenv("FRANCE_TRAVAIL_CLIENT_ID", "").strip(),
        os.getenv("FRANCE_TRAVAIL_CLIENT_SECRET", "").strip(),
    )


def _get_access_token(session: requests.Session) -> str:
    """Récupère un token OAuth2 client_credentials pour l'API officielle."""
    client_id, client_secret = _credentials()
    if not client_id or not client_secret:
        print(
            "[France Travail] API non configuree: ajoute FRANCE_TRAVAIL_CLIENT_ID "
            "et FRANCE_TRAVAIL_CLIENT_SECRET pour recuperer les offres officielles."
        )
        return ""

    payload = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": os.getenv("FRANCE_TRAVAIL_SCOPE", "api_offresdemploiv2 o2dsoffre").strip(),
    }

    last_error = None
    for auth_url in AUTH_URLS:
        try:
            response = session.post(auth_url, data=payload, timeout=15)
            response.raise_for_status()
            token = response.json().get("access_token", "")
            if token:
                return token
        except Exception as e:
            last_error = e

    print(f"[France Travail] Authentification impossible: {last_error}")
    return ""


def _search(session: requests.Session, token: str, keyword: str, location: str, max_results: int) -> list[dict[str, Any]]:
    """Appelle l'endpoint de recherche d'offres France Travail."""
    commune = CITY_TO_COMMUNE.get(location)
    params = {
        "motsCles": keyword,
        "range": f"0-{max_results - 1}",
        "sort": 1,
    }
    if commune:
        params["commune"] = commune
        params["distance"] = 50
    elif location:
        params["lieux"] = location

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }

    last_error = None
    for search_url in SEARCH_URLS:
        try:
            response = session.get(search_url, headers=headers, params=params, timeout=20)
            # L'API renvoie souvent 206 Partial Content quand la pagination est valide.
            if response.status_code == 204:
                return []
            if response.status_code not in (200, 206):
                response.raise_for_status()
            return response.json().get("resultats", [])
        except Exception as e:
            last_error = e

    print(f"[France Travail] Recherche impossible pour '{keyword}' a '{location}': {last_error}")
    return []


def _format_company(raw: dict[str, Any]) -> str:
    """Récupère le nom d'entreprise quand l'API le fournit."""
    entreprise = raw.get("entreprise") or {}
    return unescape(entreprise.get("nom") or entreprise.get("description") or "Entreprise non précisée")


def _format_location(raw: dict[str, Any], fallback: str) -> str:
    """Convertit la structure lieuTravail en texte simple."""
    lieu = raw.get("lieuTravail") or {}
    return lieu.get("libelle") or lieu.get("commune") or fallback


def _format_contract(raw: dict[str, Any]) -> str:
    """Lit le type de contrat depuis la réponse API."""
    return raw.get("typeContratLibelle") or raw.get("natureContrat") or raw.get("typeContrat") or "Contrat"


def _to_text(value: Any) -> str:
    """Convertit les champs texte/listes de l'API en texte simple."""
    if not value:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                parts.append(item.get("libelle") or item.get("exigence") or item.get("description") or "")
            else:
                parts.append(str(item))
        return " ".join(part for part in parts if part)
    if isinstance(value, dict):
        return value.get("libelle") or value.get("description") or str(value)
    return str(value)


def _to_job(raw: dict[str, Any], location: str) -> dict:
    """Transforme une offre France Travail en dictionnaire commun du projet."""
    offer_id = raw.get("id", "")
    origin = raw.get("origineOffre") or {}
    url = origin.get("urlOrigine") or (f"https://candidat.francetravail.fr/offres/recherche/detail/{offer_id}" if offer_id else "")
    description = " ".join(
        part for part in [
            _to_text(raw.get("description")),
            _to_text(raw.get("profilRecherche")),
            _to_text(raw.get("competences")),
        ]
        if part
    )

    return {
        "title": unescape(raw.get("intitule") or "Titre non précisé"),
        "company": _format_company(raw),
        "location": _format_location(raw, location),
        "contract": _format_contract(raw),
        "description": unescape(description)[:2000],
        "url": url,
        "source": "france-travail",
    }


def run(keywords: list, locations: list, max_results: int = MAX_RESULTS_PER_QUERY) -> list[dict]:
    """Récupère les offres via l'API officielle France Travail."""
    session = requests.Session()
    token = _get_access_token(session)
    if not token:
        return []

    jobs = []
    seen_urls = set()

    for keyword in keywords:
        for location in locations:
            if len(jobs) >= max_results:
                break
            print(f"[France Travail] Recherche : '{keyword}' à '{location}'")
            raw_offers = _search(session, token, keyword, location, max_results)
            added = 0
            for raw in raw_offers:
                job = _to_job(raw, location)
                key = job["url"] or f"{job['title']}|{job['company']}|{job['location']}"
                if key in seen_urls:
                    continue
                seen_urls.add(key)
                jobs.append(job)
                added += 1
                if len(jobs) >= max_results:
                    break
            print(f"  -> {added} offre(s) France Travail")
            time.sleep(REQUEST_DELAY)

    return jobs[:max_results]
