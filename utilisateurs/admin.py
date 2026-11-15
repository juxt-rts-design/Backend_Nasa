from django.contrib import admin
from .models import Notification, UtilisateurProfil, ZoneInteret


@admin.register(UtilisateurProfil)
class UtilisateurProfilAdmin(admin.ModelAdmin):
    list_display = ("user", "pays", "date_inscription")
    search_fields = ("user__username",)


@admin.register(ZoneInteret)
class ZoneInteretAdmin(admin.ModelAdmin):
    list_display = ("utilisateur", "nom", "lat_centre", "lon_centre", "rayon_km")
    search_fields = ("nom",)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("utilisateur", "region_nom", "titre", "niveau", "date_alerte", "lue", "created_at")
    list_filter = ("niveau", "lue", "region_id")
    search_fields = ("titre", "lieu", "utilisateur__username")