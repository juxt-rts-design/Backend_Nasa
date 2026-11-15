from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator, RegexValidator


class DetectionBrute(models.Model):
    latitude = models.FloatField(validators=[MinValueValidator(-90), MaxValueValidator(90)])
    longitude = models.FloatField(validators=[MinValueValidator(-180), MaxValueValidator(180)])
    brightness = models.FloatField()
    frp = models.FloatField(help_text="Fire Radiative Power en MW")
    confidence = models.CharField(max_length=10, help_text="0-100 pour MODIS, l/n/h pour VIIRS")
    satellite = models.CharField(max_length=20)
    instrument = models.CharField(max_length=10)
    date_acquisition = models.DateTimeField()
    source_fichier = models.CharField(max_length=255)

    class Meta:
        db_table = "detection_brute"
        verbose_name = "Détection brute"
        verbose_name_plural = "Détections brutes"
        indexes = [
            models.Index(fields=["date_acquisition"]),
            models.Index(fields=["satellite"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["latitude", "longitude", "date_acquisition", "satellite"],
                name="uniq_detection_brute",
            ),
        ]

    def __str__(self):
        return f"{self.satellite} {self.date_acquisition} ({self.latitude}, {self.longitude})"


class Cellule(models.Model):
    lat_centre = models.DecimalField(
        max_digits=8, decimal_places=5,
        validators=[MinValueValidator(-90), MaxValueValidator(90)],
    )
    lon_centre = models.DecimalField(
        max_digits=9, decimal_places=5,
        validators=[MinValueValidator(-180), MaxValueValidator(180)],
    )
    taille_km = models.FloatField(default=27.75, verbose_name="taille (km)")

    class Meta:
        db_table = "cellule"
        verbose_name = "Cellule"
        verbose_name_plural = "Cellules"
        constraints = [
            models.UniqueConstraint(
                fields=["lat_centre", "lon_centre"],
                name="uniq_cellule_coords",
            ),
        ]

    def __str__(self):
        return f"Cellule ({self.lat_centre}, {self.lon_centre})"


MOIS_VALIDATOR = RegexValidator(
    regex=r"^\d{4}-(0[1-9]|1[0-2])$",
    message="Le format doit être YYYY-MM (ex: 2026-06).",
)


class CelluleJourSatellite(models.Model):
    cellule = models.ForeignKey(Cellule, on_delete=models.CASCADE, related_name="jours")
    date = models.DateField()
    satellite = models.CharField(max_length=20)
    instrument = models.CharField(max_length=10)
    nb_detections = models.PositiveIntegerField(default=0)
    brightness_moy = models.FloatField(default=0)
    frp_total = models.FloatField(default=0)
    confidence_moy = models.FloatField(default=0)

    class Meta:
        db_table = "cellule_jour_satellite"
        verbose_name = "Cellule / jour / satellite"
        verbose_name_plural = "Cellules / jours / satellites"
        constraints = [
            models.UniqueConstraint(
                fields=["cellule", "date", "satellite"],
                name="uniq_cellule_jour_sat",
            ),
        ]

    def __str__(self):
        return f"{self.cellule} - {self.date} - {self.satellite}"


class RatioCorrection(models.Model):
    satellite = models.CharField(max_length=20)
    instrument = models.CharField(max_length=10)
    mois = models.CharField(max_length=7, validators=[MOIS_VALIDATOR], help_text="Format YYYY-MM")
    ratio = models.FloatField(help_text="Ratio par rapport à Aqua/MODIS")
    nb_observations = models.PositiveIntegerField()

    class Meta:
        db_table = "ratio_correction"
        verbose_name = "Ratio de correction"
        verbose_name_plural = "Ratios de correction"
        constraints = [
            models.UniqueConstraint(
                fields=["satellite", "mois"],
                name="uniq_ratio_sat_mois",
            ),
        ]

    def __str__(self):
        return f"Ratio {self.satellite} - {self.mois}: {self.ratio}"