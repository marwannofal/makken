from django.core.management.base import BaseCommand

from makken_mail.reminders import queue_due_reminders


class Command(BaseCommand):
    help = 'Queue due partnership expiry reminders for the Makken email worker.'

    def handle(self, *args, **options):
        queued = queue_due_reminders()
        self.stdout.write(f'Partnership expiry reminders queued: {queued}')
