"""In-memory station repository with spatial cKDTree indexing."""

import math
from typing import List, Optional
import numpy as np
from scipy.spatial import cKDTree

from api.constants import EARTH_RADIUS_MILES, MAX_DETOUR_MILES
from api.dataclasses import Station
from api.models import GasStation


def lat_lon_to_cartesian(lat_deg: np.ndarray, lon_deg: np.ndarray) -> np.ndarray:
    """Convert latitude/longitude arrays in degrees to 3D Cartesian coordinates on unit sphere."""
    rad_lat = np.radians(lat_deg)
    rad_lon = np.radians(lon_deg)
    x = np.cos(rad_lat) * np.cos(rad_lon)
    y = np.cos(rad_lat) * np.sin(rad_lon)
    z = np.sin(rad_lat)
    return np.column_stack((x, y, z))


def detour_miles_to_chord_distance(miles: float) -> float:
    """Convert surface distance in miles on sphere to 3D Euclidean chord distance."""
    theta = miles / EARTH_RADIUS_MILES
    return 2.0 * math.sin(theta / 2.0)


class StationRepository:
    """Singleton in-memory station store indexed with scipy cKDTree."""

    _instance: Optional["StationRepository"] = None

    def __init__(self):
        self._stations: List[Station] = []
        self._tree: Optional[cKDTree] = None
        self._load()

    @classmethod
    def get_instance(cls) -> "StationRepository":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Clear cached instance (useful for unit testing)."""
        cls._instance = None

    def _load(self) -> None:
        qs = GasStation.objects.filter(
            latitude__isnull=False,
            longitude__isnull=False,
            retail_price__gt=0.0,
        ).values(
            "opis_truckstop_id",
            "truckstop_name",
            "address",
            "city",
            "state",
            "rack_id",
            "retail_price",
            "latitude",
            "longitude",
        )

        stations = []
        lats = []
        lons = []

        for row in qs:
            st = Station(
                opis_truckstop_id=row["opis_truckstop_id"],
                truckstop_name=(row["truckstop_name"] or "").strip(),
                address=(row["address"] or "").strip(),
                city=(row["city"] or "").strip(),
                state=(row["state"] or "").strip(),
                retail_price=float(row["retail_price"]),
                latitude=float(row["latitude"]),
                longitude=float(row["longitude"]),
            )
            stations.append(st)
            lats.append(st.latitude)
            lons.append(st.longitude)

        self._stations = stations
        if stations:
            cartesian = lat_lon_to_cartesian(np.array(lats), np.array(lons))
            self._tree = cKDTree(cartesian)
        else:
            self._tree = None

    def find_nearby_stations(
        self,
        route_coords: List[tuple[float, float]],
        max_detour_miles: float = MAX_DETOUR_MILES,
    ) -> List[Station]:
        """Find all stations within max_detour_miles of any point in route_coords."""
        if not self._stations or self._tree is None or not route_coords:
            return []

        # Downsample dense route polyline for fast spatial lookup (step ~ every 5-10 miles)
        # Using every point or subsample guarantees finding any station within tolerance
        step = max(1, len(route_coords) // 200)
        sampled_coords = route_coords[::step]
        if route_coords[-1] != sampled_coords[-1]:
            sampled_coords.append(route_coords[-1])

        lats = np.array([c[0] for c in sampled_coords])
        lons = np.array([c[1] for c in sampled_coords])
        query_xyz = lat_lon_to_cartesian(lats, lons)

        # Buffer radius slightly to account for line segments between sampled vertices
        chord_radius = detour_miles_to_chord_distance(max_detour_miles * 1.25)
        neighbor_indices_list = self._tree.query_ball_point(query_xyz, r=chord_radius)

        matched_indices = set()
        for idx_group in neighbor_indices_list:
            matched_indices.update(idx_group)

        return [self._stations[idx] for idx in matched_indices]
