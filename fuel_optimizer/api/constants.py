"""Constants for fuel route optimization."""

# Vehicle constraints according to assessment requirements
MAX_VEHICLE_RANGE_MILES = 500.0
MILES_PER_GALLON = 10.0
TANK_CAPACITY_GALLONS = MAX_VEHICLE_RANGE_MILES / MILES_PER_GALLON  # 50.0 gallons

# Station search tolerance (tightened to highway exits)
MAX_DETOUR_MILES = 2.0  # Maximum perpendicular distance from highway corridor
STATION_CLUSTER_TOLERANCE_MILES = 0.5  # Clustered stations at same highway exit

# Geodesic / Spatial calculation constants
EARTH_RADIUS_MILES = 3958.8
DEFAULT_RDP_EPSILON = 0.0008  # ~80m simplification tolerance

# Contiguous USA geographic bounds
US_MIN_LAT, US_MAX_LAT = 24.0, 50.0
US_MIN_LON, US_MAX_LON = -125.0, -66.0

import os

# External service URLs, Timeouts & Cache TTL
OSRM_BASE_URL = os.getenv("OSRM_BASE_URL", "https://router.project-osrm.org/route/v1/driving")
NOMINATIM_BASE_URL = os.getenv("NOMINATIM_BASE_URL", "https://nominatim.openstreetmap.org/search")
ROUTING_HTTP_TIMEOUT_SECONDS = 12
GEOCODING_HTTP_TIMEOUT_SECONDS = 10
ROUTE_CACHE_TIMEOUT_SECONDS = 3600  # 1 hour
GEOCODE_CACHE_TIMEOUT_SECONDS = 86400  # 24 hours
