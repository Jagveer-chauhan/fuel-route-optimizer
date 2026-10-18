"""Data transfer objects and entities for fuel routing."""

from dataclasses import dataclass, field
from typing import List, Tuple


@dataclass
class Station:
    opis_truckstop_id: int
    truckstop_name: str
    address: str
    city: str
    state: str
    retail_price: float
    latitude: float
    longitude: float
    distance_along_route: float = 0.0
    miles_off_route: float = 0.0


@dataclass
class FuelStop:
    stop_number: int
    opis_truckstop_id: int
    truckstop_name: str
    address: str
    city: str
    state: str
    retail_price_per_gallon: float
    latitude: float
    longitude: float
    distance_along_route_miles: float
    miles_off_route: float
    gallons_purchased: float
    cost_at_stop: float


@dataclass
class Route:
    coordinates: List[Tuple[float, float]]  # List of (latitude, longitude)
    total_distance_miles: float
    duration_hours: float = 0.0
    cumulative_distances: List[float] = field(default_factory=list)
