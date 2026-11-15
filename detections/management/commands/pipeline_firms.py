"""
Pipeline de traitement des données FIRMS (6 étapes).

Usage :
    python manage.py pipeline_firms data/firms/
    python manage.py pipeline_firms data/firms/ --etape import
    python manage.py pipeline_firms --etape anomalies
"""

import datetime
import os
from statistics import median

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.db.models import Sum, Avg
from django.db.models.functions import TruncMonth

from detections.models import (
    DetectionBrute, Cellule, CelluleJourSatellite, RatioCorrection,
)
from calendrier.models import SerieMensuelle, Calendrier


# ── Configuration ────────────────────────────────────────────────

GRID_STEP = 0.25

SATELLITE_MAP = {
    "N": "Suomi-NPP",
    "NPP": "Suomi-NPP",
    "SNPP": "Suomi-NPP",
    "Suomi-NPP": "Suomi-NPP",
    "1": "NOAA-20",
    "N20": "NOAA-20",
    "NOAA-20": "NOAA-20",
    "2": "NOAA-21",
    "N21": "NOAA-21",
    "NOAA-21": "NOAA-21",
    "Terra": "Terra",
    "Aqua": "Aqua",
}

INSTRUMENT_MAP = {
    "SNPP": "VIIRS",
    "VIIRS": "VIIRS",
    "MODIS": "MODIS",
    "OLI": "OLI",
    "OLI-2": "OLI-2",
}

VIIRS_CONFIDENCE = {"l": 30.0, "n": 60.0, "h": 90.0}

SATELLITE_REFERENCE = "Aqua"
ZSCORE_SEUIL = 2.0
MAD_FACTOR = 1.4826


# ── Utilitaires ──────────────────────────────────────────────────

def confidence_to_float(val):
    """Convertit une confidence FIRMS en valeur numérique."""
    s = str(val).strip().lower()
    if s in VIIRS_CONFIDENCE:
        return VIIRS_CONFIDENCE[s]
    try:
        return float(s)
    except (ValueError, TypeError):
        return 0.0


def robust_mad(values):
    """Median Absolute Deviation."""
    if len(values) < 2:
        return 0.0
    med = median(values)
    return median([abs(v - med) for v in values])


def robust_sigma(valeurs):
    """
    Sigma robuste avec cascade de repli :
    1. MAD × 1.4826
    2. Si MAD = 0 : écart absolu moyen × 1.2533
    3. Plancher à 1.0
    """
    if len(valeurs) < 2:
        return 1.0, valeurs[0] if valeurs else 0.0

    med = median(valeurs)
    sigma = robust_mad(valeurs) * MAD_FACTOR

    if sigma == 0:
        mean_val = sum(valeurs) / len(valeurs)
        sigma = (
            sum(abs(v - mean_val) for v in valeurs) / len(valeurs)
        ) * 1.2533

    return max(sigma, 1.0), med


def plage_mois_continue(mois_existants):
    """Génère tous les mois entre le premier et le dernier (inclus)."""
    if not mois_existants:
        return []

    premier = min(mois_existants)
    dernier = max(mois_existants)

    courant = datetime.date.fromisoformat(premier + "-01")
    fin = datetime.date.fromisoformat(dernier + "-01")

    mois = []
    while courant <= fin:
        mois.append(courant.strftime("%Y-%m"))
        if courant.month == 12:
            courant = courant.replace(year=courant.year + 1, month=1)
        else:
            courant = courant.replace(month=courant.month + 1)
    return mois


# ── Commande ─────────────────────────────────────────────────────

