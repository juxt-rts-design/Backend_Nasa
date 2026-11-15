import os
import sys
import threading

from django.apps import AppConfig


class AgentConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "agent"
    verbose_name = "Agent IA"

    def ready(self):
        serveur = os.environ.get("RUN_MAIN") == "true" or "--noreload" in sys.argv or "gunicorn" in sys.argv[0]
        if serveur:
            from .voix import prechauffer

            threading.Thread(target=prechauffer, name="piper-prechauffage", daemon=True).start()
