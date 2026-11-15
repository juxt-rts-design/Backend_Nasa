from django.contrib import admin
from .models import DetectionBrute, Cellule, CelluleJourSatellite, RatioCorrection


@admin.register(DetectionBrute)
class DetectionBruteAdmin(admin.ModelAdmin):
    list_display = ("satellite", "instrument", "date_acquisition", "latitude", "longitude", "brightness", "confidence")
    list_filter = ("satellite", "instrument")
    search_fields = ("source_fichier",)


@admin.register(Cellule)
class CelluleAdmin(admin.ModelAdmin):
    list_display = ("lat_centre", "lon_centre", "taille_km")


@admin.register(CelluleJourSatellite)
class CelluleJourSatelliteAdmin(admin.ModelAdmin):
    list_display = ("cellule", "date", "satellite", "nb_detections", "frp_total")
    list_filter = ("satellite",)


@admin.register(RatioCorrection)
class RatioCorrectionAdmin(admin.ModelAdmin):
    list_display = ("satellite", "instrument", "mois", "ratio", "nb_observations")
    list_filter = ("satellite",)