# ============================================================
#  db.py — Gestion de la base de données SQLite
# ============================================================

import sqlite3
import sys
from pathlib import Path
from datetime import datetime, timedelta

# Assure que le dossier du projet est dans le path
sys.path.insert(0, str(Path(__file__).parent))

from config import DB_PATH


def get_connection():
    """Ouvre une connexion vers le fichier SQLite configuré dans config.py."""
    return sqlite3.connect(DB_PATH)


def init_db():
    """Crée la table jobs si elle n'existe pas encore."""
    with get_connection() as conn:
        # IF NOT EXISTS évite de supprimer les données si la table existe déjà.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                title       TEXT NOT NULL,
                company     TEXT,
                location    TEXT,
                contract    TEXT,
                description TEXT,
                url         TEXT UNIQUE,
                source      TEXT,
                found_at    TEXT,
                status      TEXT DEFAULT 'new',
                match_score INTEGER DEFAULT 0,
                match_reason TEXT DEFAULT ''
            )
        """)
        conn.commit()
    print("[DB] Base de données initialisée.")


def insert_job(job: dict) -> bool:
    """Insère une offre et retourne False si son URL existe déjà en base."""
    # found_at permet ensuite de savoir quand l'offre a été détectée.
    job["found_at"] = datetime.now().isoformat(timespec="seconds")
    try:
        with get_connection() as conn:
            # Les :title, :company, etc. sont remplis depuis les clés du dict job.
            conn.execute("""
                INSERT INTO jobs (title, company, location, contract, description, url, source, found_at)
                VALUES (:title, :company, :location, :contract, :description, :url, :source, :found_at)
            """, job)
            conn.commit()
        return True
    except sqlite3.IntegrityError:
        # L'URL est UNIQUE: cette erreur signifie généralement "doublon".
        return False


def get_all_jobs(source: str = None) -> list:
    """Retourne toutes les offres, avec un filtre optionnel par source."""
    with get_connection() as conn:
        # row_factory permet de convertir chaque ligne SQL en dictionnaire lisible.
        conn.row_factory = sqlite3.Row
        if source:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE source = ? ORDER BY found_at DESC", (source,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY found_at DESC"
            ).fetchall()
    return [dict(r) for r in rows]


def get_new_jobs_since(hours: int = 24) -> list:
    """Retourne les offres ajoutées depuis les N dernières heures."""
    # cutoff est la date minimale acceptée dans la requête SQL.
    cutoff = (datetime.now() - timedelta(hours=hours)).isoformat(timespec="seconds")
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM jobs WHERE found_at >= ? ORDER BY found_at DESC",
            (cutoff,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_stats() -> dict:
    """Calcule les chiffres globaux affichés dans le dashboard."""
    with get_connection() as conn:
        # COUNT(*) compte toutes les lignes; GROUP BY regroupe par site source.
        total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        by_source = conn.execute(
            "SELECT source, COUNT(*) FROM jobs GROUP BY source"
        ).fetchall()
    return {"total": total, "sources": len(by_source), "by_source": dict(by_source)}
