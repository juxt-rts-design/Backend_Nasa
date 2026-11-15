from django.contrib import admin
from .models import SerieMensuelle, Calendrier


@admin.register(SerieMensuelle)
class SerieMensuelleAdmin(admin.ModelAdmin):
    list_display = ("cellule", "mois", "nb_detections", "frp_total", "brightness_moy")
    list_filter = ("mois",)


@admin.register(Calendrier)
class CalendrierAdmin(admin.ModelAdmin):
    list_display = ("cellule", "mois", "zscore", "est_anomalie")
    list_filter = ("est_anomalie",)