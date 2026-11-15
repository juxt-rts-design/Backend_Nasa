"""Réponses parlées de l’assistant : chiffres lus en base, mots simples, pas de jargon."""

from __future__ import annotations

from .gemini import INAUDIBLE, INCONNU, SALUT
from .outils import lire_activite, lire_pipeline, orienter
from .regions import MACROS, resolve_lieu, trouver_lieu

MOIS = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]


def _mois(code: str) -> str:
    annee, mois = str(code).split("-")[:2]
    return f"{MOIS[int(mois) - 1]} {annee}"


def _periode(mois: list[str]) -> str:
    if not mois:
        return ""
    if len(mois) == 1:
        return _mois(mois[0])
    return f"de {_mois(mois[0])} à {_mois(mois[-1])}"


def _nombre(valeur: float) -> str:
    n = int(round(valeur))
    if n >= 1000:
        n = int(round(n, -1))
    return f"{n:,}".replace(",", " ")


def _direction(foyer: dict, box: dict) -> str:
    lat_c = (box["lat_min"] + box["lat_max"]) / 2
    lon_c = (box["lon_min"] + box["lon_max"]) / 2
    dy = (foyer["lat"] - lat_c) / max((box["lat_max"] - box["lat_min"]) / 2, 0.5)
    dx = (foyer["lon"] - lon_c) / max((box["lon_max"] - box["lon_min"]) / 2, 0.5)
    ns = "nord" if dy > 0.33 else ("sud" if dy < -0.33 else "")
    eo = "est" if dx > 0.33 else ("ouest" if dx < -0.33 else "")
    if ns and eo:
        return f"au {ns}-{eo}"
    if ns:
        return f"au {ns}"
    if eo:
        return f"à l’{eo}"
    return "au centre"


def parler_feux(act: dict) -> str:
    nom = act["nom"]
    zone = "du pays" if act.get("kind") == "country" else "de la zone"
    quand = _periode(act.get("periode") or [])
    eq = float(act.get("equivalent_aqua") or 0)
    if eq <= 0:
        phrase = f"{nom}, {quand} : je n’ai aucun point chaud enregistré sur cette période."
        cov = act.get("couverture")
        if cov:
            phrase += f" Mes données vont de {_mois(cov[0])} à {_mois(cov[1])}."
        return phrase
    z = float(act.get("zscore_moyen") or 0)
    if z >= 1.2:
        tendance = "nettement plus que d’habitude"
    elif z >= 0.4:
        tendance = "un peu plus que d’habitude"
    elif z <= -1.2:
        tendance = "nettement moins que d’habitude"
    elif z <= -0.4:
        tendance = "un peu moins que d’habitude"
    else:
        tendance = "proche de l’habitude"
    phrases = [
        f"{nom}, {quand}.",
        f"Les satellites y voient environ {_nombre(eq)} points chauds, surtout des feux de végétation.",
    ]
    hausses = int(act.get("hausses") or 0)
    if hausses:
        lien = "avec" if z >= 0.4 else "mais"
        zones = "petite zone" if hausses == 1 else "petites zones"
        en = "est" if hausses == 1 else "sont"
        if lien == "avec":
            phrases.append(f"C’est {tendance}, avec {_nombre(hausses)} {zones} en forte hausse.")
        else:
            phrases.append(f"C’est {tendance}, mais {_nombre(hausses)} {zones} {en} en forte hausse.")
    else:
        phrases.append(f"C’est {tendance}.")
    foyer = act.get("foyer")
    if foyer and act.get("bbox"):
        phrases.append(f"Le foyer le plus fort se trouve {_direction(foyer, act['bbox'])} {zone}.")
    return " ".join(phrases)


def parler_pipeline(pipe: dict) -> str:
    ratios = pipe.get("ratios") or []
    viirs = [r["ratio_vers_aqua"] for r in ratios if r["instrument"] == "VIIRS" and r["ratio_vers_aqua"] > 0]
    terra = [r["ratio_vers_aqua"] for r in ratios if r["satellite"] == "Terra" and r["ratio_vers_aqua"] > 0]
    phrases = [
        "Chaque satellite voit les feux à sa façon. Pour comparer les années, "
        "FireWatch ramène tout à l’échelle d’Aqua, le satellite de référence."
    ]
    if viirs:
        fois = max(2, round(1 / (sum(viirs) / len(viirs))))
        phrases.append(
            f"VIIRS, plus précis, voit environ {fois} fois plus de points chauds : on divise donc ses chiffres par {fois}."
        )
    if terra:
        coef = f"{sum(terra) / len(terra):.1f}".replace(".", ",")
        phrases.append(f"Terra passe le matin, quand il y a moins de feux : on multiplie ses chiffres par {coef}.")
    phrases.append("Ainsi, un changement de satellite ne fausse plus la comparaison.")
    return " ".join(phrases)


def _region_demandee(lieu: str, contexte: dict) -> dict | None:
    if lieu:
        return resolve_lieu(lieu, None) or resolve_lieu(trouver_lieu(lieu) or "", None)
    courant = contexte.get("region_id") or contexte.get("region") or ""
    return resolve_lieu(courant, None) or MACROS["Afrique_Centrale"]


def repondre(sens: dict, contexte: dict) -> tuple[str, dict | None]:
    """(phrase à dire, action globe) à partir de l’intention comprise."""
    intention = sens.get("intention")
    if intention == "salut":
        return SALUT, None
    if intention == "question":
        return sens.get("reponse") or INAUDIBLE, None
    if intention == "pipeline":
        return parler_pipeline(lire_pipeline(None)), None
    if intention != "feux":
        return INAUDIBLE, None

    lieu = str(sens.get("lieu") or "").strip()
    region = _region_demandee(lieu, contexte)
    if not region:
        return INCONNU, None
    dit_min, dit_max = sens.get("date_min") or "", sens.get("date_max") or ""
    act = lire_activite(
        region["id"],
        dit_min or contexte.get("date_min"),
        dit_max or contexte.get("date_max"),
    )
    if act.get("erreur"):
        return INCONNU, None
    action = orienter(region["id"]).get("action")
    if action and (dit_min or dit_max) and act.get("equivalent_aqua"):
        action["date_min"] = dit_min or dit_max
        action["date_max"] = dit_max or dit_min
    return parler_feux(act), action
