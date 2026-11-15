"""
Télécharge les données FIRMS depuis l'API NASA.

Usage :
    python manage.py telecharger_firms
    python manage.py telecharger_firms --source MODIS_NRT VIIRS_NOAA20_NRT --zone GAB --jours 10
    python manage.py telecharger_firms --format csv
"""

import os

import pandas as pd
from django.conf import settings
from django.core.management.base import BaseCommand


FIRMS_API_URL = "https://firms.modaps.eosdis.nasa.gov/api/area"

SOURCES_DISPONIBLES = [
    "MODIS_NRT",
    "MODIS_SP",
    "VIIRS_NOAA20_NRT",
    "VIIRS_SNPP_NRT",
    "VIIRS_NOAA21_NRT",
]


class Command(BaseCommand):
    help = "Télécharge les données FIRMS depuis l'API NASA"

    def add_arguments(self, parser):
        parser.add_argument(
            "--cle", type=str, default=None,
            help="Clé API FIRMS (sinon lit FIRMS_MAP_KEY depuis .env)",
        )
        parser.add_argument(
            "--source", type=str, nargs="+",
            default=["MODIS_NRT", "VIIRS_NOAA20_NRT"],
            choices=SOURCES_DISPONIBLES,
            help="Sources (défaut : MODIS_NRT VIIRS_NOAA20_NRT)",
        )
        parser.add_argument(
            "--zone", type=str, default="GAB",
            help="Code pays (GAB) ou bbox west,south,east,north (défaut : GAB)",
        )
        parser.add_argument(
            "--jours", type=int, default=10,
            help="Nombre de jours, 1 à 10 (défaut : 10)",
        )
        parser.add_argument(
            "--format", type=str, default="json",
            choices=["json", "csv"],
            help="Format de téléchargement (défaut : json)",
        )
        parser.add_argument(
            "--sortie", type=str, default="data/firms",
            help="Dossier de sortie (défaut : data/firms)",
        )

    def handle(self, *args, **options):
        cle = options["cle"] or getattr(settings, "FIRMS_MAP_KEY", "")
        if not cle:
            self.stderr.write(self.style.ERROR(
                "Clé API requise.\n"
                "  → Inscription gratuite : https://firms.modaps.eosdis.nasa.gov/api/area/\n"
                "  → Ajoute FIRMS_MAP_KEY=ta_cle dans .env\n"
                "  → Ou utilise --cle ta_cle"
            ))
            return

        sortie = options["sortie"]
        os.makedirs(sortie, exist_ok=True)

        fmt = options["format"]
        zone = options["zone"]
        jours = min(max(options["jours"], 1), 10)

        for source in options["source"]:
            url = f"{FIRMS_API_URL}/{fmt}/{cle}/{source}/{zone}/{jours}"
            self.stdout.write(f"  {source} ({zone}, {jours} jours)...")

            try:
                if fmt == "json":
                    df = pd.read_json(url)
                else:
                    df = pd.read_csv(url)
            except Exception as e:
                self.stderr.write(self.style.ERROR(f"    Erreur : {e}"))
                continue

            if df.empty:
                self.stdout.write(self.style.WARNING("    → 0 détections"))
                continue

            nom_fichier = f"{source}_{zone}_{jours}j.{fmt}"
            chemin = os.path.join(sortie, nom_fichier)

            if fmt == "json":
                df.to_json(chemin, orient="records", indent=2)
            else:
                df.to_csv(chemin, index=False)

            self.stdout.write(self.style.SUCCESS(
                f"    → {len(df)} détections → {nom_fichier}"
            ))

        self.stdout.write(self.style.SUCCESS(
            f"\nTéléchargement terminé → {sortie}/"
        ))
        self.stdout.write(
            f"Lance maintenant : python manage.py pipeline_firms {sortie}"
        )