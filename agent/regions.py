"""Catalogue pays / régions pour l’assistant (ISO3, alias FR, bbox, cadrage globe)."""

from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

from django.conf import settings

MACROS = {
    "Afrique_Centrale": {
        "id": "Afrique_Centrale",
        "nom": "Afrique centrale",
        "kind": "macro",
        "lat_min": -6, "lat_max": 8.2, "lon_min": 8, "lon_max": 28.5,
        "focus": {"lat": 1.1, "lng": 17.6, "altitude": 1.42},
    },
    "Monde": {
        "id": "Monde",
        "nom": "monde entier",
        "kind": "world",
        "lat_min": -56, "lat_max": 78, "lon_min": -170, "lon_max": 180,
        "focus": {"lat": 8, "lng": 18, "altitude": 2.4},
    },
}

LEGACY = {
    "afrique centrale": "Afrique_Centrale",
    "afrique_centrale": "Afrique_Centrale",
    "gabon": "GAB",
    "cameroun": "CMR",
    "congo": "COG",
    "congo brazzaville": "COG",
    "republique du congo": "COG",
    "rdc": "COD",
    "drc": "COD",
    "zaire": "COD",
    "congo kinshasa": "COD",
    "republique democratique du congo": "COD",
    "republique democratique du congo rdc": "COD",
    "rca": "CAF",
    "centrafrique": "CAF",
    "republique centrafricaine": "CAF",
    "guinee equatoriale": "GNQ",
    "monde": "Monde",
    "monde entier": "Monde",
    "globe": "Monde",
    "planete": "Monde",
}


def fold(text: str) -> str:
    raw = unicodedata.normalize("NFD", str(text or "").lower())
    stripped = "".join(ch for ch in raw if unicodedata.category(ch) != "Mn")
    return " ".join(stripped.replace("'", " ").replace("-", " ").split())


def _focus_from_bbox(lat_min, lat_max, lon_min, lon_max):
    lat = (lat_min + lat_max) / 2
    lng = (lon_min + lon_max) / 2
    if lon_max - lon_min > 300:
        lng = 20
    span = max(lat_max - lat_min, abs(lon_max - lon_min) * 0.85)
    altitude = min(2.45, max(0.32, span / 26))
    return {"lat": round(lat, 3), "lng": round(lng, 3), "altitude": round(altitude, 3)}


@lru_cache(maxsize=1)
def _atlas():
    path = Path(settings.BASE_DIR) / "data" / "geo" / "countries-110m.geojson"
    by_id = {}
    if not path.exists():
        return by_id
    data = json.loads(path.read_text(encoding="utf-8"))
    for feat in data.get("features") or []:
        props = feat.get("properties") or {}
        iso = str(feat.get("id") or props.get("id") or "").upper()
        if not iso:
            continue
        lat_min = float(props.get("latMin") or 0)
        lat_max = float(props.get("latMax") or 0)
        lon_min = float(props.get("lonMin") or 0)
        lon_max = float(props.get("lonMax") or 0)
        by_id[iso] = {
            "id": iso,
            "nom": props.get("nom") or props.get("nomEn") or iso,
            "nom_en": props.get("nomEn") or props.get("nom") or iso,
            "kind": "country",
            "lat_min": lat_min, "lat_max": lat_max,
            "lon_min": lon_min, "lon_max": lon_max,
            "focus": _focus_from_bbox(lat_min, lat_max, lon_min, lon_max),
        }
    return by_id


def resolve_lieu(lieu: str | None, fallback: str | None = None) -> dict | None:
    atlas = _atlas()
    raw = (lieu or "").strip()
    if not raw and fallback:
        raw = fallback
    if not raw:
        return MACROS["Afrique_Centrale"]
    key = fold(raw)
    if key in LEGACY:
        mapped = LEGACY[key]
        if mapped in MACROS:
            return MACROS[mapped]
        if mapped in atlas:
            return atlas[mapped]
    upper = raw.upper()
    if upper in atlas:
        return atlas[upper]
    if upper in MACROS:
        return MACROS[upper]
    if raw in MACROS:
        return MACROS[raw]
    hits = []
    for country in atlas.values():
        names = [fold(country["nom"]), fold(country["nom_en"]), fold(country["id"])]
        if key in names or any(key == n or n.startswith(key) or key.startswith(n) for n in names if n):
            hits.append(country)
    if len(hits) == 1:
        return hits[0]
    if hits:
        hits.sort(key=lambda c: len(c["nom"]))
        return hits[0]
    if fallback:
        return resolve_lieu(fallback, None)
    return None


def trouver_lieu(texte: str) -> str | None:
    """Premier lieu nommé dans une phrase libre (noms français entiers, alias)."""
    t = f" {fold(texte)} "
    if not t.strip():
        return None
    noms = {alias: alias for alias in LEGACY}
    for country in _atlas().values():
        noms[fold(country["nom"])] = country["id"]
    best = None
    for nom, ref in noms.items():
        if len(nom) < 3 or not re.search(rf"(?<![a-z]){re.escape(nom)}(?![a-z])", t):
            continue
        monde = LEGACY.get(nom) == "Monde"
        rang = (not monde, len(nom))
        if best is None or rang > best[0]:
            best = (rang, ref)
    return best[1] if best else None


def bbox_of(region: dict) -> dict:
    return {
        "lat_min": region["lat_min"],
        "lat_max": region["lat_max"],
        "lon_min": region["lon_min"],
        "lon_max": region["lon_max"],
    }
