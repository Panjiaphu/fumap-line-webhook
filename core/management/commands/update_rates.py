from django.core.management.base import BaseCommand

from core.services import ExchangeRateEngine


class Command(BaseCommand):
    help = "Fetch live rates or create a manual fallback snapshot."

    def handle(self, *args, **options):
        snapshot = ExchangeRateEngine().latest_rate()
        self.stdout.write(
            self.style.SUCCESS(
                f"Rate snapshot created: mode={snapshot.provider_mode}, twd_vnd={snapshot.official_twd_vnd_rate}"
            )
        )

