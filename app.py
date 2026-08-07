# ============================================================
#  app.py — Serveur FastAPI principal
# ============================================================

import os
import json
import asyncio
import contextlib
import sqlite3
import logging
import requests
import unicodedata
import re
import textwrap
from urllib.parse import quote
from bs4 import BeautifulSoup
from pathlib import Path
from datetime import datetime, timedelta

from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Logging: INFO garde les messages utiles sans afficher toutes les requêtes urllib3.
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logging.getLogger("urllib3").setLevel(logging.WARNING)

# Import des modules existants
import sys
sys.path.insert(0, str(Path(__file__).parent))
from db import init_db, get_all_jobs, get_stats, get_connection
from config import DB_PATH
from email_alerts import send_alert, send_email, send_summary_email, get_email_status, EMAIL_CONFIG

app = FastAPI(title="Job Scraper Dashboard")
# Le dossier candidatures devient accessible depuis le navigateur via /candidatures/...
Path("candidatures").mkdir(exist_ok=True)
app.mount("/candidatures", StaticFiles(directory="candidatures"), name="candidatures")

# Profil réutilisé par l'IA pour signer les lettres et les emails.
# os.getenv permet de remplacer ces valeurs sans modifier le code.
CANDIDATE_PROFILE = {
    "name": os.getenv("CANDIDATE_NAME", "Marc DOWÉ"),
    "email": os.getenv("CANDIDATE_EMAIL", "mr.dev.rene@gmail.com"),
    "phone": os.getenv("CANDIDATE_PHONE", "+33 7 68 56 81 37"),
    "city": os.getenv("CANDIDATE_CITY", "Paris"),
}

DEFAULT_SOURCES = [
    "linkedin",
    "hellowork",
    "meteojob",
    "adzuna",
    "jooble",
    "france-travail",
]
DEFAULT_LOCATIONS = ["Paris", "Marseille", "Le Havre", "Bailleau-le-Pin"]

# Variables d'automatisation: elles pilotent le scraping automatique,
# l'intervalle entre deux passages et l'envoi du récap email.
AUTO_SPRINT_ENABLED = os.getenv("AUTO_SPRINT_ENABLED", "true").lower() not in ("0", "false", "no")
AUTO_SPRINT_INTERVAL_SECONDS = int(os.getenv("AUTO_SPRINT_INTERVAL_SECONDS", "3600"))
AUTO_EMAIL_ENABLED = os.getenv("AUTO_EMAIL_ENABLED", "true").lower() not in ("0", "false", "no")
AUTO_EMAIL_SINCE_HOURS = int(os.getenv("AUTO_EMAIL_SINCE_HOURS", "1"))
OFFER_MAX_AGE_DAYS = int(os.getenv("OFFER_MAX_AGE_DAYS", "10"))
auto_sprint_task = None
auto_sprint_lock = asyncio.Lock()
# Etat partagé avec le dashboard pour afficher ce que fait l'automatisation.
auto_sprint_state = {
    "enabled": AUTO_SPRINT_ENABLED,
    "running": False,
    "interval_seconds": AUTO_SPRINT_INTERVAL_SECONDS,
    "last_run": None,
    "next_run": None,
    "last_result": None,
    "last_error": None,
    "email_enabled": AUTO_EMAIL_ENABLED,
    "last_email_sent": None,
}

# Dossiers
UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)
CV_PATH = UPLOAD_DIR / "cv.pdf"

# ⚠️ Groq API Configuration
# Récupère ta clé d'API depuis : https://console.groq.com/keys
# Pour l'endpoint OpenAI-compatible, un champ model est nécessaire.
# Si tu ne veux pas forcer manuellement un modèle, le code utilise un fallback stable.
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b").strip()
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"


# ============================================================
#  Helpers Groq
# ============================================================
def _call_groq(messages: list, system: str = None, max_tokens: int = 1000) -> str:
    """Appelle l'API Groq directement via HTTP (sans SDK)."""
    try:
        # Vérifier si la clé API est valide
        if not GROQ_API_KEY or len(GROQ_API_KEY) < 20:
            error_msg = "❌ Clé API Groq invalide ou non configurée. Configure GROQ_API_KEY dans les variables d'environnement ou dans app.py"
            logger.error(error_msg)
            raise HTTPException(status_code=500, detail=error_msg)
        
        # Construire les messages avec le system prompt si fourni
        full_messages = []
        if system:
            full_messages.append({"role": "system", "content": system})
        full_messages.extend(messages)
        
        # Faire l'appel API directement
        logger.debug(f"Appel Groq: model={GROQ_MODEL}, messages={len(messages)}")
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": GROQ_MODEL,
            "messages": full_messages,
            "max_tokens": max_tokens,
            "temperature": 0.7,
        }
        response = requests.post(GROQ_API_URL, json=payload, headers=headers, timeout=30)
        
        if response.status_code != 200:
            error_detail = response.text
            logger.error(f"Groq API error ({response.status_code}): {error_detail}")
            raise HTTPException(status_code=502, detail=f"Groq API error: {error_detail[:200]}")
        
        result = response.json()
        # La réponse OpenAI-compatible place le texte généré dans choices[0].message.content.
        return result["choices"][0]["message"]["content"].strip()
        
    except HTTPException:
        raise
    except requests.RequestException as e:
        error_msg = f"Groq API request error: {str(e)}"
        logger.error(error_msg, exc_info=True)
        raise HTTPException(status_code=502, detail=error_msg)
    except Exception as e:
        error_msg = f"Groq API error: {type(e).__name__}: {str(e)}"
        logger.error(error_msg, exc_info=True)
        raise HTTPException(status_code=502, detail=error_msg)


def _extract_cv_text() -> str:
    """Extrait le texte du CV PDF via pypdf."""
    if not CV_PATH.exists():
        return ""
    try:
        import pypdf
        reader = pypdf.PdfReader(str(CV_PATH))
        # On limite à 4000 caractères pour ne pas envoyer un prompt trop grand à l'IA.
        return "\n".join(p.extract_text() or "" for p in reader.pages)[:4000]
    except Exception as e:
        return f"[Erreur extraction PDF: {e}]"


# ============================================================
#  DB helpers supplémentaires
# ============================================================
def _set_job_status(job_id: int, status: str):
    """Met à jour le statut d'une offre: new, saved, applied, closed, etc."""
    with sqlite3.connect(DB_PATH) as conn:
        # Ajoute la colonne si elle n'existe pas encore
        try:
            conn.execute("ALTER TABLE jobs ADD COLUMN status TEXT DEFAULT 'new'")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE jobs ADD COLUMN match_score INTEGER DEFAULT 0")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE jobs ADD COLUMN match_reason TEXT DEFAULT ''")
        except Exception:
            pass
        conn.execute("UPDATE jobs SET status=? WHERE id=?", (status, job_id))
        conn.commit()


