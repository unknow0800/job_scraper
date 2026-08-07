# ============================================================
#  letter_generator.py — Générateur de lettre IA via Claude
# ============================================================
# Génère une lettre de motivation classique ET un email court
# personnalisés pour chaque offre, à partir de ton profil.
# ============================================================

import json
import urllib.request
import urllib.error
from db import get_all_jobs


# ============================================================
#  TON PROFIL — À remplir une fois
# ============================================================
PROFILE = {
    # Profil utilisé par défaut quand on lance letter_generator.py directement.
    # Dans le dashboard principal, app.py utilise plutôt CANDIDATE_PROFILE.
    "prenom": "Prénom",
    "nom": "Nom",
    "formation": "BUT Informatique 2ème année, IUT de Paris",
    "competences": [
        "Python", "JavaScript", "React", "SQL", "Git",
        "Docker", "REST APIs", "méthodes Agile"
    ],
    "experiences": [
        "Projet universitaire : application web de gestion de planning (React + FastAPI)",
        "Développement d'un bot Discord en Python (projet personnel)",
    ],
    "soft_skills": ["curieux", "autonome", "bon esprit d'équipe", "force de proposition"],
    "disponibilite": "à partir de juin 2025 pour 3 mois",   # adapter pour alternance
    "email": "prenom.nom@email.com",
    "telephone": "06 XX XX XX XX",
    "linkedin": "linkedin.com/in/prenom-nom",
    "github": "github.com/prenom-nom",
}


# ============================================================
#  Appel API Claude
# ============================================================
CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL = "claude-sonnet-4-20250514"


