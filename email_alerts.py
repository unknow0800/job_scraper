# ============================================================
#  email_alerts.py — Alertes email pour les nouvelles offres
# ============================================================
# Envoie un récap HTML des nouvelles offres par email.
# Utilise smtplib (aucune dépendance externe requise).
# Compatible Gmail, Outlook, et tout serveur SMTP.
# ============================================================

import smtplib
import sqlite3
import os
from html import escape
from pathlib import Path
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta
from db import get_connection


# ============================================================
#  CONFIGURATION EMAIL — À remplir
# ============================================================
EMAIL_CONFIG = {
    # Expéditeur (ton adresse Gmail ou autre)
    "smtp_host": os.getenv("SMTP_HOST", "smtp.gmail.com"),
    "smtp_port": int(os.getenv("SMTP_PORT", "587")),
    "sender_email": os.getenv("SMTP_SENDER_EMAIL", "bubb0318@gmail.com"),
    "sender_password": os.getenv("SMTP_SENDER_PASSWORD", "fghh wnqe jqqn kyqt"),

    # Destinataire (toi-même en général)
    "recipient_email": os.getenv("SMTP_RECIPIENT_EMAIL", "mr.dev.rene@gmail.com"),
}

EMAIL_LAST_ERROR = ""


def _set_email_error(message: str) -> None:
    """Garde en mémoire la dernière erreur pour l'afficher dans le dashboard."""
    global EMAIL_LAST_ERROR
    EMAIL_LAST_ERROR = message


def get_email_status() -> dict:
    """Retourne un diagnostic lisible de la configuration SMTP."""
    password = EMAIL_CONFIG.get("sender_password", "")
    # Gmail App Password contient 16 caractères hors espaces.
    looks_like_app_password = len(password.replace(" ", "")) == 16
    return {
        "smtp_host": EMAIL_CONFIG.get("smtp_host"),
        "smtp_port": EMAIL_CONFIG.get("smtp_port"),
        "sender_email": EMAIL_CONFIG.get("sender_email"),
        "recipient_email": EMAIL_CONFIG.get("recipient_email"),
        "password_configured": bool(password),
        "looks_like_app_password": looks_like_app_password,
        "last_error": EMAIL_LAST_ERROR,
    }


# ============================================================
#  Récupération des nouvelles offres
# ============================================================
def get_new_jobs(since_hours: int = 24) -> list[dict]:
    """Retourne les offres trouvées dans les dernières N heures."""
    cutoff = (datetime.now() - timedelta(hours=since_hours)).isoformat(timespec="seconds")
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM jobs WHERE found_at >= ? ORDER BY found_at DESC",
            (cutoff,)
        ).fetchall()
    return [dict(row) for row in rows]


# ============================================================
#  Construction de l'email HTML
# ============================================================
def _build_html(jobs: list[dict], since_hours: int) -> str:
    """Construit la version HTML de l'email d'alerte simple."""
    source_colors = {
        "indeed":   "#003A9B",
        "linkedin": "#0A66C2",
        "wttj":     "#4A154B",
        "apec":     "#E30613",
    }

    # Grouper par source pour créer une section par site d'emploi.
    by_source: dict[str, list] = {}
    for job in jobs:
        by_source.setdefault(job["source"], []).append(job)

    sections_html = ""
    for source, source_jobs in by_source.items():
        color = source_colors.get(source, "#555")
        cards = ""
        for job in source_jobs:
            # On tronque la description pour garder un email court et lisible.
            desc = job.get("description", "")
            desc_preview = (desc[:200] + "...") if len(desc) > 200 else desc or "—"
            url = job.get("url", "#")
            cards += f"""
            <div style="border:1px solid #e0e0e0; border-radius:8px; padding:16px; margin-bottom:12px; background:#fff;">
                <h3 style="margin:0 0 4px; font-size:16px; color:#1a1a1a;">{job['title']}</h3>
                <p style="margin:0 0 8px; color:#555; font-size:14px;">
                    🏢 <strong>{job['company']}</strong> &nbsp;·&nbsp; 📍 {job['location']} &nbsp;·&nbsp; 📄 {job['contract']}
                </p>
                <p style="margin:0 0 12px; color:#666; font-size:13px; line-height:1.5;">{desc_preview}</p>
                <a href="{url}" style="display:inline-block; padding:8px 16px; background:{color}; color:#fff; text-decoration:none; border-radius:6px; font-size:13px; font-weight:600;">
                    Voir l'offre →
                </a>
            </div>"""

        sections_html += f"""
        <div style="margin-bottom:32px;">
            <h2 style="color:{color}; border-bottom:2px solid {color}; padding-bottom:6px; font-size:18px;">
                {source.upper()} — {len(source_jobs)} offre{'s' if len(source_jobs) > 1 else ''}
            </h2>
            {cards}
        </div>"""

    total = len(jobs)
    now_str = datetime.now().strftime("%d/%m/%Y à %H:%M")

    return f"""
<!DOCTYPE html>
<html lang="fr">
<head><meta charset="UTF-8"></head>
<body style="margin:0; padding:0; background:#f5f5f5; font-family:Arial,sans-serif;">
<div style="max-width:640px; margin:24px auto; background:#f5f5f5;">

  <!-- Header -->
  <div style="background:linear-gradient(135deg,#1a1a2e,#16213e); border-radius:12px 12px 0 0; padding:28px 32px;">
    <h1 style="margin:0; color:#fff; font-size:22px;">🔍 {total} nouvelle{'s' if total > 1 else ''} offre{'s' if total > 1 else ''}</h1>
    <p style="margin:6px 0 0; color:#aaa; font-size:14px;">Dernières {since_hours}h · Récap du {now_str}</p>
  </div>

  <!-- Body -->
  <div style="background:#f5f5f5; padding:24px 32px;">
    {sections_html}
  </div>

  <!-- Footer -->
  <div style="background:#e0e0e0; border-radius:0 0 12px 12px; padding:16px 32px; text-align:center;">
    <p style="margin:0; color:#888; font-size:12px;">
      Généré automatiquement par ton Job Scraper 🤖 · 
      <a href="#" style="color:#888;">Se désabonner</a>
    </p>
  </div>

</div>
</body>
</html>"""