def _get_jobs_extended() -> list[dict]:
    """Lit les offres avec les colonnes modernes, même si la base est ancienne."""
    with sqlite3.connect(DB_PATH) as conn:
        # Migration légère: on ajoute les colonnes manquantes au démarrage.
        for col, default in [
            ("status","'new'"),
            ("match_score","0"),
            ("match_reason","''"),
            ("apply_mode","''"),
            ("apply_url","''"),
            ("recruiter_email","''"),
            ("apply_instructions","''")
        ]:
            try:
                conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} TEXT DEFAULT {default}")
                conn.commit()
            except Exception:
                pass
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM jobs ORDER BY match_score DESC, found_at DESC").fetchall()
    return [dict(r) for r in rows]


def _save_match(job_id: int, score: int, reason: str):
    """Sauvegarde le score IA et son explication pour une offre."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "UPDATE jobs SET match_score=?, match_reason=? WHERE id=?",
            (score, reason, job_id)
        )
        conn.commit()


def _looks_unavailable(text: str) -> tuple[bool, str]:
    """Detecte les annonces expirees/fermees a partir du texte disponible."""
    # Normalisation: on retire accents et majuscules pour comparer plus facilement.
    haystack = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii").lower()
    closed_markers = [
        "offre pourvue",
        "offre expir",
        "offre n'est plus disponible",
        "offre non disponible",
        "annonce expir",
        "annonce n'est plus disponible",
        "poste pourvu",
        "candidatures fermees",
        "candidature fermee",
        "candidatures ne sont plus acceptees",
        "les candidatures ne sont plus acceptees",
        "candidatures plus acceptees",
        "candidature plus acceptee",
        "ne sont plus acceptees",
        "plus acceptees",
        "n'accepte plus de candidature",
        "n accepte plus de candidature",
        "n'acceptent plus de candidatures",
        "n acceptent plus de candidatures",
        "ne recrute plus",
        "job no longer available",
        "no longer accepting applications",
        "position has been filled",
        "applications are closed",
        "applications no longer accepted",
    ]
    for marker in closed_markers:
        if marker in haystack:
            # On retourne aussi le mot détecté pour pouvoir l'expliquer à l'utilisateur.
            return True, marker

    closed_patterns = [
        r"\bles\s+candidatures?\s+ne\s+sont\s+plus\s+accept.es\b",
        r"\bcandidatures?\s+ne\s+sont\s+plus\s+accept.es\b",
        r"\bne\s+sont\s+plus\s+accept.es\b",
        r"\bplus\s+accept.es\b",
    ]
    for pattern in closed_patterns:
        if re.search(pattern, haystack):
            return True, pattern
    return False, ""


def _parse_publication_date(text: str) -> datetime | None:
    """Trouve une date de publication explicite dans le texte d'une annonce."""
    if not text:
        return None

    # On ne lit que le début: les dates utiles sont souvent dans l'en-tête de l'annonce.
    raw = text[:10000]
    normalized = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode("ascii").lower()
    month_names = {
        "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
        "juillet": 7, "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12,
        "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
        "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    }

    iso_match = re.search(r"\b(20\d{2})-(\d{2})-(\d{2})\b", normalized)
    if iso_match:
        # Format ISO classique: 2026-05-10.
        year, month, day = map(int, iso_match.groups())
        try:
            return datetime(year, month, day)
        except ValueError:
            pass

    numeric_match = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](20\d{2})\b", normalized)
    if numeric_match:
        # Format français courant: 10/05/2026 ou 10-05-2026.
        day, month, year = map(int, numeric_match.groups())
        try:
            return datetime(year, month, day)
        except ValueError:
            pass

    named_match = re.search(
        r"\b(\d{1,2})\s+("
        + "|".join(month_names.keys())
        + r")\s+(20\d{2})\b",
        normalized,
    )
    if named_match:
        day = int(named_match.group(1))
        month = month_names[named_match.group(2)]
        year = int(named_match.group(3))
        try:
            return datetime(year, month, day)
        except ValueError:
            pass

    relative_match = re.search(r"\b(il y a|depuis|posted)\s+(\d+)\s+(jour|jours|day|days|semaine|semaines|week|weeks)\b", normalized)
    if relative_match:
        # Transforme "il y a 2 semaines" en date approximative.
        qty = int(relative_match.group(2))
        unit = relative_match.group(3)
        days = qty * 7 if unit in ("semaine", "semaines", "week", "weeks") else qty
        return datetime.now() - timedelta(days=days)

    return None


def _is_stale_offer(text: str) -> tuple[bool, str]:
    """Indique si l'offre est trop ancienne selon OFFER_MAX_AGE_DAYS."""
    published_at = _parse_publication_date(text)
    if not published_at:
        return False, ""
    age_days = (datetime.now() - published_at).days
    if age_days > OFFER_MAX_AGE_DAYS:
        return True, f"Offre trop ancienne: publiee le {published_at.strftime('%d/%m/%Y')} ({age_days} jours)"
    return False, ""


