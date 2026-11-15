from django.urls import path

from . import views

app_name = "detections"

urlpatterns = [
    path("globe/", views.globe, name="globe"),
    path("globe/jours/", views.globe_jours, name="globe_jours"),
    path("detections/", views.detections_liste, name="detections_liste"),
    path("detections/<int:pk>/", views.detections_detail, name="detections_detail"),
    path("cellules/", views.cellules_liste, name="cellules_liste"),
    path("cellules/<int:pk>/jours/", views.cellule_jours, name="cellule_jours"),
    path("export/csv/", views.export_csv, name="export_csv"),
]