def _build_plain_text(jobs: list[dict]) -> str:
    """Construit une version texte pour les clients email sans HTML."""
    lines = [f"{'='*50}", f"{len(jobs)} NOUVELLES OFFRES TROUVÉES", f"{'='*50}\n"]
    for job in jobs:
        lines.append(f"[{job['source'].upper()}] {job['title']}")
        lines.append(f"  Entreprise : {job['company']}")
        lines.append(f"  Lieu       : {job['location']}")
        lines.append(f"  Contrat    : {job['contract']}")
        lines.append(f"  URL        : {job.get('url', '—')}")
        lines.append("")
    return "\n".join(lines)


def get_search_summary(since_hours: int = 1, min_score: int = 65) -> dict:
    """Retourne un resume actionnable pour le mail automatique."""
    cutoff = (datetime.now() - timedelta(hours=since_hours)).isoformat(timespec="seconds")
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        # Trois requêtes séparées rendent le résumé plus clair:
        # nouvelles offres, offres prioritaires, puis compteurs globaux.
        new_jobs = conn.execute(
            """
            SELECT * FROM jobs
            WHERE found_at >= ?
              AND COALESCE(status, 'new') NOT IN ('applied', 'closed')
            ORDER BY found_at DESC
            """,
            (cutoff,),
        ).fetchall()
        priority_jobs = conn.execute(
            """
            SELECT * FROM jobs
            WHERE COALESCE(status, 'new') NOT IN ('applied', 'closed')
              AND COALESCE(match_score, 0) >= ?
            ORDER BY match_score DESC, found_at DESC
            LIMIT 10
            """,
            (min_score,),
        ).fetchall()
        applied_count = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE COALESCE(status, 'new') = 'applied'"
        ).fetchone()[0]
        closed_count = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE COALESCE(status, 'new') = 'closed'"
        ).fetchone()[0]
        active_count = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE COALESCE(status, 'new') NOT IN ('applied', 'closed')"
        ).fetchone()[0]
        by_source = conn.execute(
            """
            SELECT source, COUNT(*) AS count
            FROM jobs
            GROUP BY source
            ORDER BY count DESC
            """
        ).fetchall()

    return {
        "since_hours": since_hours,
        "new_jobs": [dict(row) for row in new_jobs],
        "priority_jobs": [dict(row) for row in priority_jobs],
        "applied_count": applied_count,
        "closed_count": closed_count,
        "active_count": active_count,
        "by_source": {row["source"]: row["count"] for row in by_source},
    }


def _job_cards(jobs: list[dict], empty_text: str) -> str:
    """Transforme une liste d'offres en cartes HTML pour le digest."""
    if not jobs:
        return f"<p style='color:#666;margin:8px 0 18px'>{escape(empty_text)}</p>"

    cards = ""
    for job in jobs:
        url = escape(job.get("url") or "#")
        score = int(job.get("match_score") or 0)
        reason = escape((job.get("match_reason") or "")[:240])
        cards += f"""
        <div style="border:1px solid #e7e7e7;border-radius:10px;padding:14px;margin:10px 0;background:#fff">
          <h3 style="margin:0 0 6px;font-size:16px;color:#1f2933">{escape(job.get('title') or 'Titre indisponible')}</h3>
          <p style="margin:0 0 8px;color:#52606d;font-size:13px">
            <strong>{escape(job.get('company') or 'Entreprise inconnue')}</strong> · {escape(job.get('location') or 'Lieu inconnu')} · {escape(job.get('source') or 'source')}
          </p>
          <p style="margin:0 0 10px;color:#3e4c59;font-size:13px">Score: <strong>{score}%</strong>{' · ' + reason if reason else ''}</p>
          <a href="{url}" style="display:inline-block;background:#2d5a5e;color:#fff;text-decoration:none;border-radius:6px;padding:8px 12px;font-size:13px;font-weight:700">Voir l'offre</a>
        </div>"""
    return cards


