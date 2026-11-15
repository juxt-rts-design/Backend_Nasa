"""Voix de l’assistant : Piper (français hors ligne, sans quota) puis Gemini en secours."""

from __future__ import annotations

import base64
import hashlib
import io
import logging
import threading
import urllib.request
import wave
from functools import lru_cache
from pathlib import Path

from django.conf import settings

from .gemini import synth_wav

logger = logging.getLogger(__name__)

CACHE_VOIX = Path(settings.BASE_DIR) / "data" / "voix"
PIPER_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/fr/fr_FR/siwis/medium/"

_verrou = threading.Lock()


def modele_piper() -> Path:
    return Path(settings.PIPER_MODEL)


def telecharger_piper() -> bool:
    cible = modele_piper()
    if cible.exists():
        return True
    cible.parent.mkdir(parents=True, exist_ok=True)
    for nom in (f"{cible.name}.json", cible.name):
        with urllib.request.urlopen(PIPER_URL + nom, timeout=120) as res:
            (cible.parent / nom).write_bytes(res.read())
    _piper.cache_clear()
    return cible.exists()


@lru_cache(maxsize=1)
def _piper():
    chemin = modele_piper()
    if not chemin.exists():
        return None
    try:
        from piper import PiperVoice

        return PiperVoice.load(str(chemin))
    except Exception:
        logger.exception("Voix Piper non chargée")
        return None


def piper_pret() -> bool:
    return settings.VOIX_MOTEUR != "gemini" and _piper() is not None


def prechauffer() -> None:
    if settings.VOIX_MOTEUR != "gemini":
        piper_wav("Bonjour.")


def piper_wav(texte: str) -> bytes | None:
    voix = _piper()
    if not voix or not texte:
        return None
    buf = io.BytesIO()
    try:
        with _verrou, wave.open(buf, "wb") as wf:
            voix.synthesize_wav(texte, wf)
    except Exception:
        logger.exception("Synthèse Piper")
        return None
    return buf.getvalue()


def voix_wav(texte: str) -> bytes | None:
    moteurs = [synth_wav, piper_wav] if settings.VOIX_MOTEUR == "gemini" else [piper_wav, synth_wav]
    for moteur in moteurs:
        wav = moteur(texte)
        if wav:
            return wav
    return None


def synth_voix(texte: str) -> str | None:
    """WAV en base64 ; les phrases courtes sont gardées sur disque."""
    if not texte:
        return None
    court = len(texte) <= 160
    fichier = CACHE_VOIX / f"{settings.VOIX_MOTEUR}-{hashlib.sha1(texte.encode('utf-8')).hexdigest()}.wav"
    if court and fichier.exists():
        return base64.b64encode(fichier.read_bytes()).decode("ascii")
    wav = voix_wav(texte)
    if not wav:
        return None
    if court:
        try:
            CACHE_VOIX.mkdir(parents=True, exist_ok=True)
            fichier.write_bytes(wav)
        except OSError:
            logger.warning("Cache voix non écrit : %s", fichier)
    return base64.b64encode(wav).decode("ascii")
