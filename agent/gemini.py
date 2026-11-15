"""Client Gemini : comprendre la consigne (audio ou texte) et la dire à voix haute."""

from __future__ import annotations

import base64
import io
import json
import logging
import re
import ssl
import time
import urllib.error
import urllib.request
import wave
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import date

from django.conf import settings

from .regions import fold, trouver_lieu

logger = logging.getLogger(__name__)

TECH = "Je ne suis pas en mesure de répondre pour le moment, à cause d’un problème technique."
SALUT = "Bonjour, que puis-je faire pour toi ?"
INAUDIBLE = "Je n’ai pas bien entendu. Peux-tu répéter ?"
INCONNU = "Je ne trouve pas ce lieu. Peux-tu redire le nom du pays ?"
MICRO = "Autorise le micro, puis clique encore sur moi."

# Phrases fixes : servies depuis public/voix/<clip>.wav, sans quota.
CLIPS = {SALUT: "salut", TECH: "tech", INAUDIBLE: "inaudible", INCONNU: "inconnu", MICRO: "micro"}

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

CHAT_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-3.5-flash",
    "gemini-flash-latest",
]
TTS_MODELS = [
    "gemini-3.8-flash-tts",
    "gemini-3.8-flash-lite-tts",
    "gemini-3.1-flash-tts-preview",
]

CONSIGNE = (
    "Tu es l’oreille de l’assistant vocal FireWatch (points chauds vus par satellite, NASA FIRMS, "
    "MODIS et VIIRS mis à la même échelle qu’Aqua). Écoute la consigne et remplis le JSON.\n"
    "- transcript : ce que la personne a dit, mot pour mot.\n"
    "- intention : « salut » pour une simple politesse sans autre demande ; "
    "« feux » si elle parle de feux, flammes, points chauds, hausses, baisses, activité d’un lieu, "
    "ou demande de montrer un lieu sur le globe ; « pipeline » si elle demande comment MODIS et VIIRS "
    "sont harmonisés ; « question » pour une autre question sur FireWatch, les satellites ou les feux ; "
    "« inaudible » si on n’entend rien de compréhensible.\n"
    "- lieu : pays ou région prononcé, en français, sinon vide. Ne devine jamais un lieu non dit.\n"
    "- date_min, date_max : AAAA-MM-JJ seulement si une période est dite, sinon vide. Aujourd’hui : {today}.\n"
    "- reponse : seulement pour « question », 1 à 3 phrases très simples pour quelqu’un qui ne connaît "
    "rien au sujet, sans aucun chiffre. Sinon vide."
)

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "transcript": {"type": "STRING"},
        "intention": {"type": "STRING", "enum": ["salut", "feux", "pipeline", "question", "inaudible"]},
        "lieu": {"type": "STRING"},
        "date_min": {"type": "STRING"},
        "date_max": {"type": "STRING"},
        "reponse": {"type": "STRING"},
    },
    "required": ["transcript", "intention", "lieu", "reponse"],
}

SALUTS = {"bonjour", "salut", "hello", "hey", "coucou", "bonsoir", "yo", "hi"}
FEUX = (
    "feu", "flamme", "brul", "incendi", "point chaud", "points chauds", "hausse", "baisse",
    "activite", "montre", "oriente", "tourne", "zoom", "situation",
)
PIPE = ("pipeline", "harmonis", "modis", "viirs", "aqua", "capteur", "correction")
DATE_DITE = re.compile(
    r"\b(19|20)\d{2}\b|\b(janvier|fevrier|mars|avril|mai|juin|juillet|aout|septembre|octobre|"
    r"novembre|decembre|hier|semaine|annee)\b"
)
QUESTION = re.compile(
    r"\b(c est quoi|qu est ce|que veut dire|veut dire quoi|ca veut dire|pourquoi|comment ca marche|"
    r"definition|definis|signifie|difference)\b"
)
ISO_DATE = re.compile(r"^\d{4}-\d{2}(-\d{2})?$")
VIDES = {"", "inconnu", "aucun", "aucune", "none", "null", "n/a", "vide", "non precise", "non specifie", "non mentionne"}


class Indisponible(RuntimeError):
    """Aucun modèle Gemini n’a répondu (quota, clé, réseau)."""


_PAUSE: dict[str, float] = {}


def has_key() -> bool:
    return bool((settings.GEMINI_API_KEY or "").strip())


def est_salut(texte: str) -> bool:
    t = " ".join(re.sub(r"[!?.,;:]+", " ", fold(texte)).split())
    if not t:
        return False
    mots = t.split()
    if mots[0] not in SALUTS or len(mots) > 4:
        return False
    if any(k in t for k in FEUX + PIPE) or trouver_lieu(t):
        return False
    return True


def analyser_local(texte: str) -> dict | None:
    """Comprend les consignes évidentes sans appeler Gemini ; None si doute."""
    t = fold(texte)
    if not t:
        return None
    if est_salut(t):
        return {"intention": "salut", "transcript": texte}
    if DATE_DITE.search(t):
        return None
    lieu = trouver_lieu(t)
    if not lieu and QUESTION.search(t) and not any(k in t for k in PIPE):
        return None
    if not lieu and any(k in t for k in PIPE):
        return {"intention": "pipeline", "transcript": texte}
    if lieu or any(k in t for k in FEUX):
        return {"intention": "feux", "lieu": lieu or "", "transcript": texte}
    return None


def _post(model: str, payload: dict, timeout: float) -> dict:
    req = urllib.request.Request(
        GEMINI_URL.format(model=model),
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": (settings.GEMINI_API_KEY or "").strip(),
        },
    )
    with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as res:
        return json.loads(res.read().decode("utf-8"))


