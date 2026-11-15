"""Outils base de données pour l’assistant vocal (FIRMS, pipeline, calendrier)."""

from __future__ import annotations

from datetime import date

from django.db.models import Avg, Count, Max, Min, Q, Sum

from calendrier.models import Calendrier, SerieMensuelle
from detections.models import RatioCorrection

from .regions import bbox_of, resolve_lieu

TECH = "Je ne suis pas en mesure de répondre pour le moment, à cause d’un problème technique."


def months_between(debut: str | None, fin: str | None) -> list[str]:
    def parse(value):
        if not value:
            return None
        try:
            y, m, *_ = str(value).split("-")
            return int(y), int(m)
        except (TypeError, ValueError):
            return None

    a = parse(debut)
    b = parse(fin)
    if not a and not b:
        today = date.today()
        return [f"{today.year:04d}-{today.month:02d}"]
    if not a:
        a = b
    if not b:
        b = a
    if a > b:
        a, b = b, a
    out = []
    y, m = a
    while (y, m) <= b:
        out.append(f"{y:04d}-{m:02d}")
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1
        if len(out) > 24:
            break
    return out


def _bbox_filter(qs, region, lat_field, lon_field):
    box = bbox_of(region)
    return qs.filter(**{
        f"{lat_field}__gte": box["lat_min"],
        f"{lat_field}__lte": box["lat_max"],
        f"{lon_field}__gte": box["lon_min"],
        f"{lon_field}__lte": box["lon_max"],
    })


def lire_activite(lieu, date_min=None, date_max=None, region_courante=None):
    region = resolve_lieu(lieu, region_courante)
    if not region:
        return {"erreur": f"Je ne trouve pas le lieu « {lieu} »."}
    months = months_between(date_min, date_max)
    last = months[-1]
    series = _bbox_filter(
        SerieMensuelle.objects.filter(mois__in=months, nb_detections__gt=0),
        region, "cellule__lat_centre", "cellule__lon_centre",
    )
    cal = _bbox_filter(
        Calendrier.objects.filter(mois=last),
        region, "cellule__lat_centre", "cellule__lon_centre",
    )
    totaux = series.aggregate(
        eq_aqua=Sum("nb_detections"),
        frp=Sum("frp_total"),
        n=Count("id"),
    )
    z = cal.aggregate(
        z_moy=Avg("zscore"),
        anomalies=Count("id", filter=Q(est_anomalie=True)),
        hausses=Count("id", filter=Q(zscore__gte=2)),
        cellules=Count("id"),
    )
    foyers = list(
        series.values("cellule_id", "cellule__lat_centre", "cellule__lon_centre")
        .annotate(eq=Sum("nb_detections"), frp=Sum("frp_total"))
        .order_by("-eq")[:5]
    )
    foyers_out = []
    for row in foyers:
        foyers_out.append({
            "cellule_id": row["cellule_id"],
            "lat": float(row["cellule__lat_centre"]),
            "lon": float(row["cellule__lon_centre"]),
            "eq_aqua": round(float(row["eq"] or 0), 1),
            "frp_mw": round(float(row["frp"] or 0), 1),
        })
    eq = float(totaux["eq_aqua"] or 0)
    z_moy = float(z["z_moy"] or 0)
    if z_moy >= 1.2:
        tendance = "en nette hausse par rapport à l’habitude"
    elif z_moy >= 0.4:
        tendance = "un peu plus active que d’habitude"
    elif z_moy <= -1.2:
        tendance = "en baisse par rapport à l’habitude"
    elif z_moy <= -0.4:
        tendance = "un peu plus calme que d’habitude"
    else:
        tendance = "dans les clous de l’habitude"
    foyer = foyers_out[0] if foyers_out else None
    couverture = None
    if not eq:
        bornes = SerieMensuelle.objects.aggregate(debut=Min("mois"), fin=Max("mois"))
        if bornes["debut"]:
            couverture = [bornes["debut"], bornes["fin"]]
    return {
        "region_id": region["id"],
        "nom": region["nom"],
        "kind": region.get("kind"),
        "bbox": bbox_of(region),
        "couverture": couverture,
        "hausses": int(z["hausses"] or 0),
        "periode": months,
        "equivalent_aqua": round(eq, 1),
        "frp_total_mw": round(float(totaux["frp"] or 0), 1),
        "cellules_actives": int(totaux["n"] or 0),
        "zscore_moyen": round(z_moy, 2),
        "anomalies": int(z["anomalies"] or 0),
        "tendance": tendance,
        "foyer": foyer,
        "foyers": foyers_out,
        "focus": region["focus"],
        "aide": (
            "equivalent_aqua = points chauds déjà ramenés à l’échelle d’Aqua. "
            "Un point chaud est une chaleur vue du satellite, pas forcément un incendie de forêt. "
            "zscore : écart à la médiane des années précédentes pour le même mois."
        ),
    }


def lire_pipeline(mois=None):
    qs = RatioCorrection.objects.all()
    if mois:
        qs = qs.filter(mois=mois)
    else:
        dernier = qs.order_by("-mois").values_list("mois", flat=True).first()
        if dernier:
            qs = qs.filter(mois=dernier)
            mois = dernier
    rows = list(qs.order_by("satellite").values("satellite", "instrument", "mois", "ratio", "nb_observations"))
    return {
        "mois": mois,
        "ratios": [
            {
                "satellite": r["satellite"],
                "instrument": r["instrument"],
                "ratio_vers_aqua": round(float(r["ratio"] or 0), 3),
                "observations": r["nb_observations"],
            }
            for r in rows
        ],
        "aide": (
            "La pipeline ramène Terra et VIIRS à l’échelle d’Aqua (MODIS), "
            "la référence 2002-2026, pour comparer les années sans se tromper de capteur."
        ),
    }


def orienter(lieu, lat=None, lon=None, region_courante=None):
    region = resolve_lieu(lieu, region_courante)
    if not region:
        return {"erreur": f"Je ne trouve pas le lieu « {lieu} ».", "action": None}
    focus = dict(region["focus"])
    try:
        la = float(lat) if lat is not None and str(lat) != "" else None
        lo = float(lon) if lon is not None and str(lon) != "" else None
    except (TypeError, ValueError):
        la = lo = None
    if la is not None and lo is not None:
        focus = {"lat": la, "lng": lo, "altitude": 0.16}
    return {
        "region_id": region["id"],
        "nom": region["nom"],
        "focus": focus,
        "action": {
            "view": "globe",
            "region_id": region["id"],
            "lat": focus["lat"],
            "lng": focus["lng"],
            "altitude": focus["altitude"],
            "from": "assistant",
        },
    }
