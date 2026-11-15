from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from .models import Notification, UtilisateurProfil, ZoneInteret

User = get_user_model()


class InscriptionSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)
    password2 = serializers.CharField(write_only=True, required=False, allow_blank=True)
    pays = serializers.CharField(required=False, default="", allow_blank=True)

    def validate_username(self, value):
        name = (value or "").strip()
        if len(name) < 2:
            raise serializers.ValidationError("Choisissez un nom d’au moins 2 caractères.")
        if User.objects.filter(username__iexact=name).exists():
            raise serializers.ValidationError("Ce nom d’utilisateur existe déjà.")
        return name

    def validate_email(self, value):
        email = (value or "").strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise serializers.ValidationError("Cet e-mail est déjà utilisé.")
        return email

    def validate_password(self, value):
        try:
            validate_password(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages))
        return value

    def validate(self, attrs):
        confirm = attrs.get("password2")
        if confirm and confirm != attrs.get("password"):
            raise serializers.ValidationError({"password2": "Les deux mots de passe ne correspondent pas."})
        return attrs

    def create(self, validated_data):
        pays = (validated_data.pop("pays", "") or "").strip()
        validated_data.pop("password2", None)
        user = User.objects.create_user(
            username=validated_data["username"],
            email=validated_data["email"],
            password=validated_data["password"],
        )
        UtilisateurProfil.objects.create(user=user, pays=pays)
        return user


class ConnexionSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)


class ProfilSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", read_only=True)
    email = serializers.CharField(source="user.email", read_only=True)

    class Meta:
        model = UtilisateurProfil
        fields = ["username", "email", "pays", "date_inscription"]


class ZoneInteretSerializer(serializers.ModelSerializer):
    class Meta:
        model = ZoneInteret
        fields = ["id", "nom", "lat_centre", "lon_centre", "rayon_km"]
        read_only_fields = ["id"]


class NotificationSerializer(serializers.ModelSerializer):
    cellule_id = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = [
            "id",
            "cellule_id",
            "region_id",
            "region_nom",
            "lieu",
            "titre",
            "message",
            "niveau",
            "date_alerte",
            "precision",
            "lat",
            "lon",
            "lue",
            "created_at",
        ]
        read_only_fields = fields

    def get_cellule_id(self, obj):
        try:
            return int(str(obj.cle or "").rsplit(":", 1)[-1])
        except (TypeError, ValueError):
            return None