def _call_claude(prompt: str) -> str:
    """Appelle l'API Claude et retourne le texte de la réponse."""
    # L'API attend du JSON encodé en UTF-8.
    payload = json.dumps({
        "model": CLAUDE_MODEL,
        "max_tokens": 1000,
        "messages": [{"role": "user", "content": prompt}]
    }).encode("utf-8")

    req = urllib.request.Request(
        # Request prépare la requête HTTP POST sans utiliser de SDK externe.
        CLAUDE_API_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["content"][0]["text"].strip()
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        raise RuntimeError(f"Erreur API Claude ({e.code}) : {body}")


# ============================================================
#  Prompts
# ============================================================
def _prompt_lettre(job: dict, profile: dict) -> str:
    """Construit le prompt pour une lettre de motivation longue."""
    competences = ", ".join(profile["competences"])
    experiences = "\n".join(f"- {e}" for e in profile["experiences"])
    soft = ", ".join(profile["soft_skills"])

    return f"""Tu es un expert en recrutement tech en France. Rédige une lettre de motivation professionnelle et personnalisée en français pour ce candidat.

OFFRE :
- Poste : {job['title']}
- Entreprise : {job['company']}
- Lieu : {job['location']}
- Type : {job['contract']}
- Description : {job.get('description', 'Non disponible')[:800]}

PROFIL DU CANDIDAT :
- Prénom Nom : {profile['prenom']} {profile['nom']}
- Formation : {profile['formation']}
- Compétences techniques : {competences}
- Expériences : 
{experiences}
- Qualités : {soft}
- Disponibilité : {profile['disponibilite']}

CONSIGNES :
- Ton professionnel mais dynamique, adapté à une entreprise tech
- 3 paragraphes : accroche sur l'entreprise → apport du candidat → motivation/disponibilité
- Personnalise vraiment à l'entreprise et au poste (pas de lettre générique)
- Maximum 350 mots
- Terminer par les formules de politesse et les coordonnées
- N'invente pas de détails non fournis sur le candidat

Retourne UNIQUEMENT la lettre, sans commentaire."""


def _prompt_email(job: dict, profile: dict) -> str:
    """Construit le prompt pour un email de candidature court."""
    competences = ", ".join(profile["competences"][:5])  # top 5 seulement

    return f"""Rédige un email de candidature court et percutant en français pour ce candidat.

OFFRE :
- Poste : {job['title']}
- Entreprise : {job['company']}
- Type : {job['contract']}
- Description : {job.get('description', 'Non disponible')[:400]}

PROFIL :
- {profile['prenom']} {profile['nom']}, {profile['formation']}
- Compétences clés : {competences}
- Disponibilité : {profile['disponibilite']}
- Email : {profile['email']} | Tél : {profile['telephone']}
- LinkedIn : {profile['linkedin']} | GitHub : {profile['github']}

CONSIGNES :
- Objet accrocheur inclus (commence par "Objet : ")
- Corps de l'email : 4-5 phrases max
- Direct, professionnel, donne envie d'ouvrir le CV
- Mentionne 1-2 compétences clés pertinentes pour le poste
- Terminer par les coordonnées

Retourne UNIQUEMENT l'email (objet + corps), sans commentaire."""


# ============================================================
#  Fonctions publiques
# ============================================================
def generate_cover_letter(job: dict, profile: dict = None) -> str:
    """Génère une lettre de motivation classique pour une offre."""
    profile = profile or PROFILE
    print(f"  ✍️  Génération de la lettre pour '{job['title']}' chez {job['company']}...")
    return _call_claude(_prompt_lettre(job, profile))


def generate_email(job: dict, profile: dict = None) -> str:
    """Génère un email de candidature court pour une offre."""
    profile = profile or PROFILE
    print(f"  📧 Génération de l'email pour '{job['title']}' chez {job['company']}...")
    return _call_claude(_prompt_email(job, profile))


def generate_both(job: dict, profile: dict = None) -> dict:
    """Génère les deux formats et les retourne dans un dict."""
    # Le dictionnaire permet ensuite de sauvegarder chaque format séparément.
    return {
        "lettre": generate_cover_letter(job, profile),
        "email": generate_email(job, profile),
    }


def save_to_file(job: dict, results: dict, output_dir: str = "candidatures") -> dict:
    """Sauvegarde la lettre et l'email dans des fichiers .txt"""
    import os
    os.makedirs(output_dir, exist_ok=True)

    # Nom de fichier sûr
    safe_company = "".join(c for c in job["company"] if c.isalnum() or c in " -_").strip()
    safe_title = "".join(c for c in job["title"] if c.isalnum() or c in " -_").strip()
    base = f"{output_dir}/{safe_company}_{safe_title}"

    paths = {}

    if "lettre" in results:
        # Un fichier par format rend les candidatures faciles à retrouver.
        path = f"{base}_lettre.txt"
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"LETTRE DE MOTIVATION\n")
            f.write(f"Poste : {job['title']} | Entreprise : {job['company']}\n")
            f.write(f"Source : {job['source']} | URL : {job['url']}\n")
            f.write("=" * 60 + "\n\n")
            f.write(results["lettre"])
        paths["lettre"] = path

    if "email" in results:
        # L'email est sauvegardé séparément pour pouvoir le copier rapidement.
        path = f"{base}_email.txt"
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"EMAIL DE CANDIDATURE\n")
            f.write(f"Poste : {job['title']} | Entreprise : {job['company']}\n")
            f.write("=" * 60 + "\n\n")
            f.write(results["email"])
        paths["email"] = path

    return paths


# ============================================================
#  CLI — Utilisation directe
# ============================================================
if __name__ == "__main__":
    import sys

    print("🤖 Générateur de lettres de candidature\n")

    # Récupère les dernières offres en base
    jobs = get_all_jobs()
    if not jobs:
        print("Aucune offre en base. Lance d'abord : python main.py")
        sys.exit(1)

    # Affiche les 10 dernières offres
    print("Dernières offres disponibles :\n")
    recent = jobs[:10]
    for i, job in enumerate(recent):
        print(f"  [{i+1}] {job['title']} — {job['company']} ({job['source']})")

    print()
    choice = input("Numéro de l'offre à traiter (ou 'all' pour les 5 premières) : ").strip()

    if choice.lower() == "all":
        # Mode rapide: traiter directement les 5 offres les plus récentes.
        selected = recent[:5]
    else:
        try:
            idx = int(choice) - 1
            selected = [recent[idx]]
        except (ValueError, IndexError):
            print("Choix invalide.")
            sys.exit(1)

    for job in selected:
        print(f"\n📋 Traitement : {job['title']} chez {job['company']}")
        results = generate_both(job)
        paths = save_to_file(job, results)

        print(f"  ✅ Lettre sauvegardée : {paths.get('lettre')}")
        print(f"  ✅ Email sauvegardé  : {paths.get('email')}")
        print()

    print("🎉 Terminé ! Tes candidatures sont dans le dossier 'candidatures/'")
