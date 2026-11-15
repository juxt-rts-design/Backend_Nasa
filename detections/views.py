from datetime import datetime, timedelta, timezone as dt_timezone

from django.db import connection
from django.utils.dateparse import parse_date
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from firewatch.utils import parse_int_param, paginer
from .models import DetectionBrute, Cellule, CelluleJourSatellite
from .serializers import (
    DetectionBruteSerializer,
    GlobePointSerializer,
    CelluleSerializer,
    CelluleJourSatelliteSerializer,
)


# ── Filtre partagé ───────────────────────────────────────────────

def appliquer_bbox(queryset, request, lat_field="latitude", lon_field="longitude"):
    """Filtre un queryset par rectangle lat/lon (params GET)."""
    lat_min = request.query_params.get("lat_min")
    lat_max = request.query_params.get("lat_max")
    lon_min = request.query_params.get("lon_min")
    lon_max = request.query_params.get("lon_max")
    try:
        if lat_min:
            queryset = queryset.filter(**{f"{lat_field}__gte": float(lat_min)})
        if lat_max:
            queryset = queryset.filter(**{f"{lat_field}__lte": float(lat_max)})
        if lon_min:
            queryset = queryset.filter(**{f"{lon_field}__gte": float(lon_min)})
        if lon_max:
            queryset = queryset.filter(**{f"{lon_field}__lte": float(lon_max)})
    except (TypeError, ValueError):
        pass
    return queryset


def filtrer_detections(request):
    """Filtre les détections par satellite, plage de dates et bbox."""
    queryset = DetectionBrute.objects.all()

    satellite = request.query_params.get("satellite") or request.query_params.get("satellites")
    if satellite:
        names = [s.strip() for s in satellite.split(",") if s.strip()]
        if len(names) == 1:
            queryset = queryset.filter(satellite=names[0])
        elif names:
            queryset = queryset.filter(satellite__in=names)

    date_min = request.query_params.get("date_min")
    if date_min:
        debut = _jour_utc(date_min)
        if debut:
            queryset = queryset.filter(date_acquisition__gte=debut)

    date_max = request.query_params.get("date_max")
    if date_max:
        fin = _jour_utc(date_max)
        if fin:
            queryset = queryset.filter(date_acquisition__lt=fin + timedelta(days=1))

    return appliquer_bbox(queryset, request)


def _jour_utc(value):
    """Parse YYYY-MM-DD en datetime UTC (évite DATE()/CONVERT_TZ qui casse l'index MySQL)."""
    jour = parse_date(value) if isinstance(value, str) else value
    if not jour:
        return None
    return datetime(jour.year, jour.month, jour.day, tzinfo=dt_timezone.utc)


# ── Vues ─────────────────────────────────────────────────────────

def _unique_flag(request):
    return str(request.query_params.get("unique") or "1").lower() not in ("0", "false", "no", "off")


def _split_names(value):
    return [p.strip() for p in str(value or "").split(",") if p.strip()]


def _as_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _where_clause(queryset):
    compiler = queryset.query.get_compiler(using=queryset.db)
    sql, params = queryset.query.where.as_sql(compiler, compiler.connection)
    if not sql:
        return "1=1", []
    return sql, list(params)


