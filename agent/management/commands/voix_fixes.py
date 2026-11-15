"""Génère data/voix/<clip>.wav : phrases fixes de l’assistant, jouées sans quota ni réseau."""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from agent.gemini import CLIPS
from agent.voix import telecharger_piper, voix_wav


class Command(BaseCommand):
    help = "Télécharge la voix Piper si besoin et enregistre les phrases fixes dans data/voix/."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="Réenregistre même si le fichier existe.")

    def handle(self, *args, **options):
        if settings.VOIX_MOTEUR != "gemini":
            try:
                telecharger_piper()
            except Exception as err:
                self.stderr.write(f"Voix Piper non téléchargée : {err}")
        dossier = Path(settings.BASE_DIR) / "data" / "voix"
        dossier.mkdir(parents=True, exist_ok=True)
        for phrase, nom in CLIPS.items():
            cible = dossier / f"{nom}.wav"
            if cible.exists() and not options["force"]:
                self.stdout.write(f"{nom}.wav déjà là")
                continue
            wav = voix_wav(phrase)
            if not wav:
                self.stderr.write(f"{nom}.wav : synthèse impossible")
                continue
            cible.write_bytes(wav)
            self.stdout.write(self.style.SUCCESS(f"{nom}.wav ({len(wav) // 1024} Ko)"))
