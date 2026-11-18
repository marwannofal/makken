from django.core.management.base import BaseCommand
from makken_mail.worker import run_batch


class Command(BaseCommand):
    help = 'Process one bounded batch of queued Makken email notifications.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=20)

    def handle(self, *args, **options):
        count = run_batch(limit=max(1, min(100, options['limit'])))
        self.stdout.write(f'Email delivery attempts: {count}')
