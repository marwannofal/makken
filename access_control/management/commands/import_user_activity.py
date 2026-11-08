from django.core.management.base import BaseCommand
from access_control.activity_history import import_history


class Command(BaseCommand):
    help = 'استيراد السجلات السابقة المتاحة فقط دون اختلاق مشاهدات تاريخية.'

    def handle(self, *args, **options):
        count = import_history()
        self.stdout.write(self.style.SUCCESS(f'Imported {count} existing audit events. Original records and role grants unchanged.'))