def _build_summary_html(summary: dict) -> str:
    """Construit le digest HTML complet envoyé automatiquement."""
    now_str = datetime.now().strftime("%d/%m/%Y à %H:%M")
    by_source = "".join(
        f"<li><strong>{escape(source or 'inconnu')}</strong>: {count}</li>"
        for source, count in summary["by_source"].items()
    )
    return f"""
<!DOCTYPE html>
<html lang="fr">
<body style="margin:0;background:#f4f6f8;font-family:Arial,sans-serif;color:#1f2933">
  <div style="max-width:680px;margin:24px auto;background:#f4f6f8">
    <div style="background:#2d5a5e;border-radius:12px 12px 0 0;padding:24px 28px;color:#fff">
      <h1 style="margin:0;font-size:22px">Résumé recherche d'offres</h1>
      <p style="margin:6px 0 0;color:#d9e8ea;font-size:14px">{now_str} · dernières {summary['since_hours']}h</p>
    </div>
    <div style="background:#fff;padding:22px 28px;border-radius:0 0 12px 12px">
      <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:22px">
        <div style="background:#eef5f6;border-radius:8px;padding:12px"><strong>{len(summary['new_jobs'])}</strong><br><span style="font-size:12px;color:#52606d">nouvelles offres</span></div>
        <div style="background:#fff7e8;border-radius:8px;padding:12px"><strong>{len(summary['priority_jobs'])}</strong><br><span style="font-size:12px;color:#52606d">à postuler vite</span></div>
        <div style="background:#f1f5f9;border-radius:8px;padding:12px"><strong>{summary['active_count']}</strong><br><span style="font-size:12px;color:#52606d">offres actives</span></div>
      </div>

      <h2 style="font-size:18px;margin:18px 0 8px">Offres à traiter en priorité</h2>
      {_job_cards(summary['priority_jobs'], "Aucune offre prioritaire pour le moment.")}

      <h2 style="font-size:18px;margin:22px 0 8px">Nouvelles offres détectées</h2>
      {_job_cards(summary['new_jobs'][:10], "Aucune nouvelle offre sur cette période.")}

      <h2 style="font-size:18px;margin:22px 0 8px">Répartition par source</h2>
      <ul style="margin-top:6px;color:#52606d">{by_source or "<li>Aucune donnée source</li>"}</ul>

      <p style="margin-top:22px;color:#52606d;font-size:13px">
        Historique: {summary['applied_count']} postulées · {summary['closed_count']} fermées/expirées.
      </p>
    </div>
  </div>
</body>
</html>"""


def _build_summary_text(summary: dict) -> str:
    """Construit l'équivalent texte du digest automatique."""
    lines = [
        "RESUME RECHERCHE D'OFFRES",
        f"Dernieres {summary['since_hours']}h",
        "",
        f"Nouvelles offres: {len(summary['new_jobs'])}",
        f"Offres prioritaires: {len(summary['priority_jobs'])}",
        f"Offres actives: {summary['active_count']}",
        f"Postulees: {summary['applied_count']} | Fermees: {summary['closed_count']}",
        "",
        "A traiter en priorite:",
    ]
    for job in summary["priority_jobs"][:10]:
        lines.append(f"- {job.get('title')} chez {job.get('company')} ({job.get('match_score') or 0}%)")
        lines.append(f"  {job.get('url') or ''}")
    return "\n".join(lines)


