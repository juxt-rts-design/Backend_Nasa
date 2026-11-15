from datetime import date, timedelta

from django.contrib.auth import authenticate, get_user_model, login, logout
from django.db.models import Q
from django.middleware.csrf import get_token
from django.utils.dateparse import parse_date
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from calendrier.models import Calendrier, SerieMensuelle

from .models import Notification, UtilisateurProfil, ZoneInteret
from .serializers import (
    ConnexionSerializer,
    InscriptionSerializer,
    NotificationSerializer,
    ProfilSerializer,
    ZoneInteretSerializer,
)

User = get_user_model()
MONDE_IDS = {"Monde", "WORLD", "monde", "world"}


def _profil_payload(user):
    prof, _created = UtilisateurProfil.objects.get_or_create(user=user)
    return ProfilSerializer(prof).data


@ensure_csrf_cookie
@api_view(["GET"])
@permission_classes([AllowAny])
def csrf_token(request):
    """Envoie le cookie CSRF et le jeton lisible par le SPA."""
    return Response({"csrfToken": get_token(request), "message": "Cookie CSRF défini"})


@ensure_csrf_cookie
@api_view(["POST"])
@permission_classes([AllowAny])
def inscription(request):
    serializer = InscriptionSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    user = serializer.save()
    login(request, user)
    return Response(
        {
            "message": "Inscription réussie",
            "username": user.username,
            "profil": _profil_payload(user),
        },
        status=status.HTTP_201_CREATED,
    )


def _authenticate(username, password):
    user = authenticate(username=username, password=password)
    if user is not None:
        return user
    if "@" in username:
        found = User.objects.filter(email__iexact=username).first()
        if found:
            return authenticate(username=found.username, password=password)
    found = User.objects.filter(username__iexact=username).first()
    if found and found.username != username:
        return authenticate(username=found.username, password=password)
    return None


@ensure_csrf_cookie
@api_view(["POST"])
@permission_classes([AllowAny])
def connexion(request):
    serializer = ConnexionSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    user = _authenticate(
        serializer.validated_data["username"].strip(),
        serializer.validated_data["password"],
    )
    if user is None:
        return Response({"error": "Nom ou mot de passe incorrect."}, status=status.HTTP_401_UNAUTHORIZED)
    if not user.is_active:
        return Response({"error": "Ce compte est désactivé."}, status=status.HTTP_401_UNAUTHORIZED)
    login(request, user)
    return Response({
        "message": "Connexion réussie",
        "username": user.username,
        "profil": _profil_payload(user),
    })


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def deconnexion(request):
    logout(request)
    return Response({"message": "Déconnexion réussie"})


