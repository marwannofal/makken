from django.apps import AppConfig


class AccessControlConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'access_control'
    verbose_name = 'إدارة المستخدمين والصلاحيات'

    def ready(self):
        from .signals import connect
        connect()
