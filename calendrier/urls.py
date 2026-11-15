from django.urls import path
from . import views

app_name = "calendrier"

urlpatterns = [
    path("globe/harmonise/", views.globe_harmonise, name="globe-harmonise"),
    path("calendrier/resume/", views.calendrier_resume, name="calendrier-resume"),
    path("calendrier/", views.calendrier_liste, name="calendrier-liste"),
    path("anomalies/", views.anomalies, name="anomalies"),
    path("cellules/<int:pk>/serie/", views.cellule_serie, name="cellule-serie"),
]