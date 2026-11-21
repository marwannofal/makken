from django.apps import AppConfig


class MakkenMailConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "makken_mail"

    def ready(self):
        from .signals import connect_clause_sync_signals
        connect_clause_sync_signals()
