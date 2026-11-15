from datetime import date

from django.db.models import Avg, Count, Max, OuterRef, Q, Subquery, Sum
from django.utils.dateparse import parse_date
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from firewatch.utils import parse_float_param, parse_int_param, paginer
from detections.models import Cellule
from detections.views import appliquer_bbox
from .models import SerieMensuelle, Calendrier
from .serializers import SerieMensuelleSerializer, CalendrierSerializer


def _months_in_range(request):
    mois = request.query_params.get("mois")
    if mois:
        return [mois]
    debut = parse_date(request.query_params.get("date_min") or "")
    fin = parse_date(request.query_params.get("date_max") or "")
    if not debut and not fin:
        return []
    if not debut:
        debut = fin
    if not fin:
        fin = debut
    if fin < debut:
        debut, fin = fin, debut
    months = []
    y, m = debut.year, debut.month
    while (y, m) <= (fin.year, fin.month):
        months.append(f"{y:04d}-{m:02d}")
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1
        if len(months) > 24:
            break
    return months


@api_view(["GET"])
def globe_harmonise(request):
    """Cases 0.25° déjà harmonisées (équivalent Aqua), pour le globe et la carte."""
    months = _months_in_range(request)
    if not months:
        today = date.today()
        months = [f"{today.year:04d}-{today.month:02d}"]
    limit = parse_int_param(request, "limit", 5000, max_value=10000)
    last = months[-1]
    z_sub = Calendrier.objects.filter(cellule_id=OuterRef("cellule_id"), mois=last)
    queryset = appliquer_bbox(
        SerieMensuelle.objects.filter(mois__in=months, nb_detections__gt=0),
        request,
        lat_field="cellule__lat_centre",
        lon_field="cellule__lon_centre",
    )
    queryset = queryset.values("cellule_id").annotate(
        lat=Max("cellule__lat_centre"),
        lon=Max("cellule__lon_centre"),
        nb_detections=Sum("nb_detections"),
        frp_total=Sum("frp_total"),
        zscore=Subquery(z_sub.values("zscore")[:1]),
        est_anomalie=Subquery(z_sub.values("est_anomalie")[:1]),
    )
    rows = list(queryset.order_by("-nb_detections")[:limit])
    total = sum(float(r.get("nb_detections") or 0) for r in rows)
    points = []
    for row in rows:
        nb = float(row.get("nb_detections") or 0)
        frp = float(row.get("frp_total") or 0)
        z = float(row.get("zscore") or 0)
        points.append({
            "id": row["cellule_id"],
            "cellule_id": row["cellule_id"],
            "lat": float(row["lat"]),
            "lon": float(row["lon"]),
            "nb_detections": round(nb, 2),
            "frp_total": round(frp, 2),
            "frp_max": round(frp, 2),
            "zscore": round(z, 3),
            "est_anomalie": bool(row.get("est_anomalie")),
            "mois": last,
        })
    return Response({
        "points": points,
        "total": round(total, 1),
        "nb_cellules": len(points),
        "mois": months,
        "unique": True,
        "mode": "harmonise",
    })


def filtrer_calendrier(request):
    queryset = Calendrier.objects.select_related("cellule")
    mois = request.query_params.get("mois")
    if mois:
        queryset = queryset.filter(mois=mois)
    anomalies_only = request.query_params.get("anomalies_only")
    if anomalies_only in ("true", "1"):
        queryset = queryset.filter(est_anomalie=True)
    return appliquer_bbox(queryset, request, lat_field="cellule__lat_centre", lon_field="cellule__lon_centre")


@api_view(["GET"])
def calendrier_liste(request):
    """Liste paginée du calendrier avec filtre par mois, bbox et anomalies."""
    queryset = filtrer_calendrier(request).order_by("-mois")
    return paginer(queryset, request, CalendrierSerializer)


@api_view(["GET"])
def calendrier_resume(request):
    """Agrégat mensuel du calendrier (une ligne par mois) pour la heatmap régionale."""
    queryset = filtrer_calendrier(request)
    rows = (
        queryset.values("mois")
        .annotate(
            zscore_moyen=Avg("zscore"),
            nb_cellules=Count("id"),
            nb_anomalies=Count("id", filter=Q(est_anomalie=True)),
        )
        .order_by("mois")
    )
    series = appliquer_bbox(
        SerieMensuelle.objects.all(),
        request,
        lat_field="cellule__lat_centre",
        lon_field="cellule__lon_centre",
    )
    sums = {
        item["mois"]: item["total"]
        for item in series.values("mois").annotate(total=Sum("nb_detections"))
    }
    return Response([
        {
            "mois": row["mois"],
            "zscore_moyen": row["zscore_moyen"],
            "nb_cellules": row["nb_cellules"],
            "nb_anomalies": row["nb_anomalies"],
            "nb_detections": sums.get(row["mois"]) or 0,
        }
        for row in rows
    ])


@api_view(["GET"])
def anomalies(request):
    """Anomalies détectées (z-score > seuil), paginées."""
    seuil = parse_float_param(request, "seuil", 2.0)
    queryset = appliquer_bbox(
        Calendrier.objects.filter(est_anomalie=True, zscore__gte=seuil).select_related("cellule"),
        request,
        lat_field="cellule__lat_centre",
        lon_field="cellule__lon_centre",
    ).order_by("-zscore")
    return paginer(queryset, request, CalendrierSerializer)


@api_view(["GET"])
def cellule_serie(request, pk):
    """Série temporelle mensuelle pour une cellule (graphe)."""
    try:
        cellule = Cellule.objects.get(pk=pk)
    except Cellule.DoesNotExist:
        return Response(
            {"erreur": "Cellule introuvable."},
            status=status.HTTP_404_NOT_FOUND,
        )

    series = (
        SerieMensuelle.objects
        .filter(cellule=cellule)
        .order_by("mois")
    )
    serializer = SerieMensuelleSerializer(series, many=True)
    return Response(serializer.data)