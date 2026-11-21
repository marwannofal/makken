from django.core.management.base import BaseCommand
from makken_mail.clause_sync import sync_all_partnership_works


class Command(BaseCommand):
    help = "Sync all partnership/agreement WorkAssignment progress & status from ClauseAssignment progress."

    def handle(self, *args, **options):
        updated = sync_all_partnership_works()
        self.stdout.write(self.style.SUCCESS(f"Synced {updated} work assignment(s) from agreement clauses."))