def _fetch_dicts(sql, params):
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        columns = [col[0] for col in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _fill_days(by_day, request):
    debut = parse_date(request.query_params.get("date_min") or "")
    fin = parse_date(request.query_params.get("date_max") or "")
    if not debut or not fin or fin < debut:
        return sorted(by_day.values(), key=lambda d: d["date"])
    if (fin - debut).days > 366:
        fin = debut + timedelta(days=366)
    days = []
    cur = debut
    while cur <= fin:
        key = cur.isoformat()
        days.append(by_day.get(key) or {"date": key, "total": 0, "frp_max": 0, "parSat": {}})
        cur += timedelta(days=1)
    return days


def _cluster_globe(queryset, limit):
    """Un point par lieu (~1 km) et par jour, même si plusieurs satellites l’ont vu."""
    where, params = _where_clause(queryset)
    rows = _fetch_dicts(
        f"""
        SELECT
            MIN(id) AS sample_id,
            AVG(latitude) AS latitude,
            AVG(longitude) AS longitude,
            MAX(frp) AS frp,
            MAX(brightness) AS brightness,
            MAX(date_acquisition) AS date_acquisition,
            COUNT(*) AS nb,
            GROUP_CONCAT(DISTINCT satellite) AS satellites,
            GROUP_CONCAT(DISTINCT instrument) AS instruments,
            MAX(confidence) AS confidence
        FROM detection_brute
        WHERE {where}
        GROUP BY DATE(date_acquisition), ROUND(latitude, 2), ROUND(longitude, 2)
        ORDER BY frp DESC
        LIMIT %s
        """,
        params + [int(limit)],
    )
    points = []
    for row in rows:
        sats = _split_names(row.get("satellites"))
        inst = _split_names(row.get("instruments"))
        acquired = row.get("date_acquisition")
        lat = _as_float(row.get("latitude"))
        lon = _as_float(row.get("longitude"))
        frp = _as_float(row.get("frp"))
        points.append({
            "id": row["sample_id"],
            "lat": lat,
            "lon": lon,
            "weight": frp,
            "frp": frp,
            "nb": int(row.get("nb") or 1),
            "satellite": sats[0] if len(sats) == 1 else "plusieurs",
            "satellites": sats,
            "instrument": inst[0] if len(inst) == 1 else "mixte",
            "confidence": row.get("confidence"),
            "brightness": row.get("brightness"),
            "date_acquisition": acquired.isoformat() if acquired else None,
        })
    return points


@api_view(["GET"])
def globe(request):
    """Points légers pour le globe 3D (lat, lon, frp). unique=1 fusionne les capteurs d’un même lieu."""
    queryset = filtrer_detections(request)
    limit = parse_int_param(request, "limit", 5000, max_value=10000)
    if _unique_flag(request):
        return Response(_cluster_globe(queryset, limit))
    points = queryset.only(
        "id", "latitude", "longitude", "frp", "satellite", "date_acquisition",
        "confidence", "brightness", "instrument",
    ).order_by("-frp", "-date_acquisition")[:limit]
    serializer = GlobePointSerializer(points, many=True)
    return Response(serializer.data)


def _empty_day(key):
    return {"date": key, "total": 0, "frp_max": 0, "parSat": {}}


def _day_key(value):
    if hasattr(value, "isoformat"):
        return value.isoformat()
    text = str(value or "")
    return text[:10] if text else ""


@api_view(["GET"])
def globe_jours(request):
    """Comptes journaliers sans charger 10 000 points. unique=1 = un hotspot par lieu/jour."""
    queryset = filtrer_detections(request)
    unique = _unique_flag(request)
    where, params = _where_clause(queryset)
    by_day = {}

    if unique:
        rows = _fetch_dicts(
            f"""
            SELECT DATE(date_acquisition) AS jour,
                   ROUND(latitude, 2) AS gy,
                   ROUND(longitude, 2) AS gx,
                   satellite,
                   MAX(frp) AS frp_max
            FROM detection_brute
            WHERE {where}
            GROUP BY 1, 2, 3, 4
            """,
            params,
        )
        seen = set()
        for row in rows:
            key = _day_key(row.get("jour"))
            if not key:
                continue
            cur = by_day.setdefault(key, _empty_day(key))
            cell = (key, row.get("gy"), row.get("gx"))
            if cell not in seen:
                seen.add(cell)
                cur["total"] += 1
            cur["frp_max"] = max(cur["frp_max"], _as_float(row.get("frp_max")))
            sat = row.get("satellite") or "inconnu"
            cur["parSat"][sat] = cur["parSat"].get(sat, 0) + 1
        days = _fill_days(by_day, request)
        return Response({"days": days, "total": sum(d["total"] for d in days), "unique": True})

    rows = _fetch_dicts(
        f"""
        SELECT DATE(date_acquisition) AS jour,
               satellite,
               COUNT(*) AS n,
               MAX(frp) AS frp_max
        FROM detection_brute
        WHERE {where}
        GROUP BY 1, 2
        ORDER BY 1
        """,
        params,
    )
    for row in rows:
        key = _day_key(row.get("jour"))
        if not key:
            continue
        cur = by_day.setdefault(key, _empty_day(key))
        n = int(row.get("n") or 0)
        cur["total"] += n
        cur["frp_max"] = max(cur["frp_max"], _as_float(row.get("frp_max")))
        sat = row.get("satellite") or "inconnu"
        cur["parSat"][sat] = cur["parSat"].get(sat, 0) + n
    days = _fill_days(by_day, request)
    return Response({"days": days, "total": sum(d["total"] for d in days), "unique": False})


@api_view(["GET"])
def detections_liste(request):
    """Liste paginée des détections brutes avec filtres."""
    queryset = filtrer_detections(request).order_by("-date_acquisition")
    return paginer(queryset, request, DetectionBruteSerializer)


@api_view(["GET"])
def detections_detail(request, pk):
    """Détail d'une détection brute."""
    try:
        detection = DetectionBrute.objects.get(pk=pk)
    except DetectionBrute.DoesNotExist:
        return Response(
            {"erreur": "Détection introuvable."},
            status=status.HTTP_404_NOT_FOUND,
        )
    serializer = DetectionBruteSerializer(detection)
    return Response(serializer.data)


@api_view(["GET"])
def cellules_liste(request):
    """Liste paginée des cellules de la grille 0.25°."""
    queryset = appliquer_bbox(
        Cellule.objects.all(), request, lat_field="lat_centre", lon_field="lon_centre",
    )
    return paginer(queryset, request, CelluleSerializer)


@api_view(["GET"])
def cellule_jours(request, pk):
    """Agrégats journaliers par satellite pour une cellule (paginé)."""
    try:
        cellule = Cellule.objects.get(pk=pk)
    except Cellule.DoesNotExist:
        return Response(
            {"erreur": "Cellule introuvable."},
            status=status.HTTP_404_NOT_FOUND,
        )

    queryset = CelluleJourSatellite.objects.filter(cellule=cellule)

    satellite = request.query_params.get("satellite")
    if satellite:
        queryset = queryset.filter(satellite=satellite)

    queryset = queryset.order_by("-date")
    return paginer(queryset, request, CelluleJourSatelliteSerializer)


# ── Export CSV ───────────────────────────────────────────────────

class Echo:
    """Pseudo-buffer pour StreamingHttpResponse."""
    def write(self, value):
        return value


@api_view(["GET"])
def export_csv(request):
    """Exporte les détections filtrées au format CSV (streaming)."""
    import csv
    from django.http import StreamingHttpResponse

    queryset = filtrer_detections(request).order_by("date_acquisition")

    pseudo_buffer = Echo()
    writer = csv.writer(pseudo_buffer)

    def generate():
        yield writer.writerow([
            "id", "latitude", "longitude", "brightness", "frp",
            "confidence", "satellite", "instrument",
            "date_acquisition", "source_fichier",
        ])
        for det in queryset.iterator(chunk_size=2000):
            yield writer.writerow([
                det.id, det.latitude, det.longitude,
                det.brightness, det.frp, det.confidence,
                det.satellite, det.instrument,
                det.date_acquisition.isoformat(),
                det.source_fichier,
            ])

    response = StreamingHttpResponse(generate(), content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="firewatch_export.csv"'
    return response