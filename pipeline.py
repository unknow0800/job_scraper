# ============================================================
#  pipeline.py — Pipeline complet automatisé
# ============================================================
# Lance tout en une commande :
#   1. Scrape toutes les sources
#   2. Envoie une alerte email si nouvelles offres
#   3. (optionnel) Génère des lettres pour les meilleures offres
#
# Usage :
#   python pipeline.py                  → scrape + email
#   python pipeline.py --letters        → scrape + email + lettres (top 3)
#   python pipeline.py --letters --top 5 → lettres pour les 5 premières
# ============================================================

import sys
import argparse
from main import run_scraper
from email_alerts import send_alert
from letter_generator import generate_both, save_to_file
from db import get_new_jobs_since


def parse_args():
    """Lit les options passées en ligne de commande."""
    parser = argparse.ArgumentParser(description="Pipeline automatisé de recherche d'offres")
    parser.add_argument(
        "--sources", nargs="*",
        default=None,
        help="Sources à scraper (défaut : toutes)"
    )
    parser.add_argument(
        "--letters", action="store_true",
        help="Générer des lettres de motivation pour les nouvelles offres"
    )
    parser.add_argument(
        "--top", type=int, default=3,
        help="Nombre de lettres à générer (défaut : 3)"
    )
    parser.add_argument(
        "--hours", type=int, default=24,
        help="Fenêtre de temps pour les alertes (défaut : 24h)"
    )
    return parser.parse_args()


def main():
    """Enchaîne scraping, email, puis génération de lettres si demandée."""
    args = parse_args()

    print("=" * 60)
    print("🚀 PIPELINE JOB SCRAPER")
    print("=" * 60)

    # ── Étape 1 : Scraping ─────────────────────────────────
    print("\n📡 ÉTAPE 1 — Scraping des offres\n")
    run_scraper(args.sources)

    # ── Étape 2 : Alerte email ─────────────────────────────
    print("\n📧 ÉTAPE 2 — Envoi de l'alerte email\n")
    send_alert(since_hours=args.hours)

    # ── Étape 3 : Génération de lettres (optionnel) ────────
    if args.letters:
        print(f"\n✍️  ÉTAPE 3 — Génération de lettres (top {args.top})\n")
        from db import get_all_jobs
        new_jobs = get_all_jobs()[:args.top]

        if not new_jobs:
            print("  Aucune offre disponible.")
        else:
            for job in new_jobs:
                try:
                    # generate_both appelle l'IA deux fois: lettre + email.
                    results = generate_both(job)
                    # save_to_file écrit les textes dans le dossier candidatures/.
                    paths = save_to_file(job, results)
                    print(f"  ✅ {job['company']} — {job['title']}")
                    print(f"     Lettre : {paths.get('lettre')}")
                    print(f"     Email  : {paths.get('email')}")
                except Exception as e:
                    print(f"  ❌ Erreur pour {job['company']} : {e}")

    print("\n" + "=" * 60)
    print("✅ Pipeline terminé !")
    print("=" * 60)


if __name__ == "__main__":
    main()