def send_summary_email(since_hours: int = 1, force: bool = False) -> bool:
    """Envoie un digest: nouvelles offres, priorites et resume global."""
    _set_email_error("")
    summary = get_search_summary(since_hours=since_hours)
    # Sans nouveauté ni priorité, on n'envoie rien sauf si force=True.
    should_send = bool(summary["new_jobs"] or summary["priority_jobs"] or force)
    if not should_send:
        print("[Email] Aucun digest a envoyer.")
        return False

    _set_email_error("")
    cfg = EMAIL_CONFIG
    subject = (
        f"Job Scraper - {len(summary['new_jobs'])} nouvelle(s), "
        f"{len(summary['priority_jobs'])} prioritaire(s)"
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = cfg["sender_email"]
    msg["To"] = cfg["recipient_email"]
    msg.attach(MIMEText(_build_summary_text(summary), "plain", "utf-8"))
    msg.attach(MIMEText(_build_summary_html(summary), "html", "utf-8"))

    try:
        with smtplib.SMTP(cfg["smtp_host"], cfg["smtp_port"]) as server:
            server.ehlo()
            server.starttls()
            server.login(cfg["sender_email"], cfg["sender_password"])
            server.sendmail(cfg["sender_email"], cfg["recipient_email"], msg.as_string())
        print(f"[Email] Digest envoye a {cfg['recipient_email']}")
        return True
    except smtplib.SMTPAuthenticationError as e:
        message = "Authentification SMTP refusee. Avec Gmail, utilise un App Password de 16 caracteres, pas le mot de passe normal du compte."
        _set_email_error(message)
        print(f"[Email] Erreur digest: {message} ({e})")
        return False
    except Exception as e:
        _set_email_error(str(e))
        print(f"[Email] Erreur digest: {e}")
        return False


# ============================================================
#  Envoi de l'email
# ============================================================
def send_alert(since_hours: int = 24, force: bool = False) -> bool:
    """
    Vérifie les nouvelles offres et envoie un email si nécessaire.
    
    Args:
        since_hours : fenêtre de temps pour les "nouvelles" offres
        force       : envoyer même s'il n'y a aucune nouvelle offre
    
    Returns:
        True si email envoyé, False sinon.
    """
    _set_email_error("")
    new_jobs = get_new_jobs(since_hours)

    if not new_jobs and not force:
        print(f"[Email] Aucune nouvelle offre dans les {since_hours}h. Pas d'email envoyé.")
        return False

    if not new_jobs and force:
        print("[Email] Aucune offre à signaler (envoi forcé).")

    cfg = EMAIL_CONFIG
    total = len(new_jobs)

    # Construction du message multi-part: texte simple + HTML.
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"🔍 {total} nouvelle{'s' if total > 1 else ''} offre{'s' if total > 1 else ''} stage/alternance"
    msg["From"] = cfg["sender_email"]
    msg["To"] = cfg["recipient_email"]

    plain = _build_plain_text(new_jobs)
    html = _build_html(new_jobs, since_hours)

    msg.attach(MIMEText(plain, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    # Envoi SMTP via le serveur configuré dans EMAIL_CONFIG.
    try:
        with smtplib.SMTP(cfg["smtp_host"], cfg["smtp_port"]) as server:
            # TLS chiffre la connexion avant l'authentification SMTP.
            server.ehlo()
            server.starttls()
            server.login(cfg["sender_email"], cfg["sender_password"])
            server.sendmail(cfg["sender_email"], cfg["recipient_email"], msg.as_string())

        print(f"[Email] ✅ Email envoyé à {cfg['recipient_email']} ({total} offres)")
        return True

    except smtplib.SMTPAuthenticationError:
        _set_email_error("Authentification SMTP refusee. Verifie ton App Password Gmail.")
        print("[Email] ❌ Erreur d'authentification. Vérifie ton App Password Gmail.")
        print("  → https://myaccount.google.com/apppasswords")
        return False
    except Exception as e:
        _set_email_error(str(e))
        print(f"[Email] ❌ Erreur d'envoi : {e}")
        return False


def send_email(subject: str, body: str, recipient_email: str, attachments: list[str] | None = None) -> bool:
    """Envoie un email simple avec texte et pièces jointes facultatives."""
    cfg = EMAIL_CONFIG
    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"] = cfg["sender_email"]
    msg["To"] = recipient_email
    msg.attach(MIMEText(body or "", "plain", "utf-8"))

    for attachment in attachments or []:
        # Chaque pièce jointe est lue en binaire puis ajoutée au message MIME.
        path = Path(attachment)
        if not path.exists():
            continue
        with path.open("rb") as f:
            part = MIMEApplication(f.read(), Name=path.name)
        part["Content-Disposition"] = f"attachment; filename=\"{path.name}\""
        msg.attach(part)

    try:
        with smtplib.SMTP(cfg["smtp_host"], cfg["smtp_port"]) as server:
            server.ehlo()
            server.starttls()
            server.login(cfg["sender_email"], cfg["sender_password"])
            server.sendmail(cfg["sender_email"], recipient_email, msg.as_string())

        print(f"[Email] ✅ Email d'application envoyé à {recipient_email}")
        return True
    except Exception as e:
        print(f"[Email] ❌ Erreur d'envoi application : {e}")
        return False


# ============================================================
#  CLI
# ============================================================
if __name__ == "__main__":
    import sys
    hours = int(sys.argv[1]) if len(sys.argv) > 1 else 24
    force = "--force" in sys.argv
    send_alert(since_hours=hours, force=force)
