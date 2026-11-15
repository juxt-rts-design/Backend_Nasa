"""Peuple une base vide pour que globe, calendrier et auth fonctionnent en local."""

from datetime import date, datetime, timedelta
from math import cos, pi, sin
from random import Random

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils.timezone import make_aware

from calendrier.models import Calendrier, SerieMensuelle
from detections.models import Cellule, CelluleJourSatellite, DetectionBrute
from utilisateurs.models import UtilisateurProfil

User = get_user_model()

SATS = [
    ("Terra", "MODIS", date(2000, 11, 1)),
    ("Aqua", "MODIS", date(2002, 7, 4)),
    ("Suomi-NPP", "VIIRS", date(2012, 1, 19)),
    ("NOAA-20", "VIIRS", date(2018, 4, 5)),
    ("NOAA-21", "VIIRS", date(2024, 1, 5)),
]


def months_between(start, end):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield f"{y:04d}-{m:02d}"
        m += 1
        if m == 13:
            y += 1
            m = 1


class Command(BaseCommand):
    help = "Crée un compte démo et des détections / cellules / calendrier si la base est vide."

    def add_arguments(self, parser):
        parser.add_argument("--if-empty", action="store_true", help="Ne rien faire si des détections existent déjà.")
        parser.add_argument("--force", action="store_true", help="Réécrire le jeu de démo.")

    def handle(self, *args, **options):
        if options["if_empty"] and DetectionBrute.objects.exists() and not options["force"]:
            self.stdout.write("Base déjà peuplée, seed ignoré.")
            self._ensure_user()
            return
        if options["force"]:
            DetectionBrute.objects.filter(source_fichier="seed_demo").delete()
            CelluleJourSatellite.objects.all().delete()
            Calendrier.objects.all().delete()
            SerieMensuelle.objects.all().delete()
            Cellule.objects.all().delete()

        self._ensure_user()
        rng = Random(2026)
        cells = self._cellules()
        self._calendrier(cells, rng)
        self._detections(rng)
        self.stdout.write(self.style.SUCCESS(
            f"Seed OK : {DetectionBrute.objects.count()} détections, "
            f"{Cellule.objects.count()} cellules, {Calendrier.objects.count()} lignes calendrier."
        ))

    def _ensure_user(self):
        user, created = User.objects.get_or_create(
            username="observateur",
            defaults={"email": "observateur@firewatch.dev"},
        )
        if created or not user.check_password("feux2026"):
            user.set_password("feux2026")
            user.save()
        UtilisateurProfil.objects.get_or_create(user=user, defaults={"pays": "Gabon"})
        if created:
            self.stdout.write("Compte observateur / feux2026 créé.")

    def _cellules(self):
        rows = []
        lat = -4.0
        while lat <= 6.0:
            lon = 9.0
            while lon <= 22.0:
                rows.append(Cellule(lat_centre=round(lat, 5), lon_centre=round(lon, 5), taille_km=27.75))
                lon += 1.0
            lat += 1.0
        Cellule.objects.bulk_create(rows, ignore_conflicts=True)
        return list(Cellule.objects.all())

    def _calendrier(self, cells, rng):
        series, cals, jours = [], [], []
        today = date.today()
        for cell in cells:
            lat = float(cell.lat_centre)
            lon = float(cell.lon_centre)
            for mois in months_between(date(2002, 7, 1), date(today.year, today.month, 1)):
                year, month = int(mois[:4]), int(mois[5:7])
                season = 0.55 + 0.85 * (0.5 + 0.5 * cos((month - 8) * 2 * pi / 12))
                base = 4 + (6 - abs(lat)) * 0.8 + max(0, 18 - lon) * 0.15
                n = max(0.0, base * season * (0.75 + rng.random() * 0.5))
                if year == 2007 and month == 8:
                    n *= 1.85
                if year == 2023 and month == 3 and lat < 1:
                    n *= 2.4
                z = (n / (base * 0.9 + 0.1) - 1) * 3.2 + rng.uniform(-0.4, 0.4)
                frp = n * (8 + rng.random() * 6)
                series.append(SerieMensuelle(
                    cellule=cell, mois=mois, nb_detections=round(n, 2),
                    frp_total=round(frp, 2), brightness_moy=round(320 + rng.random() * 25, 2),
                ))
                cals.append(Calendrier(
                    cellule=cell, mois=mois, zscore=round(z, 3), est_anomalie=abs(z) > 2,
                ))
        SerieMensuelle.objects.bulk_create(series, ignore_conflicts=True, batch_size=1000)
        Calendrier.objects.bulk_create(cals, ignore_conflicts=True, batch_size=1000)

        # quelques agrégats journaliers récents pour les séries d'une cellule
        recent = date.today() - timedelta(days=20)
        sample = cells[:8]
        for cell in sample:
            for sat, instrument, start in SATS:
                if start > date.today():
                    continue
                d = recent
                while d <= date.today():
                    if d >= start:
                        n = rng.randint(0, 6)
                        jours.append(CelluleJourSatellite(
                            cellule=cell, date=d, satellite=sat, instrument=instrument,
                            nb_detections=n, brightness_moy=330 + rng.random() * 20,
                            frp_total=n * (5 + rng.random() * 20),
                            confidence_moy=70 + rng.random() * 20,
                        ))
                    d += timedelta(days=1)
        CelluleJourSatellite.objects.bulk_create(jours, ignore_conflicts=True, batch_size=1000)

    def _detections(self, rng):
        today = date.today()
        windows = []
        for offset in range(0, 21):
            windows.append(today - timedelta(days=offset))
        windows.extend([date(2024, 8, d) for d in range(8, 16)])
        windows.extend([date(2007, 8, d) for d in range(8, 16)])
        rows = []
        for day in windows:
            for sat, instrument, start in SATS:
                if day < start:
                    continue
                n = 6 if sat == "Aqua" else 4
                if day.month == 8:
                    n += 4
                for i in range(n):
                    lat = rng.uniform(-3.8, 5.8)
                    lon = rng.uniform(9.2, 21.5)
                    hour = 10 if sat == "Terra" else 13
                    minute = rng.randint(0, 59)
                    dt = make_aware(datetime(day.year, day.month, day.day, hour, minute, rng.randint(0, 59)))
                    conf = str(rng.randint(55, 95)) if instrument == "MODIS" else rng.choice(["n", "h", "h"])
                    rows.append(DetectionBrute(
                        latitude=round(lat, 5),
                        longitude=round(lon, 5),
                        brightness=round(310 + rng.random() * 40, 2),
                        frp=round(max(0.8, rng.lognormvariate(1.8 if instrument == "MODIS" else 1.4, 0.7)), 2),
                        confidence=conf,
                        satellite=sat,
                        instrument=instrument,
                        date_acquisition=dt,
                        source_fichier="seed_demo",
                    ))
        DetectionBrute.objects.bulk_create(rows, ignore_conflicts=True, batch_size=500)