@api_view(["GET", "PUT"])
@permission_classes([IsAuthenticated])
def profil(request):
    prof, _created = UtilisateurProfil.objects.get_or_create(user=request.user)
    if request.method == "GET":
        return Response(ProfilSerializer(prof).data)
    serializer = ProfilSerializer(prof, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    serializer.save()
    return Response(serializer.data)


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def zones(request):
    if request.method == "GET":
        qs = ZoneInteret.objects.filter(utilisateur=request.user)
        return Response(ZoneInteretSerializer(qs, many=True).data)
    serializer = ZoneInteretSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    serializer.save(utilisateur=request.user)
    return Response(serializer.data, status=status.HTTP_201_CREATED)


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def zone_delete(request, pk):
    try:
        zone = ZoneInteret.objects.get(pk=pk, utilisateur=request.user)
    except ZoneInteret.DoesNotExist:
        return Response({"error": "Zone non trouvée"}, status=status.HTTP_404_NOT_FOUND)
    zone.delete()
    return Response({"message": "Zone supprimée"})


def _float(data, key):
    try:
        value = data.get(key)
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _months_between(debut, fin):
    if not debut and not fin:
        today = date.today()
        return [f"{today.year:04d}-{today.month:02d}"]
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
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        if len(months) > 24:
            break
    return months


def _bbox_filter(qs, data, lat_field, lon_field):
    lat_min = _float(data, "lat_min")
    lat_max = _float(data, "lat_max")
    lon_min = _float(data, "lon_min")
    lon_max = _float(data, "lon_max")
    if lat_min is not None:
        qs = qs.filter(**{f"{lat_field}__gte": lat_min})
    if lat_max is not None:
        qs = qs.filter(**{f"{lat_field}__lte": lat_max})
    if lon_min is not None:
        qs = qs.filter(**{f"{lon_field}__gte": lon_min})
    if lon_max is not None:
        qs = qs.filter(**{f"{lon_field}__lte": lon_max})
    return qs


def _month_end(mois):
    y, m = int(mois[:4]), int(mois[5:7])
    if m == 12:
        return date(y, 12, 31)
    return date(y, m + 1, 1) - timedelta(days=1)


def _serialize_notifs(qs):
    return NotificationSerializer(qs, many=True).data


def _visible(user):
    return Notification.objects.filter(utilisateur=user, supprimee=False)


def _unread_count(user, region_id=None):
    qs = _visible(user).filter(lue=False)
    if region_id:
        qs = qs.filter(region_id=region_id)
    return qs.count()


def _region_notifs(user, region_id, limit=1000):
    unread = list(
        _visible(user).filter(region_id=region_id, lue=False).order_by("-created_at", "-id")[:limit]
    )
    rest = limit - len(unread)
    if rest <= 0:
        return unread
    read = list(
        _visible(user).filter(region_id=region_id, lue=True).order_by("-created_at", "-id")[:rest]
    )
    return unread + read


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def notifications_liste(request):
    region_id = (request.query_params.get("region_id") or "").strip()
    items = _region_notifs(request.user, region_id) if region_id else list(
        _visible(request.user).order_by("lue", "-created_at", "-id")[:1000]
    )
    return Response({
        "items": _serialize_notifs(items),
        "non_lues": _unread_count(request.user, region_id or None),
        "active": True,
    })


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def notifications_sync(request):
    """Crée les alertes de la région courante pour l’utilisateur connecté, sans le globe monde."""
    data = request.data or {}
    region_id = str(data.get("region_id") or "").strip()
    kind = str(data.get("kind") or "").strip().lower()
    if not region_id or region_id in MONDE_IDS or kind == "world":
        return Response({"items": [], "nouvelles": [], "non_lues": 0, "active": False})

    region_nom = str(data.get("region_nom") or region_id).strip()
    debut = parse_date(str(data.get("date_min") or ""))
    fin = parse_date(str(data.get("date_max") or ""))
    months = _months_between(debut, fin)
    last = months[-1]
    date_alerte = fin or _month_end(last)

    seen = {}
    anomalies = _bbox_filter(
        Calendrier.objects.filter(mois__in=months).select_related("cellule"),
        data,
        "cellule__lat_centre",
        "cellule__lon_centre",
    ).filter(Q(est_anomalie=True) | Q(zscore__gte=2)).order_by("-zscore")[:10000]
    for row in anomalies:
        seen[(row.cellule_id, row.mois)] = row

    extra = _bbox_filter(
        SerieMensuelle.objects.filter(mois__in=months, nb_detections__gte=1).select_related("cellule"),
        data,
        "cellule__lat_centre",
        "cellule__lon_centre",
    ).order_by("-nb_detections")[:10000]
    for serie in extra:
        key = (serie.cellule_id, serie.mois)
        if key not in seen:
            seen[key] = serie

    rows = list(seen.values())
    cell_ids = [getattr(row, "cellule_id", None) for row in rows]
    series_map = {
        (s.cellule_id, s.mois): s
        for s in SerieMensuelle.objects.filter(cellule_id__in=cell_ids, mois__in=months)
    }
    cal_map = {
        (c.cellule_id, c.mois): c
        for c in Calendrier.objects.filter(cellule_id__in=cell_ids, mois__in=months)
    }

    wanted = []
    cles = []
    for row in rows:
        cellule = getattr(row, "cellule", None)
        if cellule is None:
            continue
        mois = getattr(row, "mois", last)
        cal = cal_map.get((cellule.id, mois))
        serie = series_map.get((cellule.id, mois))
        z = float(getattr(cal or row, "zscore", 0) or 0)
        est_anomalie = bool(getattr(cal or row, "est_anomalie", False) or z >= 2)
        nb = float(serie.nb_detections or 0) if serie else 0
        lat = float(cellule.lat_centre)
        lon = float(cellule.lon_centre)
        niveau = Notification.NIVEAU_ALERTE if est_anomalie else Notification.NIVEAU_RISQUE
        titre = "Zone à haut risque" if est_anomalie else "Activité intense"
        precision = f"z-score {z:.1f}"
        if nb:
            precision = f"{precision} · {nb:.0f} éq. Aqua"
        lieu = f"{lat:.2f}°, {lon:.2f}°"
        cle = f"{request.user.id}:{region_id}:{mois}:{cellule.id}"
        alerte = _month_end(mois) if not fin else min(date_alerte, _month_end(mois))
        cles.append(cle)
        wanted.append(Notification(
            utilisateur=request.user,
            cle=cle,
            region_id=region_id,
            region_nom=region_nom,
            lieu=lieu,
            titre=titre,
            message=f"{region_nom} · {lieu} · {mois} · {precision}.",
            niveau=niveau,
            date_alerte=alerte,
            precision=precision,
            lat=lat,
            lon=lon,
            lue=False,
        ))

    existing = set(
        Notification.objects.filter(utilisateur=request.user, cle__in=cles).values_list("cle", flat=True)
    )
    to_create = [n for n in wanted if n.cle not in existing]
    if to_create:
        Notification.objects.bulk_create(to_create, ignore_conflicts=True, batch_size=500)
    nouvelles = []
    if to_create:
        new_cles = [n.cle for n in to_create]
        nouvelles = list(
            Notification.objects.filter(utilisateur=request.user, cle__in=new_cles).order_by("-created_at", "-id")
        )

    return Response({
        "items": _serialize_notifs(_region_notifs(request.user, region_id)),
        "nouvelles": _serialize_notifs(nouvelles),
        "non_lues": _unread_count(request.user, region_id),
        "active": True,
    })


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def notification_lire(request, pk):
    try:
        notif = _visible(request.user).get(pk=pk)
    except Notification.DoesNotExist:
        return Response({"error": "Notification introuvable."}, status=status.HTTP_404_NOT_FOUND)
    if not notif.lue:
        notif.lue = True
        notif.save(update_fields=["lue"])
    return Response({
        "item": NotificationSerializer(notif).data,
        "non_lues": _unread_count(request.user, notif.region_id),
    })


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def notifications_lire_tout(request):
    _visible(request.user).filter(lue=False).update(lue=True)
    return Response({"ok": True, "non_lues": 0})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def notifications_vider(request):
    Notification.objects.filter(utilisateur=request.user, supprimee=False).update(supprimee=True, lue=True)
    return Response({"ok": True, "non_lues": 0})
