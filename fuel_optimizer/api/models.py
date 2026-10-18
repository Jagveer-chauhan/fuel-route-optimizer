from django.db import models

class GasStation(models.Model):
    opis_truckstop_id = models.IntegerField(db_index=True)
    truckstop_name = models.CharField(max_length=255)
    address = models.TextField()
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=50)
    rack_id = models.IntegerField()
    retail_price = models.FloatField()
    
    # Coordinates
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = 'gas_stations'
        indexes = [
            # Composite index for fast location-based queries
            models.Index(fields=['latitude', 'longitude'], name='lat_lon_idx'),
            # Index for price-based filtering and sorting faster
            models.Index(fields=['retail_price'], name='price_idx'),
        ]

    def __str__(self):
        return f"{self.truckstop_name} ({self.city}, {self.state}) - ${self.retail_price}/gal"