def _extract_linkedin_job_id(url: str) -> str:
    """Recupere l'identifiant LinkedIn meme si l'URL contient un slash ou des parametres."""
    if not url:
        return ""
    patterns = [
        r"/jobs/view/[^?#]*?-(\d{8,})(?:[/?#]|$)",
        r"/jobs/view/(\d{8,})(?:[/?#]|$)",
        r"currentJobId=(\d{8,})",
        r"\bjobPostingId=(\d{8,})",
        r"-(\d{8,})(?:[/?#]|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return ""


def _linkedin_cookies() -> dict:
    """Cookies optionnels pour lire la page LinkedIn connectee si l'utilisateur les fournit."""
    cookies = {}
    li_at = os.getenv("LINKEDIN_LI_AT", "").strip()
    if li_at:
        cookies["li_at"] = li_at

    raw_cookie = os.getenv("LINKEDIN_COOKIE", "").strip()
    if raw_cookie:
        for part in raw_cookie.split(";"):
            if "=" not in part:
                continue
            key, value = part.split("=", 1)
            key = key.strip()
            value = value.strip()
            if key and value:
                cookies[key] = value
    return cookies


def _check_job_page_availability(job: dict) -> tuple[bool, str]:
    """Verification legere avant l'analyse IA."""
    # Premier filtre sans requête réseau: on inspecte le texte déjà stocké.
    combined = " ".join([
        str(job.get("title", "")),
        str(job.get("company", "")),
        str(job.get("description", "")),
    ])
    unavailable, reason = _looks_unavailable(combined)
    if unavailable:
        return False, f"Signal detecte dans l'offre: {reason}"
    stale, stale_reason = _is_stale_offer(combined)
    if stale:
        return False, stale_reason

    url = job.get("url") or ""
    if not url.startswith(("http://", "https://")):
        return True, ""

    try:
        requests_to_check = [(url, None)]
        if "linkedin.com/jobs" in url:
            # LinkedIn a plusieurs formats d'URL; on teste d'abord l'endpoint public.
            linkedin_job_id = _extract_linkedin_job_id(url)
            linkedin_cookies = _linkedin_cookies()
            if linkedin_job_id and linkedin_cookies:
                requests_to_check.insert(0, (f"https://www.linkedin.com/jobs/view/{linkedin_job_id}/", linkedin_cookies))
            if linkedin_job_id:
                requests_to_check.insert(0, (f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{linkedin_job_id}", None))

        for check_url, cookies in requests_to_check:
            # Vérification simple de la page: statut HTTP + texte visible.
            response = requests.get(
                check_url,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
                },
                cookies=cookies,
                timeout=10,
            )
            if response.status_code in (404, 410):
                return False, f"Page indisponible HTTP {response.status_code}"
            if response.status_code >= 500:
                continue
            page_text = BeautifulSoup(response.text, "html.parser").get_text(" ", strip=True)[:10000]
            unavailable, reason = _looks_unavailable(page_text)
            if unavailable:
                return False, f"Signal detecte sur la page: {reason}"
            stale, stale_reason = _is_stale_offer(page_text)
            if stale:
                return False, stale_reason
    except Exception:
        return True, ""

    return True, ""


def _analyze_match(job: dict, cv_text: str) -> dict:
    """Demande à l'IA de noter l'adéquation entre le CV et l'offre."""
    available, availability_reason = _check_job_page_availability(job)
    if not available:
        return {
            "score": 0,
            "reason": availability_reason or "Offre indisponible.",
            "available": False,
            "status": "closed",
        }

    risks = _detect_match_risks(job, cv_text)
    risk_text = "\n".join(f"- {risk}" for risk in risks) if risks else "- Aucun signal bloquant detecte automatiquement."
    score_cap = _score_cap_from_risks(risks)

    # Prompt strict: on demande du JSON pour pouvoir relire automatiquement la réponse.
    prompt = f"""Tu es un expert RH et assistant de candidature.
Analyse cette offre avec exigence. Tu dois lire tous les prerequis de l'offre, pas seulement le titre.
Tu dois aussi detecter si l'offre semble expiree, deja pourvue, ou si elle n'accepte plus les candidatures.

CV:
{cv_text[:3500]}

OFFRE:
Titre: {job.get('title', '')}
Entreprise: {job.get('company', '')}
Localisation: {job.get('location', '')}
Contrat: {job.get('contract', '')}
Description complete disponible:
{job.get('description', '')[:3500]}
URL: {job.get('url', '')}

SIGNAUX AUTOMATIQUES A VERIFIER ET A RESPECTER:
{risk_text}
Plafond de score recommande par ces signaux: {score_cap}/100. Ne le depasse pas sauf justification evidente dans le CV.

Retourne UNIQUEMENT un JSON exact:
{{
  "disponible": true,
  "score": 0,
  "raison": "3 phrases max. Cite les prerequis bloquants si niveau diplome, experience ou competences manquent.",
  "motif_indisponibilite": "",
  "actions": "Action concrete courte pour postuler mieux"
}}

Regles:
- Si l'offre parait expiree, pourvue, supprimee, ou fermee aux candidatures, mets "disponible": false et "score": 0.
- Si une date de publication explicite est trop ancienne ou anterieure a la fenetre recente attendue, mets "disponible": false et explique la date.
- Ne surestime pas le score: 80+ seulement si le CV correspond tres fortement aux missions, competences et contrat.
- Si l'offre demande Licence/Bac+3/Niveau 6 et que le CV montre BTS/premiere experience, score max 35 sauf mention explicite que le niveau est optionnel.
- Si l'offre demande experience confirmee, Symfony, PHP, PostgreSQL/MariaDB, Vue.js, securite ou administration production et que ce n'est pas prouve dans le CV, penalise fortement.
- Penalise les offres trop seniors, hors localisation, hors contrat recherche, ou avec peu d'informations."""

    response = _call_groq([{"role": "user", "content": prompt}], max_tokens=700)
    result = _parse_json_response(response)
    # L'IA peut renvoyer true/false en booléen ou en texte; on sécurise les deux cas.
    raw_available = result.get("disponible", True)
    if isinstance(raw_available, str):
        is_available = raw_available.strip().lower() not in ("false", "non", "no", "0")
    else:
        is_available = bool(raw_available)
    if not is_available:
        return {
            "score": 0,
            "reason": result.get("motif_indisponibilite") or result.get("raison") or "Offre fermee ou indisponible.",
            "available": False,
            "status": "closed",
        }

    score = max(0, min(100, int(result.get("score", 50))))
    if score > score_cap:
        score = score_cap
    reason = result.get("raison") or "Analyse disponible, mais justification courte absente."
    if risks:
        reason = f"{reason} Points bloquants detectes: {'; '.join(risks[:4])}"
    action = result.get("actions")
    if action:
        reason = f"{reason} Action conseillee: {action}"
    return {"score": score, "reason": reason, "available": True, "status": "new"}


def _run_matching_batch(limit: int = 20) -> int:
    """Analyse automatiquement un lot d'offres non encore scorées."""
    cv_text = _extract_cv_text()
    if not cv_text:
        return 0

    jobs = _get_jobs_extended()
    unscored = [
        # On évite de rescorrer les offres déjà traitées ou fermées.
        j for j in jobs
        if (j.get("match_score") or 0) == 0
        and (j.get("status") or "new") not in ("applied", "closed")
    ]

    matched = 0
    for job in unscored[:limit]:
        try:
            analysis = _analyze_match(job, cv_text)
            _save_match(job["id"], analysis["score"], analysis["reason"])
            if not analysis["available"]:
                _set_job_status(job["id"], "closed")
            matched += 1
        except Exception as e:
            logger.warning("Matching failed for job %s: %s", job.get("id"), e)
    return matched


def _cleanup_unavailable_jobs(limit: int = 200) -> int:
    """Déplace en closed les offres détectées comme expirées ou indisponibles."""
    jobs = _get_jobs_extended()
    checked = 0
    closed = 0
    for job in jobs:
        if checked >= limit:
            break
        if (job.get("status") or "new") in ("applied", "closed"):
            continue
        checked += 1
        available, reason = _check_job_page_availability(job)
        if not available:
            _save_match(job["id"], 0, reason)
            _set_job_status(job["id"], "closed")
            closed += 1
    return closed


def _run_sprint_sync() -> dict:
    """Exécute un cycle complet: scraping, nettoyage, matching et email."""
    from main import run_scraper

    before_total = get_stats().get("total", 0)
    # run_scraper remplit la base; les étapes suivantes exploitent cette base.
    run_scraper(DEFAULT_SOURCES, DEFAULT_LOCATIONS)
    after_total = get_stats().get("total", 0)
    closed = _cleanup_unavailable_jobs(limit=200)
    matched = _run_matching_batch(limit=20)
    email_sent = False
    if AUTO_EMAIL_ENABLED:
        email_sent = send_summary_email(since_hours=AUTO_EMAIL_SINCE_HOURS)
    return {
        "new_jobs": max(0, after_total - before_total),
        "matched": matched,
        "closed": closed,
        "email_sent": email_sent,
        "sources": DEFAULT_SOURCES,
        "locations": DEFAULT_LOCATIONS,
    }


async def _run_auto_sprint_once(reason: str = "auto") -> dict:
    """Lance un sprint en arrière-plan, protégé contre les doubles lancements."""
    if auto_sprint_lock.locked():
        return {"status": "skipped", "reason": "already_running"}

    async with auto_sprint_lock:
        # Le lock évite deux sprints simultanés qui écriraient dans la même base.
        auto_sprint_state["running"] = True
        auto_sprint_state["last_error"] = None
        try:
            result = await asyncio.to_thread(_run_sprint_sync)
            now = datetime.now().isoformat(timespec="seconds")
            auto_sprint_state["last_run"] = now
            auto_sprint_state["last_result"] = {**result, "reason": reason}
            if result.get("email_sent"):
                auto_sprint_state["last_email_sent"] = now
            return {"status": "done", **result}
        except Exception as e:
            auto_sprint_state["last_error"] = str(e)
            logger.error("Auto sprint failed: %s", e, exc_info=True)
            return {"status": "error", "error": str(e)}
        finally:
            auto_sprint_state["running"] = False


async def _auto_sprint_loop():
    """Boucle infinie qui attend l'intervalle configuré entre deux sprints."""
    while True:
        auto_sprint_state["next_run"] = datetime.fromtimestamp(
            datetime.now().timestamp() + AUTO_SPRINT_INTERVAL_SECONDS
        ).isoformat(timespec="seconds")
        await asyncio.sleep(AUTO_SPRINT_INTERVAL_SECONDS)
        if auto_sprint_state["enabled"]:
            await _run_auto_sprint_once("hourly")


def _save_apply_info(job_id: int, info: dict):
    """Mémorise la stratégie de candidature proposée par l'IA."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "UPDATE jobs SET apply_mode=?, apply_url=?, recruiter_email=?, apply_instructions=? WHERE id=?",
            (
                info.get("apply_mode", ""),
                info.get("apply_url", ""),
                info.get("recruiter_email", ""),
                info.get("instructions", ""),
                job_id,
            )
        )
        conn.commit()


def _parse_json_response(text: str) -> dict:
    """Récupère un objet JSON même si l'IA ajoute du texte autour."""
    clean = text.strip().lstrip("```json").rstrip("```").strip()
    try:
        return json.loads(clean)
    except Exception:
        try:
            return json.loads(clean.split('\n', 1)[-1])
        except Exception:
            return {}


def _infer_application_strategy(job: dict, cv_text: str) -> dict:
    """Demande à l'IA s'il faut postuler par email, site web ou autre action."""
    # La réponse est demandée en JSON pour pouvoir alimenter automatiquement l'UI.
    prompt = f"""Tu es un assistant d'automatisation de candidatures.
Analyse cette offre et dis comment postuler de la manière la plus directe et adaptée.

Offre:
Titre : {job['title']}
Entreprise : {job['company']}
Localisation : {job.get('location', 'Non précisée')}
Contrat : {job.get('contract', 'Non précisé')}
Description : {job.get('description', 'Non disponible')[:1200]}
URL : {job.get('url', '')}

Réponds UNIQUEMENT en JSON exact avec ces clés :
{{
  "apply_mode": "email" | "website" | "other",
  "apply_url": "URL de candidature ou URL de l'annonce",
  "recruiter_email": "email du recruteur ou du service RH si disponible",
  "instructions": "Instruction courte pour l'action à faire",
  "subject": "Sujet recommandé si email",
  "body": "Texte du message ou email à envoyer"
}}

Si l'offre indique un envoi par email, remplis recruiter_email.
Si l'offre demande une candidature via un formulaire ou un site, mets apply_mode sur "website" et donne apply_url.
Si tu n'es pas sûr, mets apply_mode sur "other" et décris la procédure dans instructions."""
    response = _call_groq([{"role": "user", "content": prompt}], max_tokens=600)
    result = _parse_json_response(response)
    if not result.get("apply_mode"):
        result = {
            "apply_mode": "website",
            "apply_url": job.get("url", ""),
            "recruiter_email": "",
            "instructions": "Ouvre l'annonce et postule via le site du recruteur.",
            "subject": "",
            "body": "",
        }
    return result


# ============================================================
#  Routes API
# ============================================================

@app.on_event("startup")
async def startup():
    """Prépare la base et démarre la boucle automatique au lancement du serveur."""
    global auto_sprint_task
    init_db()
    if auto_sprint_task is None:
        auto_sprint_task = asyncio.create_task(_auto_sprint_loop())


@app.on_event("shutdown")
async def shutdown():
    """Arrête proprement la tâche automatique quand le serveur s'éteint."""
    global auto_sprint_task
    if auto_sprint_task:
        auto_sprint_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await auto_sprint_task
        auto_sprint_task = None


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Renvoie le fichier HTML principal du dashboard."""
    html_path = Path(__file__).parent / "templates" / "dashboard.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


# ── Test Groq ───────────────────────────────────────────────
@app.get("/api/test-groq")
async def test_groq():
    """Test la connexion et configuration de Groq API."""
    try:
        # Vérifier la clé API
        if not GROQ_API_KEY or len(GROQ_API_KEY) < 20:
            return {
                "status": "error",
                "message": "❌ Clé API Groq invalide ou non configurée",
                "hint": "Configure GROQ_API_KEY: https://console.groq.com/keys",
                "current_key": GROQ_API_KEY[:10] + "..." if GROQ_API_KEY else "NONE"
            }
        
        # Tester l'appel API
        logger.info("Testing Groq API connection...")
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": GROQ_MODEL,
            "messages": [{"role": "user", "content": "Dis simplement 'OK'"}],
            "max_tokens": 10,
            "temperature": 0.7,
        }
        
        response = requests.post(GROQ_API_URL, json=payload, headers=headers, timeout=30)
        
        if response.status_code != 200:
            return {
                "status": "error",
                "message": f"❌ Erreur Groq ({response.status_code})",
                "error": response.text[:500],
                "model": GROQ_MODEL,
                "api_key_valid": False
            }
        
        result = response.json()
        test_response = result["choices"][0]["message"]["content"].strip()
        
        return {
            "status": "success",
            "message": "✅ Groq API fonctionne correctement!",
            "model": GROQ_MODEL,
            "test_response": test_response,
            "api_key_valid": True
        }
    except Exception as e:
        logger.error(f"Groq test failed: {e}", exc_info=True)
        return {
            "status": "error",
            "message": f"❌ Erreur Groq: {type(e).__name__}",
            "error": str(e),
            "model": GROQ_MODEL,
            "api_key_configured": bool(GROQ_API_KEY and len(GROQ_API_KEY) > 10)
        }


# ── CV ──────────────────────────────────────────────────────
@app.post("/api/cv/upload")
async def upload_cv(file: UploadFile = File(...)):
    """Reçoit un CV PDF depuis le navigateur et le stocke dans uploads/cv.pdf."""
    if not file.filename.endswith(".pdf"):
        raise HTTPException(400, "Seuls les fichiers PDF sont acceptés.")
    content = await file.read()
    CV_PATH.write_bytes(content)
    text = _extract_cv_text()
    return {"status": "ok", "preview": text[:500], "chars": len(text)}


@app.get("/api/cv/status")
async def cv_status():
    """Indique au dashboard si un CV est déjà disponible."""
    exists = CV_PATH.exists()
    text = _extract_cv_text() if exists else ""
    return {"uploaded": exists, "preview": text[:300], "chars": len(text)}


# ── Offres ──────────────────────────────────────────────────
@app.get("/api/jobs")
async def list_jobs(source: str = None, status: str = None, min_score: int = 0, include_history: bool = False):
    """Liste les offres avec filtres facultatifs pour l'interface."""
    jobs = _get_jobs_extended()
    # Par défaut, l'interface principale masque les offres déjà postulées ou fermées.
    if not include_history and not status:
        jobs = [j for j in jobs if (j.get("status") or "new") not in ("applied", "closed")]
    if source:
        jobs = [j for j in jobs if j["source"] == source]
    if status:
        jobs = [j for j in jobs if (j.get("status") or "new") == status]
    if min_score:
        jobs = [j for j in jobs if (j.get("match_score") or 0) >= min_score]
    return jobs


@app.get("/api/stats")
async def stats():
    """Construit les statistiques et catégories affichées sur le dashboard."""
    s = get_stats()
    jobs = _get_jobs_extended()
    active_jobs = [j for j in jobs if (j.get("status") or "new") not in ("applied", "closed")]
    history_jobs = [j for j in jobs if (j.get("status") or "new") in ("applied", "closed")]
    scored = [j for j in active_jobs if (j.get("match_score") or 0) > 0]
    hot_jobs = [j for j in active_jobs if (j.get("match_score") or 0) >= 65]
    followups = [j for j in jobs if (j.get("status") or "new") in ("applied", "interview", "saved")]
    top_jobs = sorted(active_jobs, key=lambda j: ((j.get("match_score") or 0), j.get("found_at", "")), reverse=True)[:5]

    # Classer toutes les offres par catégories pour simplifier le rendu côté JS.
    categorized_jobs = {
        "hot_opportunities": [j for j in active_jobs if (j.get("match_score") or 0) >= 65],
        "good_matches": [j for j in active_jobs if 40 <= (j.get("match_score") or 0) < 65],
        "new": [j for j in active_jobs if (j.get("status") or "new") == "new" and (j.get("match_score") or 0) < 40],
        "others": [j for j in active_jobs if (j.get("status") or "new") not in ("new",) and (j.get("match_score") or 0) < 40],
        "history": history_jobs,
    }

    return {
        **s,
        "cv_uploaded": CV_PATH.exists(),
        "active_total": len(active_jobs),
        "history_total": len(history_jobs),
        "scored": len(scored),
        "avg_score": round(sum(j["match_score"] for j in scored) / len(scored)) if scored else 0,
        "hot_opportunities": len(hot_jobs),
        "followups_due": len(followups),
        "top_jobs": top_jobs,
        "all_jobs": categorized_jobs,
    }


@app.post("/api/jobs/{job_id}/status")
async def update_status(job_id: int, body: dict):
    """Change manuellement le statut d'une offre depuis le dashboard."""
    status = body.get("status", "new")
    if status not in ("new", "saved", "applied", "interview", "rejected", "closed"):
        raise HTTPException(400, "Statut invalide")
    _set_job_status(job_id, status)
    return {"ok": True}


# ── Matching CV ─────────────────────────────────────────────
@app.post("/api/jobs/{job_id}/match")
async def match_job(job_id: int):
    """Lance le scoring IA pour une seule offre."""
    cv_text = _extract_cv_text()
    if not cv_text:
        raise HTTPException(400, "Aucun CV uploadé. Charge ton CV d'abord.")

    jobs = _get_jobs_extended()
    job = next((j for j in jobs if j["id"] == job_id), None)
    if not job:
        raise HTTPException(404, "Offre introuvable")

    analysis = _analyze_match(job, cv_text)
    score = analysis["score"]
    reason = analysis["reason"]
    _save_match(job_id, score, reason)
    if not analysis["available"]:
        _set_job_status(job_id, "closed")
    return {"score": score, "reason": reason, "available": analysis["available"]}


@app.post("/api/match-all")
async def match_all_jobs(background_tasks: BackgroundTasks, sync: bool = False):
    """Score plusieurs offres, soit immédiatement, soit en arrière-plan."""
    cv_text = _extract_cv_text()
    if not cv_text:
        raise HTTPException(400, "Aucun CV uploadé.")

    def _run():
        # Fonction interne exécutée par FastAPI en tâche de fond si sync=False.
        jobs = _get_jobs_extended()
        unscored = [
            j for j in jobs
            if (j.get("match_score") or 0) == 0
            and (j.get("status") or "new") not in ("applied", "closed")
        ]
        matched = 0
        for job in unscored[:20]:  # max 20 à la fois
            try:
                analysis = _analyze_match(job, cv_text)
                _save_match(job["id"], analysis["score"], analysis["reason"])
                if not analysis["available"]:
                    _set_job_status(job["id"], "closed")
                matched += 1
            except Exception:
                pass
        return matched

    if sync:
        matched = _run()
        return {"status": "done", "matched": matched}

    background_tasks.add_task(_run)
    return {"status": "started", "message": "Matching en cours en arrière-plan..."}


# ── Génération de lettre ────────────────────────────────────
@app.post("/api/jobs/{job_id}/letter")
async def generate_letter(job_id: int, body: dict):
    """Génère une lettre, un email, ou les deux pour une offre."""
    fmt = body.get("format", "both")  # "letter", "email", "both"
    cv_text = _extract_cv_text()

    jobs = _get_jobs_extended()
    job = next((j for j in jobs if j["id"] == job_id), None)
    if not job:
        raise HTTPException(404, "Offre introuvable")

    result = _build_application_text(job, cv_text, fmt)
    paths = _save_application_files(job, result)
    return {**result, "paths": paths}


def _build_application_text(job, cv_text, fmt="both"):
    """Construit les prompts IA et renvoie les textes de candidature."""
    cv_context = f"\nCV du candidat :\n{cv_text[:2000]}" if cv_text else ""
    result = {}
    # identity est injecté dans le prompt pour éviter que l'IA invente des coordonnées.
    identity = (
        f"\nCoordonnees exactes du candidat a utiliser sans modification :\n"
        f"Nom : {CANDIDATE_PROFILE['name']}\n"
        f"Email : {CANDIDATE_PROFILE['email']}\n"
        f"Telephone : {CANDIDATE_PROFILE['phone']}\n"
        f"Ville : {CANDIDATE_PROFILE['city']}\n"
    )

    if fmt in ("letter", "both"):
        prompt = f"""Rédige une lettre de motivation professionnelle en français pour ce poste.{identity}{cv_context}

Offre : {job['title']} chez {job['company']} ({job['location']})
Description : {job.get('description','')[:600]}

Consignes : 3 paragraphes percutants, ton pro mais humain, 230 mots max.
Termine avec exactement les coordonnees donnees. N'invente jamais une autre adresse email ou un autre numero.
La lettre doit tenir sur une seule page PDF. Evite les espaces et tirets typographiques invisibles. Uniquement la lettre."""
        result["letter"] = _normalize_application_text(_call_groq([{"role": "user", "content": prompt}], max_tokens=750))

    if fmt in ("email", "both"):
        prompt = f"""Rédige un email de candidature court et percutant en français.{identity}{cv_context}

Poste : {job['title']} | Entreprise : {job['company']}
Description : {job.get('description','')[:400]}

Format : "Objet : ..." puis le corps (5 lignes max). Termine avec les coordonnees exactes. Uniquement l'email."""
        result["email"] = _normalize_application_text(_call_groq([{"role": "user", "content": prompt}], max_tokens=500))

    return result


def _normalize_application_text(text: str) -> str:
    """Nettoie le texte IA et force l'email officiel du candidat."""
    clean = _clean_typography(text)
    clean = re.sub(r"[\w.+\-À-ÿ]+@\s*[\w.\-À-ÿ]+\.\w+", CANDIDATE_PROFILE["email"], clean)
    clean = re.sub(r"m\.?\s*r\.?\s*dev\.?\s*r[èe]ne\s*@\s*gmail\.com", CANDIDATE_PROFILE["email"], clean, flags=re.I)

    if CANDIDATE_PROFILE["email"] not in clean:
        # Sécurité: si l'IA oublie les coordonnées, on les ajoute à la fin.
        clean = clean.rstrip() + f"\n\n{CANDIDATE_PROFILE['name']}\n{CANDIDATE_PROFILE['email']} - {CANDIDATE_PROFILE['phone']}"

    return clean.strip()


def _clean_typography(text: str) -> str:
    """Remplace les espaces/tirets invisibles par des caractères simples."""
    replacements = {
        "\u00a0": " ",
        "\u202f": " ",
        "\u2009": " ",
        "\u200b": "",
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
        "\ufeff": "",
    }
    clean = text or ""
    for old, new in replacements.items():
        clean = clean.replace(old, new)
    return clean


def _normalize_text(text: str) -> str:
    """Retire accents et majuscules pour les comparaisons simples."""
    return unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii").lower()


def _detect_candidate_level(cv_text: str) -> dict:
    """Déduit grossièrement le niveau du candidat depuis le CV extrait."""
    text = _normalize_text(cv_text)
    is_bts = "bts" in text
    is_student = any(term in text for term in ("etudiant", "alternance", "stage", "junior"))
    has_licence = any(term in text for term in ("licence", "bachelor", "bac+3", "bac +3", "niveau 6", "master", "bac+5", "bac +5"))
    if has_licence:
        level = "licence_plus"
    elif is_bts:
        level = "bts"
    else:
        level = "junior"
    return {"level": level, "is_student": is_student, "has_licence": has_licence}


def _detect_match_risks(job: dict, cv_text: str) -> list[str]:
    """Repère les prérequis durs qui doivent peser fortement dans le score."""
    offer = _normalize_text(" ".join(str(job.get(k, "")) for k in ("title", "contract", "description")))
    cv = _normalize_text(cv_text)
    candidate = _detect_candidate_level(cv_text)
    risks = []

    if re.search(r"\bniveau\s*6\b|\blicence\b|\bbac\s*\+?\s*3\b|\bbachelor\b", offer) and not candidate["has_licence"]:
        risks.append("Prerequis diplome: l'offre demande un niveau Licence/Bac+3/Niveau 6, alors que le CV indique surtout BTS SIO/developpeur junior.")
    if re.search(r"\b(master|bac\s*\+?\s*5|niveau\s*7|ingenieur)\b", offer) and "master" not in cv and "ingenieur" not in cv:
        risks.append("Prerequis diplome eleve: l'offre semble demander Bac+5/ingenieur, non visible dans le CV.")
    if re.search(r"\bexperience\s+(confirmee|significative|solide)|\bconfirme\b|\bsenior\b|\bexpert\b", offer):
        risks.append("Experience attendue: l'offre demande un profil confirme/senior, plus eleve que le CV junior/etudiant.")

    skill_checks = [
        ("Symfony", r"\bsymfony\b"),
        ("PHP", r"\bphp\b"),
        ("PostgreSQL", r"\bpostgresql\b|\bpostgres\b"),
        ("MariaDB", r"\bmariadb\b"),
        ("Vue.js", r"\bvue\.?js\b|\bvue\b"),
        ("administration environnement production", r"\badministr|production|infrastructure|deploiement\b"),
        ("securisation applicative", r"\bsecuris|securite|security\b"),
    ]
    for label, pattern in skill_checks:
        if re.search(pattern, offer) and not re.search(pattern, cv):
            risks.append(f"Competence manquante ou non prouvee dans le CV: {label}.")

    if len(risks) >= 4:
        risks.append("Accumulation de prerequis durs: candidature possible seulement si l'offre accepte vraiment un profil tres junior.")
    return risks


def _score_cap_from_risks(risks: list[str]) -> int:
    """Plafonne le score quand les prérequis bloquants sont nombreux."""
    hard = sum(1 for risk in risks if risk.startswith(("Prerequis", "Experience", "Accumulation")))
    missing_skills = sum(1 for risk in risks if risk.startswith("Competence"))
    if hard >= 2 or (hard >= 1 and missing_skills >= 3):
        return 35
    if hard >= 1 or missing_skills >= 4:
        return 45
    if missing_skills >= 2:
        return 60
    return 100


def _save_application_files(job, result):
    """Sauvegarde les textes générés et crée aussi le PDF de la lettre."""
    out_dir = Path("candidatures")
    out_dir.mkdir(exist_ok=True)
    safe = lambda s: "".join(c for c in s if c.isalnum() or c in " -_").strip()
    # safe retire les caractères dangereux pour fabriquer un nom de fichier Windows.
    base = out_dir / f"{safe(job['company'])}_{safe(job['title'])}"
    paths = {}

    if "letter" in result:
        letter_path = Path(str(base) + "_lettre.txt")
        letter_path.write_text(result["letter"], encoding="utf-8")
        paths["letter"] = str(letter_path)
        pdf_path = Path(str(base) + "_lettre.pdf")
        _write_letter_pdf(pdf_path, job, result["letter"])
        paths["letter_pdf"] = str(pdf_path)
        paths["letter_pdf_url"] = "/" + quote(str(pdf_path).replace("\\", "/"))
    if "email" in result:
        email_path = Path(str(base) + "_email.txt")
        email_path.write_text(result["email"], encoding="utf-8")
        paths["email"] = str(email_path)

    return paths


def _pdf_escape(text: str) -> bytes:
    """Échappe les caractères spéciaux avant de les écrire dans le PDF brut."""
    clean = _clean_typography(text or "")
    clean = clean.replace("’", "'").replace("“", '"').replace("”", '"')
    clean = clean.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return clean.encode("cp1252", errors="replace")


def _wrap_pdf_text(text: str, width: int = 92) -> list[str]:
    """Coupe les longs paragraphes en lignes adaptées à la largeur du PDF."""
    lines = []
    for paragraph in (text or "").splitlines():
        paragraph = paragraph.strip()
        if not paragraph:
            lines.append("")
            continue
        lines.extend(textwrap.wrap(paragraph, width=width, break_long_words=False) or [""])
    return lines


def _pdf_text_width(text: str, size: int) -> float:
    """Approxime la largeur d'une ligne Helvetica pour les alignements."""
    return len(_clean_typography(text or "")) * size * 0.50


def _pdf_text(stream: bytearray, text: str, x: int, y: int, size: int = 11, color: tuple[float, float, float] = (0, 0, 0), width: int | None = None, align: str = "left"):
    """Ajoute une ligne de texte dans le flux PDF à une position donnée."""
    if width and align in ("center", "right"):
        text_width = _pdf_text_width(text, size)
        if align == "center":
            x = int(x + max(0, (width - text_width) / 2))
        else:
            x = int(x + max(0, width - text_width))
    r, g, b = color
    stream.extend(f"{r:.3f} {g:.3f} {b:.3f} rg\n".encode("ascii"))
    stream.extend(b"BT\n")
    stream.extend(f"/F1 {size} Tf\n{x} {y} Td\n".encode("ascii"))
    stream.extend(b"(" + _pdf_escape(text) + b") Tj\n")
    stream.extend(b"ET\n")


def _pdf_wrapped_text(stream: bytearray, lines: list[str], x: int, y: int, size: int = 11, leading: int = 16, color: tuple[float, float, float] = (0.13, 0.13, 0.13), width: int | None = None, align: str = "left"):
    """Ajoute plusieurs lignes de texte dans le PDF avec un interligne."""
    current_y = y
    for line in lines:
        if line:
            _pdf_text(stream, line, x, current_y, size, color, width=width, align=align)
        current_y -= leading


PDF_DESIGNS = {
    "data": {
        "name": "Data",
        "bg": (0.955, 0.972, 0.976),
        "primary": (0.045, 0.236, 0.285),
        "accent": (0.000, 0.560, 0.620),
        "soft": (0.820, 0.930, 0.940),
        "text": (0.120, 0.160, 0.180),
    },
    "digital": {
        "name": "Digital",
        "bg": (0.965, 0.968, 0.985),
        "primary": (0.145, 0.200, 0.410),
        "accent": (0.420, 0.260, 0.720),
        "soft": (0.870, 0.890, 0.980),
        "text": (0.110, 0.130, 0.190),
    },
    "business": {
        "name": "Business",
        "bg": (0.975, 0.965, 0.945),
        "primary": (0.300, 0.115, 0.120),
        "accent": (0.720, 0.500, 0.200),
        "soft": (0.940, 0.880, 0.760),
        "text": (0.160, 0.130, 0.110),
    },
}


def _choose_pdf_design(job: dict) -> dict:
    """Choisit un theme PDF selon les signaux de l'offre."""
    text = _normalize_text(" ".join(str(job.get(k, "")) for k in ("title", "company", "contract", "description", "source")))
    if any(term in text for term in ("data", "analytics", "analyst", "python", "ia", "ai", "machine learning", "bi")):
        return PDF_DESIGNS["data"]
    if any(term in text for term in ("front", "web", "javascript", "react", "ux", "ui", "design", "developpeur", "developer")):
        return PDF_DESIGNS["digital"]
    if any(term in text for term in ("banque", "finance", "assurance", "business", "consult", "commercial", "marketing")):
        return PDF_DESIGNS["business"]
    return PDF_DESIGNS["digital"]


def _pdf_rgb(color: tuple[float, float, float], op: str = "rg") -> bytes:
    return f"{color[0]:.3f} {color[1]:.3f} {color[2]:.3f} {op}\n".encode("ascii")


def _build_pdf_page(lines: list[str], job: dict, page_number: int, body_size: int = 10, body_leading: int = 15) -> bytes:
    """Construit le contenu graphique d'une page PDF."""
    stream = bytearray()
    design = _choose_pdf_design(job)
    bg = design["bg"]
    primary = design["primary"]
    accent = design["accent"]
    soft = design["soft"]
    text_color = design["text"]

    # Fond de page, bande d'identite et accent adapte a l'offre.
    stream.extend(_pdf_rgb(bg) + b"0 0 595 842 re f\n")
    stream.extend(_pdf_rgb(primary) + b"0 0 156 842 re f\n")
    stream.extend(_pdf_rgb(accent) + b"156 0 8 842 re f\n")
    stream.extend(_pdf_rgb(soft) + b"36 724 84 84 re f\n")
    stream.extend(_pdf_rgb(accent) + b"44 732 68 68 re f\n")
    stream.extend(_pdf_rgb(accent, "RG") + b"190 758 m 546 758 l S\n")
    stream.extend(_pdf_rgb(soft) + b"190 54 356 688 re f\n")
    stream.extend(b"1 1 1 rg\n202 66 332 664 re f\n")

    initials = "".join(part[:1] for part in CANDIDATE_PROFILE["name"].split()[:2]).upper()
    _pdf_text(stream, initials, 44, 758, 22, (1, 1, 1), width=68, align="center")
    _pdf_wrapped_text(stream, _wrap_pdf_text(CANDIDATE_PROFILE["name"], 20)[:2], 24, 684, 14, 17, (1, 1, 1), width=108, align="center")
    _pdf_text(stream, design["name"], 24, 642, 9, soft, width=108, align="center")
    _pdf_text(stream, CANDIDATE_PROFILE["email"], 20, 594, 8, (1, 1, 1))
    _pdf_text(stream, CANDIDATE_PROFILE["phone"], 20, 576, 8, (1, 1, 1))
    _pdf_text(stream, CANDIDATE_PROFILE["city"], 20, 558, 8, (1, 1, 1))

    _pdf_text(stream, "Offre", 24, 492, 10, soft)
    _pdf_wrapped_text(stream, _wrap_pdf_text(str(job.get("title", "")), 23)[:5], 24, 468, 8, 12, (1, 1, 1))
    _pdf_wrapped_text(stream, _wrap_pdf_text(str(job.get("company", "")), 22)[:2], 24, 392, 9, 12, (1, 1, 1))
    _pdf_text(stream, str(job.get("location", ""))[:24], 24, 360, 8, soft)

    main_x = 222
    main_w = 292
    _pdf_text(stream, f"{CANDIDATE_PROFILE['city']}, le {datetime.now().strftime('%d/%m/%Y')}", main_x, 714, 9, (0.42, 0.42, 0.42), width=main_w, align="right")
    _pdf_text(stream, "Lettre de motivation", main_x, 676, 21, text_color, width=main_w, align="center")
    _pdf_wrapped_text(stream, _wrap_pdf_text(f"{job.get('company', '')} - {job.get('title', '')}", 54)[:2], main_x, 650, 9, 12, accent, width=main_w, align="center")
    stream.extend(_pdf_rgb(soft, "RG") + b"234 624 m 502 624 l S\n")
    _pdf_wrapped_text(stream, lines, main_x, 594, body_size, body_leading, text_color, width=main_w)

    _pdf_text(stream, f"Page {page_number}", 470, 34, 8, (0.50, 0.50, 0.50))
    return bytes(stream)


def _write_letter_pdf(path: Path, job: dict, letter_text: str):
    """Assemble manuellement un PDF simple sans dépendance externe."""
    clean_text = _normalize_application_text(letter_text)
    # Une lettre de motivation doit rester sur une page. On ajuste le corps
    # avant de tronquer en dernier recours.
    layout_options = [
        {"width": 62, "size": 10, "leading": 15, "max_lines": 36},
        {"width": 68, "size": 9, "leading": 13, "max_lines": 41},
        {"width": 74, "size": 8, "leading": 11, "max_lines": 49},
    ]
    selected = layout_options[-1]
    lines = _wrap_pdf_text(clean_text, width=selected["width"])
    for option in layout_options:
        candidate = _wrap_pdf_text(clean_text, width=option["width"])
        if len(candidate) <= option["max_lines"]:
            selected = option
            lines = candidate
            break
    if len(lines) > selected["max_lines"]:
        lines = lines[: selected["max_lines"] - 1] + ["..."]
    pages = [lines]

    objects: list[bytes] = []
    page_ids = []
    font_id = 3 + len(pages) * 2

    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(b"")

    for index, page_lines in enumerate(pages, start=1):
        # Chaque page PDF référence un objet "page" et un objet "contenu".
        page_obj_id = len(objects) + 1
        content_obj_id = page_obj_id + 1
        page_ids.append(page_obj_id)
        content = _build_pdf_page(page_lines, job, index, selected["size"], selected["leading"])
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {content_obj_id} 0 R >>".encode("ascii")
        )
        objects.append(b"<< /Length " + str(len(content)).encode("ascii") + b" >>\nstream\n" + content + b"endstream")

    kids = b" ".join(f"{page_id} 0 R".encode("ascii") for page_id in page_ids)
    objects[1] = b"<< /Type /Pages /Kids [" + kids + b"] /Count " + str(len(page_ids)).encode("ascii") + b" >>"
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")

    pdf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for obj_id, obj in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{obj_id} 0 obj\n".encode("ascii"))
        pdf.extend(obj)
        pdf.extend(b"\nendobj\n")

    xref_offset = len(pdf)
    # La table xref indique au lecteur PDF où commence chaque objet.
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    pdf.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    path.write_bytes(pdf)


@app.post("/api/jobs/{job_id}/apply")
async def apply_job(job_id: int, body: dict = {}):
    """Prépare une candidature complète et l'envoie si une adresse email existe."""
    send_email_flag = body.get("send_email", True)
    cv_text = _extract_cv_text()

    jobs = _get_jobs_extended()
    job = next((j for j in jobs if j["id"] == job_id), None)
    if not job:
        raise HTTPException(404, "Offre introuvable")

    strategy = _infer_application_strategy(job, cv_text)
    _save_apply_info(job_id, strategy)

    # On génère toujours lettre + email pour avoir une candidature complète.
    result = _build_application_text(job, cv_text, "both")
    paths = _save_application_files(job, result)

    action = {
        "method": strategy.get("apply_mode", "website"),
        "apply_url": strategy.get("apply_url", job.get("url", "")),
        "recruiter_email": strategy.get("recruiter_email", ""),
        "instructions": strategy.get("instructions", ""),
    }

    sent = False
    recipient = strategy.get("recruiter_email", "")
    if send_email_flag and strategy.get("apply_mode") == "email" and recipient:
        # Envoi automatique uniquement si l'IA a identifié un destinataire clair.
        subject = strategy.get("subject") or f"Candidature pour {job['title']} - {job['company']}"
        body_text = strategy.get("body") or result.get("email", "")
        email_body = body_text + "\n\n" + result.get("letter", "")
        attachments = [str(CV_PATH)] if CV_PATH.exists() else []
        sent = send_email(subject, email_body, recipient, attachments=attachments)
        action["sent"] = sent
        action["recipient"] = recipient
    else:
        action["sent"] = False
        action["recipient"] = recipient

    if strategy.get("apply_mode") == "website" and action["apply_url"]:
        action["instructions"] = action["instructions"] or "Ouvre ce lien et postule sur le site de l'annonceur."

    _set_job_status(job_id, "applied")
    return {
        "status": "applied",
        "action": action,
        "result": result,
        "paths": paths,
    }


@app.post("/api/email/config-test")
async def test_email_config():
    """Test l'envoi d'un email de test."""
    try:
        cfg = EMAIL_CONFIG
        subject = "Test Job Scraper - Configuration email"
        body = f"""Test de configuration email réussi!

Configuration actuelle:
- Expéditeur: {cfg['sender_email']}
- Destinataire: {cfg['recipient_email']}
- Serveur: {cfg['smtp_host']}:{cfg['smtp_port']}

Si vous recevez cet email, la configuration SMTP fonctionne correctement.

Généré automatiquement le {datetime.now().strftime('%d/%m/%Y à %H:%M')}"""

        sent = send_email(subject, body, cfg["recipient_email"])
        return {"sent": sent, "recipient": cfg["recipient_email"]}
    except Exception as e:
        logger.error(f"Email test failed: {e}")
        return {"sent": False, "error": str(e)}

# ── Scraping ────────────────────────────────────────────────
@app.post("/api/scrape")
async def scrape_jobs(background_tasks: BackgroundTasks, body: dict = {}):
    """Lance le scraping demandé sans bloquer le navigateur."""
    sources = body.get("sources", DEFAULT_SOURCES)
    locations = body.get("locations", DEFAULT_LOCATIONS)

    def _run():
        # Import local pour éviter de charger tous les scrapers au démarrage.
        from main import run_scraper
        run_scraper(sources, locations)

    background_tasks.add_task(_run)
    return {"status": "started", "sources": sources, "locations": locations}


@app.get("/api/automation/status")
async def automation_status():
    """Expose l'état courant de l'automatisation au dashboard."""
    return auto_sprint_state


@app.post("/api/automation/run-now")
async def automation_run_now():
    """Force un sprint automatique immédiatement depuis l'interface."""
    return await _run_auto_sprint_once("manual")


@app.post("/api/jobs/cleanup")
async def cleanup_jobs():
    """Vérifie les offres actives et ferme celles qui ne sont plus disponibles."""
    closed = await asyncio.to_thread(_cleanup_unavailable_jobs, 300)
    return {"closed": closed}


# ── Email alert ─────────────────────────────────────────────
@app.post("/api/email/test")
async def test_email():
    """Envoie un email de résumé forcé pour vérifier la configuration."""
    try:
        sent = send_summary_email(since_hours=24, force=True)
        return {"sent": sent, "recipient": EMAIL_CONFIG["recipient_email"], "email_status": get_email_status()}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/email/summary")
async def email_summary():
    """Envoie manuellement le résumé email des offres."""
    sent = send_summary_email(since_hours=24, force=True)
    return {"sent": sent, "recipient": EMAIL_CONFIG["recipient_email"], "email_status": get_email_status()}


@app.get("/api/email/status")
async def email_status():
    """Retourne l'état SMTP et la dernière erreur connue."""
    return get_email_status()
