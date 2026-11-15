from django.db import models
from detections.models import Cellule, MOIS_VALIDATOR


class SerieMensuelle(models.Model):
    cellule = models.ForeignKey(Cellule, on_delete=models.CASCADE, related_name="series")
    mois = models.CharField(max_length=7, validators=[MOIS_VALIDATOR], help_text="Format YYYY-MM")
    nb_detections = models.FloatField(default=0, verbose_name="nombre de détections")
    frp_total = models.FloatField(default=0)
    brightness_moy = models.FloatField(default=0)

    class Meta:
        db_table = "serie_mensuelle"
        verbose_name = "Série mensuelle"
        verbose_name_plural = "Séries mensuelles"
        constraints = [
            models.UniqueConstraint(
                fields=["cellule", "mois"],
                name="uniq_serie_cellule_mois",
            ),
        ]

    def __str__(self):
        return f"{self.cellule} - {self.mois}"


class Calendrier(models.Model):
    cellule = models.ForeignKey(Cellule, on_delete=models.CASCADE, related_name="calendrier")
    mois = models.CharField(max_length=7, validators=[MOIS_VALIDATOR])
    zscore = models.FloatField(default=0)
    est_anomalie = models.BooleanField(default=False)

    class Meta:
        db_table = "calendrier"
        verbose_name = "Calendrier"
        verbose_name_plural = "Calendriers"
        constraints = [
            models.UniqueConstraint(
                fields=["cellule", "mois"],
                name="uniq_calendrier_cellule_mois",
            ),
        ]

    def __str__(self):
        status = "ANOMALIE" if self.est_anomalie else "normal"
        return f"{self.cellule} - {self.mois} [{status}]"