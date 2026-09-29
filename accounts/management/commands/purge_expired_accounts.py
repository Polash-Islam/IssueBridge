from django.core.management.base import BaseCommand

from accounts.services import purge_expired_account_requests


class Command(BaseCommand):
    help = "Delete inactive self-registered Officer accounts whose one-day approval window expired."

    def handle(self, *args, **options):
        count = purge_expired_account_requests()
        self.stdout.write(self.style.SUCCESS(f"Removed {count} expired pending account(s)."))
