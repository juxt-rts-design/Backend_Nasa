from rest_framework import serializers
from .models import SerieMensuelle, Calendrier


class SerieMensuelleSerializer(serializers.ModelSerializer):
    lat = serializers.DecimalField(source="cellule.lat_centre", max_digits=8, decimal_places=5, read_only=True)
    lon = serializers.DecimalField(source="cellule.lon_centre", max_digits=9, decimal_places=5, read_only=True)

    class Meta:
        model = SerieMensuelle
        fields = ["id", "cellule_id", "lat", "lon", "mois", "nb_detections", "frp_total", "brightness_moy"]


class CalendrierSerializer(serializers.ModelSerializer):
    lat = serializers.DecimalField(source="cellule.lat_centre", max_digits=8, decimal_places=5, read_only=True)
    lon = serializers.DecimalField(source="cellule.lon_centre", max_digits=9, decimal_places=5, read_only=True)

    class Meta:
        model = Calendrier
        fields = ["id", "cellule_id", "lat", "lon", "mois", "zscore", "est_anomalie"]