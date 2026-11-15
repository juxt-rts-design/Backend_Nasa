from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator


class UtilisateurProfil(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profil")
    pays = models.CharField(max_length=100, blank=True, default="")
    date_inscription = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "utilisateur_profil"
        verbose_name = "Profil utilisateur"
        verbose_name_plural = "Profils utilisateurs"

    def __str__(self):
        return f"Profil de {self.user.username}"


class ZoneInteret(models.Model):
    utilisateur = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="zones")
    nom = models.CharField(max_length=200)
    lat_centre = models.FloatField(validators=[MinValueValidator(-90), MaxValueValidator(90)])
    lon_centre = models.FloatField(validators=[MinValueValidator(-180), MaxValueValidator(180)])
    rayon_km = models.FloatField(default=50, validators=[MinValueValidator(0.1)])

    class Meta:
        db_table = "zone_interet"
        verbose_name = "Zone d'intérêt"
        verbose_name_plural = "Zones d'intérêt"

    def __str__(self):
        return f"{self.nom} ({self.lat_centre}, {self.lon_centre})"


class Notification(models.Model):
    NIVEAU_ALERTE = "alerte"
    NIVEAU_RISQUE = "risque"
    NIVEAU_INFO = "info"
    NIVEAUX = (
        (NIVEAU_ALERTE, "Alerte"),
        (NIVEAU_RISQUE, "Risque"),
        (NIVEAU_INFO, "Info"),
    )

    utilisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    region_id = models.CharField(max_length=64)
    region_nom = models.CharField(max_length=200, blank=True, default="")
    lieu = models.CharField(max_length=200, blank=True, default="")
    titre = models.CharField(max_length=200)
    message = models.TextField(blank=True, default="")
    niveau = models.CharField(max_length=16, choices=NIVEAUX, default=NIVEAU_RISQUE)
    date_alerte = models.DateField()
    precision = models.CharField(max_length=200, blank=True, default="")
    lat = models.FloatField(null=True, blank=True)
    lon = models.FloatField(null=True, blank=True)
    lue = models.BooleanField(default=False)
    supprimee = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    cle = models.CharField(max_length=180)

    class Meta:
        db_table = "notification"
        verbose_name = "Notification"
        verbose_name_plural = "Notifications"
        constraints = [
            models.UniqueConstraint(fields=["utilisateur", "cle"], name="uniq_notif_user_cle"),
        ]
        indexes = [
            models.Index(fields=["utilisateur", "region_id", "lue"], name="notif_user_region_lue"),
            models.Index(fields=["utilisateur", "supprimee"], name="notif_user_supprimee"),
            models.Index(fields=["utilisateur", "-created_at"], name="notif_user_created"),
        ]

    def __str__(self):
        return f"{self.utilisateur} · {self.titre}"