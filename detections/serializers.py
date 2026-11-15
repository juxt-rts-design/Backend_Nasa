from rest_framework import serializers
from .models import DetectionBrute, Cellule, CelluleJourSatellite


class DetectionBruteSerializer(serializers.ModelSerializer):
    class Meta:
        model = DetectionBrute
        fields = [
            "id", "latitude", "longitude", "brightness", "frp",
            "confidence", "satellite", "instrument", "date_acquisition",
        ]


class GlobePointSerializer(serializers.ModelSerializer):
    """Serializer léger pour le globe 3D — uniquement les coords et l'intensité."""
    lat = serializers.FloatField(source="latitude")
    lon = serializers.FloatField(source="longitude")
    weight = serializers.FloatField(source="frp")

    class Meta:
        model = DetectionBrute
        fields = [
            "id", "lat", "lon", "weight", "satellite", "date_acquisition",
            "confidence", "brightness", "instrument",
        ]


class CelluleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Cellule
        fields = ["id", "lat_centre", "lon_centre", "taille_km"]


class CelluleJourSatelliteSerializer(serializers.ModelSerializer):
    class Meta:
        model = CelluleJourSatellite
        fields = [
            "id", "date", "satellite", "instrument",
            "nb_detections", "brightness_moy", "frp_total", "confidence_moy",
        ]