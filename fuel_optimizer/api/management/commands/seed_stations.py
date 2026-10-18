"""Management command to import gas stations from CSV into the database."""

import csv
import os
from typing import Dict
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from api.models import GasStation
from api.stations import StationRepository


class Command(BaseCommand):
    help = "Idempotently import and deduplicate gas stations from CSV dataset."

    def add_arguments(self, parser):
        parser.add_argument(
            "--csv-path",
            type=str,
            default=os.path.join(settings.BASE_DIR, "api", "fuel_stations.csv"),
            help="Path to fuel stations CSV file",
        )

    def handle(self, *args, **options):
        csv_path = options["csv_path"]

        if not os.path.exists(csv_path):
            self.stdout.write(self.style.ERROR(f"CSV file not found at: {csv_path}"))
            return

        self.stdout.write(f"Reading and parsing stations from {csv_path}...")

        unique_stations: Dict[int, GasStation] = {}
        skipped_duplicates = 0
        skipped_invalid = 0
        total_rows = 0

        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                total_rows += 1
                try:
                    opis_id = int(row["OPIS Truckstop ID"].strip())
                    name = row["Truckstop Name"].strip()
                    address = row["Address"].strip()
                    city = row["City"].strip()
                    state = row["State"].strip()
                    rack_id = int(row["Rack ID"].strip())
                    price = float(row["Retail Price"].strip())
                    lat = float(row["Geocodio Latitude"].strip())
                    lon = float(row["Geocodio Longitude"].strip())

                    if price <= 0.0 or lat == 0.0 or lon == 0.0:
                        skipped_invalid += 1
                        continue

                    # Deduplicate: if ID already seen, keep the lower priced station
                    if opis_id in unique_stations:
                        skipped_duplicates += 1
                        if price < unique_stations[opis_id].retail_price:
                            unique_stations[opis_id] = GasStation(
                                opis_truckstop_id=opis_id,
                                truckstop_name=name,
                                address=address,
                                city=city,
                                state=state,
                                rack_id=rack_id,
                                retail_price=price,
                                latitude=lat,
                                longitude=lon,
                            )
                    else:
                        unique_stations[opis_id] = GasStation(
                            opis_truckstop_id=opis_id,
                            truckstop_name=name,
                            address=address,
                            city=city,
                            state=state,
                            rack_id=rack_id,
                            retail_price=price,
                            latitude=lat,
                            longitude=lon,
                        )
                except (ValueError, KeyError):
                    skipped_invalid += 1

        self.stdout.write(
            f"Processed {total_rows} CSV rows. Found {len(unique_stations)} unique stations."
        )
        if skipped_duplicates > 0:
            self.stdout.write(f"Skipped {skipped_duplicates} duplicate OPIS Truckstop ID records.")
        if skipped_invalid > 0:
            self.stdout.write(f"Skipped {skipped_invalid} invalid records.")

        with transaction.atomic():
            GasStation.objects.all().delete()
            GasStation.objects.bulk_create(list(unique_stations.values()), batch_size=1000)

        # Invalidate in-memory station spatial cache
        StationRepository.reset()

        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully seeded {len(unique_stations)} unique stations into database."
            )
        )