def _pause_pour(code: int, detail: str) -> float:
    if code == 404:
        return 24 * 3600
    if code == 429:
        return 30 * 60 if "perday" in detail.lower().replace(" ", "") else 60
    return 45


def _essai(model: str, payload: dict, timeout: float) -> tuple[str, dict | None]:
    try:
        return "ok", _post(model, payload, timeout)
    except urllib.error.HTTPError as err:
        try:
            detail = err.read().decode("utf-8", "ignore")
        except Exception:
            detail = ""
        logger.warning("Gemini %s HTTP %s %s", model, err.code, " ".join(detail.split())[:240])
        if err.code in (401, 403) or "API_KEY_INVALID" in detail:
            return "cle", None
        if err.code != 400:
            _PAUSE[model] = time.monotonic() + _pause_pour(err.code, detail)
    except Exception as err:
        logger.warning("Gemini %s injoignable : %s", model, err)
        _PAUSE[model] = time.monotonic() + 25
    return "ko", None


def _appeler(models: list[str], payload: dict, budget: float, par_modele: float, relance: float) -> dict:
    """Premier modèle disponible ; s’il traîne plus de `relance` s, le suivant part en parallèle."""
    fin = time.monotonic() + budget
    file = [m for m in dict.fromkeys(models) if m and _PAUSE.get(m, 0) <= time.monotonic()]
    pool = ThreadPoolExecutor(max_workers=3)
    en_cours = {}

    def lancer() -> None:
        reste = fin - time.monotonic()
        if file and reste > 1.5:
            model = file.pop(0)
            en_cours[pool.submit(_essai, model, payload, min(par_modele, reste))] = model

    lancer()
    try:
        while en_cours:
            reste = fin - time.monotonic()
            if reste <= 0:
                break
            finis, _ = wait(en_cours, timeout=min(relance, reste), return_when=FIRST_COMPLETED)
            if not finis:
                lancer()
                continue
            for futur in finis:
                en_cours.pop(futur)
                etat, data = futur.result()
                if etat == "ok":
                    return data
                if etat == "cle":
                    raise Indisponible("clé refusée")
                lancer()
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    raise Indisponible("aucun modèle Gemini disponible")


def _parts_of(data: dict) -> list:
    cands = data.get("candidates") or []
    if not cands:
        return []
    return (cands[0].get("content") or {}).get("parts") or []


def comprendre(texte: str, audio_b64: str | None = None, mime: str = "audio/webm") -> dict:
    """Un seul appel : transcription + intention + lieu (+ réponse simple si question)."""
    if not has_key():
        raise Indisponible("clé absente")
    parts = []
    if audio_b64:
        parts.append({"inlineData": {"mimeType": mime or "audio/webm", "data": audio_b64}})
    parts.append({"text": f"Consigne écrite : {texte}" if texte else "La consigne est dans l’audio."})
    payload = {
        "systemInstruction": {"parts": [{"text": CONSIGNE.format(today=date.today().isoformat())}]},
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 400,
            "responseMimeType": "application/json",
            "responseSchema": SCHEMA,
        },
    }
    data = _appeler([settings.GEMINI_MODEL, *CHAT_MODELS], payload, budget=15, par_modele=10, relance=3.5)
    brut = "".join(p.get("text") or "" for p in _parts_of(data) if not p.get("thought"))
    try:
        sens = json.loads(brut)
    except json.JSONDecodeError:
        trouve = re.search(r"\{.*\}", brut, re.S)
        try:
            sens = json.loads(trouve.group(0)) if trouve else {}
        except json.JSONDecodeError:
            sens = {}
    if not isinstance(sens, dict):
        sens = {}
    for cle in ("date_min", "date_max"):
        if not ISO_DATE.match(str(sens.get(cle) or "")):
            sens[cle] = ""
    lieu = str(sens.get("lieu") or "").strip()
    if fold(lieu).strip(" .") in VIDES:
        lieu = ""
    sens["lieu"] = lieu
    sens["reponse"] = str(sens.get("reponse") or "").strip()[:420]
    sens.setdefault("intention", "inaudible")
    if sens["intention"] == "salut" and not est_salut(sens.get("transcript") or "bonjour"):
        sens["intention"] = "feux" if trouver_lieu(sens.get("transcript") or "") else sens["intention"]
    return sens


def _pcm_to_wav(pcm: bytes, rate: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(pcm)
    return buf.getvalue()


def synth_wav(texte: str, budget: float = 12) -> bytes | None:
    """Voix Gemini (Kore) en WAV ; None si quota, clé ou réseau en défaut."""
    if not texte or not has_key():
        return None
    payload = {
        "contents": [{"parts": [{"text": texte}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": "Kore"}}},
        },
    }
    try:
        data = _appeler([settings.GEMINI_TTS_MODEL, *TTS_MODELS], payload, budget=budget, par_modele=10, relance=6)
    except Indisponible as err:
        logger.warning("Synthèse vocale indisponible : %s", err)
        return None
    for part in _parts_of(data):
        inline = part.get("inlineData") or part.get("inline_data") or {}
        if not inline.get("data"):
            continue
        raw = base64.b64decode(inline["data"])
        mime = (inline.get("mimeType") or inline.get("mime_type") or "").lower()
        if raw[:4] == b"RIFF" or "wav" in mime:
            return raw
        rate = re.search(r"rate=(\d+)", mime)
        return _pcm_to_wav(raw, int(rate.group(1)) if rate else 24000)
    return None