class Command(BaseCommand):
    help = "Pipeline de traitement des données FIRMS (6 étapes)"

    def add_arguments(self, parser):
        parser.add_argument(
            "chemin", nargs="?", type=str, default=None,
            help="Dossier contenant les fichiers CSV/JSON FIRMS",
        )
        parser.add_argument(
            "--etape", type=str, default="tout",
            choices=[
                "import", "grille", "jours",
                "ratios", "series", "anomalies", "tout",
            ],
            help="Étape à exécuter (défaut : tout)",
        )

    def handle(self, *args, **options):
        etape = options["etape"]
        chemin = options.get("chemin")

        etapes = [
            ("import", self.etape_import),
            ("grille", self.etape_grille),
            ("jours", self.etape_jours),
            ("ratios", self.etape_ratios),
            ("series", self.etape_series),
            ("anomalies", self.etape_anomalies),
        ]

        if etape == "tout":
            if not chemin:
                raise CommandError("Chemin requis pour le pipeline complet.")
            if not os.path.isdir(chemin):
                raise CommandError(f"Dossier introuvable : {chemin}")

            for nom, func in etapes:
                self.stdout.write(self.style.MIGRATE_HEADING(
                    f"\n{'='*50}\n  Étape : {nom}\n{'='*50}"
                ))
                func(chemin) if nom == "import" else func()

            self.stdout.write(self.style.SUCCESS(
                "\n Pipeline terminé avec succès !"
            ))
        else:
            if etape == "import":
                if not chemin:
                    raise CommandError("Chemin requis pour l'étape 'import'.")
                if not os.path.isdir(chemin):
                    raise CommandError(f"Dossier introuvable : {chemin}")
                self.etape_import(chemin)
            else:
                dict(etapes)[etape]()

    # ── Étape 1 : Import ────────────────────────────────────────

    def etape_import(self, chemin):
        """Lit les CSV/JSON FIRMS par lots (les archives font plusieurs Go)."""
        extensions = (".csv", ".json")
        fichiers = [
            os.path.join(chemin, f)
            for f in sorted(os.listdir(chemin))
            if f.lower().endswith(extensions)
        ]
        if not fichiers:
            raise CommandError(f"Aucun fichier CSV/JSON dans {chemin}")

        total_avant = DetectionBrute.objects.count()
        for fichier in fichiers:
            nom = os.path.basename(fichier)
            if "_LS_" in nom or nom.lower().endswith("_ls.json"):
                self.stdout.write(self.style.WARNING(
                    f"  {nom} ignoré (Landsat : pas de FRP / brightness FIRMS)"
                ))
                continue
            self.stdout.write(f"  {nom}...")
            n = self._importer_fichier(fichier, nom)
            self.stdout.write(f"    → {n} lignes traitées")

        total_apres = DetectionBrute.objects.count()
        self.stdout.write(self.style.SUCCESS(
            f"  +{total_apres - total_avant} nouvelles détections "
            f"(total : {total_apres})"
        ))

    def _importer_fichier(self, fichier, nom):
        if fichier.lower().endswith(".json"):
            return self._importer_json(fichier, nom)
        return self._importer_csv(fichier, nom)

    def _flush_batch(self, batch):
        if not batch:
            return 0
        DetectionBrute.objects.bulk_create(
            batch, batch_size=5000, ignore_conflicts=True,
        )
        n = len(batch)
        batch.clear()
        return n

    def _importer_json(self, fichier, nom):
        try:
            import ijson
        except ImportError as exc:
            raise CommandError(
                "Installez ijson pour lire les JSON FIRMS volumineux : pip install ijson"
            ) from exc

        lus = 0
        ok = 0
        batch = []
        with open(fichier, "rb") as fh:
            for rec in ijson.items(fh, "item"):
                lus += 1
                obj = self._detection_depuis_record(rec, nom)
                if obj:
                    batch.append(obj)
                    ok += 1
                if len(batch) >= 5000:
                    self._flush_batch(batch)
                if lus % 200000 == 0:
                    self.stdout.write(f"    … {lus} lues, {ok} valides")
        self._flush_batch(batch)
        return ok

    def _importer_csv(self, fichier, nom):
        import pandas as pd

        ok = 0
        for chunk in pd.read_csv(fichier, chunksize=5000):
            batch = []
            for rec in chunk.to_dict("records"):
                obj = self._detection_depuis_record(rec, nom)
                if obj:
                    batch.append(obj)
                    ok += 1
            self._flush_batch(batch)
        return ok

    def _detection_depuis_record(self, rec, nom):
        """Construit une DetectionBrute ou None si la ligne est invalide / hors spec."""
        try:
            lat = float(rec.get("latitude"))
            lon = float(rec.get("longitude"))
        except (TypeError, ValueError):
            return None
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return None

        typ = rec.get("type")
        if typ not in (None, "", "0", 0):
            return None

        brightness = rec.get("brightness", rec.get("bright_ti4"))
        frp = rec.get("frp")
        try:
            brightness = float(brightness)
            frp = float(frp)
        except (TypeError, ValueError):
            return None
        if frp < 0:
            return None

        acq_date = str(rec.get("acq_date") or "").strip()
        acq_time = str(rec.get("acq_time") or "0").strip().zfill(4)
        if len(acq_date) < 10:
            return None
        try:
            dt = datetime.datetime.strptime(
                f"{acq_date[:10]} {acq_time[:4]}", "%Y-%m-%d %H%M",
            ).replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            return None

        sat_raw = str(rec.get("satellite") or "").strip()
        satellite = SATELLITE_MAP.get(sat_raw, sat_raw) or "inconnu"
        if len(satellite) > 20:
            satellite = satellite[:20]

        inst_raw = str(rec.get("instrument") or "").strip()
        instrument = INSTRUMENT_MAP.get(inst_raw, inst_raw) or "MODIS"
        if instrument in ("SNPP",):
            instrument = "VIIRS"
        if len(instrument) > 10:
            instrument = instrument[:10]

        conf = rec.get("confidence")
        conf = "" if conf is None else str(conf)[:10]

        return DetectionBrute(
            latitude=round(lat, 5),
            longitude=round(lon, 5),
            brightness=brightness,
            frp=frp,
            confidence=conf,
            satellite=satellite,
            instrument=instrument,
            date_acquisition=dt,
            source_fichier=nom[:255],
        )

    # ── Étape 2 : Grille ────────────────────────────────────────

    def etape_grille(self):
        """Crée les cellules 0.25° à partir des détections (SQL, sans charger toute la table)."""
        if not DetectionBrute.objects.exists():
            raise CommandError("Aucune détection en base")
        self.stdout.write("  Calcul SQL des cellules 0,25°...")
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT IGNORE INTO cellule (lat_centre, lon_centre, taille_km)
                SELECT DISTINCT
                  CAST(ROUND(latitude / %s, 0) * %s AS DECIMAL(8,5)),
                  CAST(ROUND(longitude / %s, 0) * %s AS DECIMAL(9,5)),
                  27.75
                FROM detection_brute
                """,
                [GRID_STEP, GRID_STEP, GRID_STEP, GRID_STEP],
            )
        n = Cellule.objects.count()
        self.stdout.write(self.style.SUCCESS(f"  {n} cellules en base"))

    # ── Étape 3 : Agrégation journalière ────────────────────────

    def etape_jours(self):
        """Agrège par cellule / jour / satellite, un mois à la fois (index date)."""
        if not DetectionBrute.objects.exists():
            raise CommandError("Aucune détection en base")
        self.stdout.write("  Agrégation SQL par mois...")
        with connection.cursor() as cursor:
            cursor.execute("SELECT MIN(date_acquisition), MAX(date_acquisition) FROM detection_brute")
            debut, fin = cursor.fetchone()
        if not debut or not fin:
            raise CommandError("Aucune date d'acquisition")

        mois = debut.date().replace(day=1)
        fin_m = fin.date().replace(day=1)
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM cellule_jour_satellite")

        sql = """
            INSERT IGNORE INTO cellule_jour_satellite (
                cellule_id, date, satellite, instrument,
                nb_detections, brightness_moy, frp_total, confidence_moy
            )
            SELECT
                c.id,
                DATE(d.date_acquisition),
                d.satellite,
                d.instrument,
                COUNT(*),
                AVG(d.brightness),
                SUM(d.frp),
                AVG(
                  CASE
                    WHEN LOWER(d.confidence) = 'l' THEN 30
                    WHEN LOWER(d.confidence) IN ('n') THEN 60
                    WHEN LOWER(d.confidence) IN ('h') THEN 90
                    WHEN d.confidence REGEXP '^[0-9]' THEN CAST(d.confidence AS DECIMAL(10,2))
                    ELSE 0
                  END
                )
            FROM detection_brute d
            INNER JOIN cellule c
              ON c.lat_centre = CAST(ROUND(d.latitude / %s, 0) * %s AS DECIMAL(8,5))
             AND c.lon_centre = CAST(ROUND(d.longitude / %s, 0) * %s AS DECIMAL(9,5))
            WHERE d.date_acquisition >= %s AND d.date_acquisition < %s
            GROUP BY c.id, DATE(d.date_acquisition), d.satellite, d.instrument
        """
        while mois <= fin_m:
            if mois.month == 12:
                suivant = mois.replace(year=mois.year + 1, month=1)
            else:
                suivant = mois.replace(month=mois.month + 1)
            self.stdout.write(f"    {mois:%Y-%m}...")
            with connection.cursor() as cursor:
                cursor.execute(
                    sql,
                    [GRID_STEP, GRID_STEP, GRID_STEP, GRID_STEP, mois, suivant],
                )
                self.stdout.write(f"      {cursor.rowcount} agrégats")
            mois = suivant
        n = CelluleJourSatellite.objects.count()
        self.stdout.write(self.style.SUCCESS(f"  {n} agrégats créés"))

    # ── Étape 4 : Ratios de correction ──────────────────────────

    def etape_ratios(self):
        """Calcule les ratios satellite / Aqua par mois."""
        self.stdout.write(f"  Référence : {SATELLITE_REFERENCE}...")

        stats = (
            CelluleJourSatellite.objects
            .annotate(mois=TruncMonth("date"))
            .values("satellite", "instrument", "mois")
            .annotate(total=Sum("nb_detections"))
        )

        par_mois = {}
        for s in stats:
            mois_str = s["mois"].strftime("%Y-%m")
            par_mois.setdefault(mois_str, {})[s["satellite"]] = {
                "instrument": s["instrument"],
                "total": s["total"],
            }

        with transaction.atomic():
            RatioCorrection.objects.all().delete()
            objets = []
            mois_sans_ref = []

            for mois_str, satellites in par_mois.items():
                ref = satellites.get(SATELLITE_REFERENCE)
                if not ref or ref["total"] == 0:
                    mois_sans_ref.append(mois_str)
                    continue
                for sat_nom, sat_data in satellites.items():
                    if sat_data["total"] == 0:
                        continue
                    objets.append(RatioCorrection(
                        satellite=sat_nom,
                        instrument=sat_data["instrument"],
                        mois=mois_str,
                        ratio=round(
                            ref["total"] / sat_data["total"], 4,
                        ),
                        nb_observations=sat_data["total"],
                    ))

            RatioCorrection.objects.bulk_create(
                objets, batch_size=5000,
            )

        self.stdout.write(self.style.SUCCESS(
            f"  {len(objets)} ratios calculés"
        ))
        for m in sorted(mois_sans_ref):
            self.stdout.write(self.style.WARNING(
                f"  ⚠ {m} : pas de référence {SATELLITE_REFERENCE}, "
                "ratios non calculés"
            ))

    # ── Étape 5 : Séries mensuelles harmonisées ─────────────────

    def etape_series(self):
        """
        Agrège par cellule / mois en appliquant les ratios,
        puis divise par le nombre de satellites actifs (moyenne).
        """
        self.stdout.write("  Agrégation mensuelle harmonisée...")

        # Charger les ratios
        ratios = {
            (r.satellite, r.mois): r.ratio
            for r in RatioCorrection.objects.all()
        }
        mois_avec_ratios = set(mois for _, mois in ratios)

        # Agrégation par cellule / mois / satellite
        stats = list(
            CelluleJourSatellite.objects
            .annotate(mois=TruncMonth("date"))
            .values("cellule_id", "mois", "satellite")
            .annotate(
                nb_det=Sum("nb_detections"),
                frp=Sum("frp_total"),
                brt=Avg("brightness_moy"),
            )
        )

        # Satellites actifs par mois — zone entière
        sat_par_mois = {}
        for s in stats:
            mois_str = s["mois"].strftime("%Y-%m")
            sat_par_mois.setdefault(mois_str, set()).add(s["satellite"])
        nb_sat_actifs = {
            m: len(sats) for m, sats in sat_par_mois.items()
        }

        for mois_str in sorted(sat_par_mois):
            if mois_str not in mois_avec_ratios:
                self.stdout.write(self.style.WARNING(
                    f"  ⚠ {mois_str} : pas de référence "
                    f"{SATELLITE_REFERENCE}, données brutes utilisées"
                ))

        # Sommer les contributions harmonisées
        series = {}
        for s in stats:
            mois_str = s["mois"].strftime("%Y-%m")
            key = (s["cellule_id"], mois_str)
            ratio = ratios.get((s["satellite"], mois_str), 1.0)

            if key not in series:
                series[key] = {
                    "nb": 0.0, "frp": 0.0,
                    "brt_sum": 0.0, "brt_n": 0,
                }

            entry = series[key]
            entry["nb"] += s["nb_det"] * ratio
            entry["frp"] += s["frp"] * ratio
            entry["brt_sum"] += s["brt"]
            entry["brt_n"] += 1

        # Diviser par nb satellites actifs → moyenne harmonisée
        with transaction.atomic():
            SerieMensuelle.objects.all().delete()
            objets = []

            for (cid, mois), d in series.items():
                n_sat = nb_sat_actifs.get(mois, 1)
                objets.append(SerieMensuelle(
                    cellule_id=cid,
                    mois=mois,
                    nb_detections=round(d["nb"] / n_sat, 4),
                    frp_total=round(d["frp"] / n_sat, 2),
                    brightness_moy=round(
                        d["brt_sum"] / d["brt_n"], 2,
                    ),
                ))

            SerieMensuelle.objects.bulk_create(
                objets, batch_size=5000,
            )

        self.stdout.write(self.style.SUCCESS(
            f"  {len(objets)} séries mensuelles harmonisées"
        ))

    # ── Étape 6 : Détection d'anomalies ─────────────────────────

    def etape_anomalies(self):
        """
        Z-score robuste (médiane + MAD) avec :
        - repli si MAD = 0 (écart absolu moyen, puis plancher 1.0)
        - plage continue de mois (mois vides = 0)
        - z-score saisonnier si ≥ 3 valeurs par mois de l'année
        """
        self.stdout.write("  Calcul des z-scores robustes...")

        # Plage continue de mois
        mois_existants = sorted(set(
            s["mois"]
            for s in SerieMensuelle.objects.values("mois").distinct()
        ))
        if not mois_existants:
            raise CommandError("Aucune série mensuelle en base")

        tous_mois = plage_mois_continue(mois_existants)
        self.stdout.write(
            f"  Plage : {tous_mois[0]} → {tous_mois[-1]} "
            f"({len(tous_mois)} mois)"
        )

        # Grouper par cellule
        par_cellule = {}
        for s in SerieMensuelle.objects.values(
            "cellule_id", "mois", "nb_detections",
        ):
            par_cellule.setdefault(
                s["cellule_id"], {},
            )[s["mois"]] = s["nb_detections"]

        # Vérifier si on peut faire du saisonnier (≥ 3 ans)
        annees = set(m[:4] for m in tous_mois)
        saisonnier = len(annees) >= 3

        if saisonnier:
            self.stdout.write("  Mode saisonnier (≥ 3 ans de données)")
        else:
            self.stdout.write(self.style.WARNING(
                f"  ⚠ Données sur {len(annees)} an(s) : z-score global "
                "(pas saisonnier). Les pics de saison sèche "
                "apparaîtront comme anomalies."
            ))

        with transaction.atomic():
            Calendrier.objects.all().delete()
            objets = []
            nb_anomalies = 0

            for cellule_id, mois_data in par_cellule.items():
                valeurs_par_mois = {
                    m: mois_data.get(m, 0) for m in tous_mois
                }

                if len(valeurs_par_mois) < 3:
                    for mois_str, nb in valeurs_par_mois.items():
                        objets.append(Calendrier(
                            cellule_id=cellule_id,
                            mois=mois_str,
                            zscore=0,
                            est_anomalie=False,
                        ))
                    continue

                if saisonnier:
                    # Grouper par mois de l'année (1-12)
                    par_mois_annee = {}
                    for m, nb in valeurs_par_mois.items():
                        mois_num = int(m[5:7])
                        par_mois_annee.setdefault(
                            mois_num, [],
                        ).append((m, nb))

                    for mois_num, paires in par_mois_annee.items():
                        vals = [nb for _, nb in paires]
                        if len(vals) < 3:
                            # Pas assez → z-score global pour ce mois
                            all_vals = list(valeurs_par_mois.values())
                            sigma, med = robust_sigma(all_vals)
                        else:
                            sigma, med = robust_sigma(vals)

                        for mois_str, nb in paires:
                            z = (nb - med) / sigma
                            anomalie = z > ZSCORE_SEUIL
                            if anomalie:
                                nb_anomalies += 1
                            objets.append(Calendrier(
                                cellule_id=cellule_id,
                                mois=mois_str,
                                zscore=round(z, 4),
                                est_anomalie=anomalie,
                            ))
                else:
                    # Z-score global
                    valeurs = list(valeurs_par_mois.values())
                    sigma, med = robust_sigma(valeurs)

                    for mois_str, nb in valeurs_par_mois.items():
                        z = (nb - med) / sigma
                        anomalie = z > ZSCORE_SEUIL
                        if anomalie:
                            nb_anomalies += 1
                        objets.append(Calendrier(
                            cellule_id=cellule_id,
                            mois=mois_str,
                            zscore=round(z, 4),
                            est_anomalie=anomalie,
                        ))

            Calendrier.objects.bulk_create(objets, batch_size=5000)

        self.stdout.write(self.style.SUCCESS(
            f"  {len(objets)} entrées, {nb_anomalies} anomalies"
        ))