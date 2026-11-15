from django.urls import path
from . import views

app_name = "utilisateurs"

urlpatterns = [
    path("auth/csrf/", views.csrf_token, name="csrf-token"),
    path("auth/inscription/", views.inscription, name="inscription"),
    path("auth/connexion/", views.connexion, name="connexion"),
    path("auth/deconnexion/", views.deconnexion, name="deconnexion"),
    path("profil/", views.profil, name="profil"),
    path("zones/", views.zones, name="zones"),
    path("zones/<int:pk>/", views.zone_delete, name="zone-delete"),
    path("notifications/", views.notifications_liste, name="notifications"),
    path("notifications/sync/", views.notifications_sync, name="notifications-sync"),
    path("notifications/lire-tout/", views.notifications_lire_tout, name="notifications-lire-tout"),
    path("notifications/vider/", views.notifications_vider, name="notifications-vider"),
    path("notifications/<int:pk>/lire/", views.notification_lire, name="notification-lire"),
]