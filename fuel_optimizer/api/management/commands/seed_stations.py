import os
import pandas as pd
from django.conf import settings
from django.core.management.base import BaseCommand
from api.models import GasStation

class Command(BaseCommand):
    help = 'Bulk seeds gas stations from CSV with pre-computed coordinates'

    def handle(self, *args, **kwargs):
        csv_path = os.path.join(settings.BASE_DIR, 'api', 'fuel_stations.csv')

        if not os.path.exists(csv_path):
            self.stdout.write(self.style.ERROR(f"File not found at: {csv_path}"))
            return

        self.stdout.write("Reading CSV dataset...")
        df = pd.read_csv(csv_path)
        
        stations_to_create = []

        for _, row in df.iterrows():
            stations_to_create.append(
                GasStation(
                    opis_truckstop_id=row['OPIS Truckstop ID'],
                    truckstop_name=row['Truckstop Name'],
                    address=row['Address'],
                    city=row['City'],
                    state=row['State'],
                    rack_id=row['Rack ID'],
                    retail_price=row['Retail Price'],
                    latitude=row['Geocodio Latitude'],
                    longitude=row['Geocodio Longitude']
                )
            )

        GasStation.objects.all().delete()
        
        self.stdout.write("Inserting records into PostgreSQL in bulk...")
        GasStation.objects.bulk_create(stations_to_create, batch_size=1000)
        
        self.stdout.write(self.style.SUCCESS(f"Successfully seeded {len(stations_to_create)} stations instantly!"))