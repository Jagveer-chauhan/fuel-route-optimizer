"""Routing and geocoding clients with session pooling, caching, and error handling."""

import math
from typing import List, Tuple
import numpy as np
import requests
from requests.adapters import HTTPAdapter
from django.core.cache import cache

from api.constants import (
    EARTH_RADIUS_MILES,
    GEOCODE_CACHE_TIMEOUT_SECONDS,
    GEOCODING_HTTP_TIMEOUT_SECONDS,
    NOMINATIM_BASE_URL,
    OSRM_BASE_URL,
    ROUTE_CACHE_TIMEOUT_SECONDS,
    ROUTING_HTTP_TIMEOUT_SECONDS,
)
from api.dataclasses import Route
from api.exceptions import RouteNotFound, RoutingUnavailable

# Shared HTTP connection pool to avoid TLS/TCP handshake overhead on every request
_routing_session = requests.Session()
_adapter = HTTPAdapter(pool_connections=10, pool_maxsize=20, max_retries=1)
_routing_session.mount("http://", _adapter)
_routing_session.mount("https://", _adapter)


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate Great Circle distance between two lat/lon points in miles."""
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2.0) ** 2
    )
    return EARTH_RADIUS_MILES * (2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a)))


def decode_polyline(polyline_str: str, precision: int = 5) -> List[Tuple[float, float]]:
    """
    Fast Google Encoded Polyline decoder converting polyline string to [(lat, lon), ...]
    with sub-millisecond per-segment efficiency.
    """
    inv_factor = 1.0 / (10 ** precision)
    coords: List[Tuple[float, float]] = []
    index = 0
    lat = 0
    lng = 0
    length = len(polyline_str)

    while index < length:
        shift = 0
        result = 0
        while True:
            b = ord(polyline_str[index]) - 63
            index += 1
            result |= (b & 0x1F) << shift
            shift += 5
            if b < 0x20:
                break
        dlat = ~(result >> 1) if (result & 1) else (result >> 1)
        lat += dlat

        shift = 0
        result = 0
        while True:
            b = ord(polyline_str[index]) - 63
            index += 1
            result |= (b & 0x1F) << shift
            shift += 5
            if b < 0x20:
                break
        dlng = ~(result >> 1) if (result & 1) else (result >> 1)
        lng += dlng

        coords.append((lat * inv_factor, lng * inv_factor))
    return coords


def compute_cumulative_distances(coords: List[Tuple[float, float]]) -> List[float]:
    """Calculate cumulative Great Circle distance in miles along polyline using vectorized numpy."""
    n = len(coords)
    if n <= 1:
        return [0.0] * n

    arr = np.array(coords, dtype=np.float64)
    lats = np.radians(arr[:, 0])
    lons = np.radians(arr[:, 1])

    dlat = np.diff(lats)
    dlon = np.diff(lons)

    a = np.sin(dlat / 2.0) ** 2 + np.cos(lats[:-1]) * np.cos(lats[1:]) * np.sin(dlon / 2.0) ** 2
    np.clip(a, 0.0, 1.0, out=a)
    c = 2.0 * np.arcsin(np.sqrt(a))
    seg_miles = c * EARTH_RADIUS_MILES

    cum_dist = np.empty(n, dtype=np.float64)
    cum_dist[0] = 0.0
    np.cumsum(seg_miles, out=cum_dist[1:])
    return cum_dist.tolist()


class OSRMClient:
    """HTTP client for OSRM driving routes with connection pooling, polyline compression, and caching."""

    def __init__(self, session: requests.Session = None):
        self._session = session or _routing_session

    def get_route(
        self,
        origin_lat: float,
        origin_lon: float,
        dest_lat: float,
        dest_lon: float,
    ) -> Route:
        cache_key = (
            f"osrm_{round(origin_lat, 4)}_{round(origin_lon, 4)}_"
            f"{round(dest_lat, 4)}_{round(dest_lon, 4)}"
        )
        cached_data = cache.get(cache_key)
        if cached_data is not None:
            return cached_data

        url = f"{OSRM_BASE_URL}/{origin_lon},{origin_lat};{dest_lon},{dest_lat}"
        # Request encoded polyline to drop network transfer payload from 210KB down to ~30KB
        params = {
            "overview": "full",
            "geometries": "polyline",
            "steps": "false",
        }

        try:
            resp = self._session.get(url, params=params, timeout=ROUTING_HTTP_TIMEOUT_SECONDS)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as err:
            raise RoutingUnavailable(f"Routing service unavailable: {err}") from err

        if data.get("code") != "Ok" or not data.get("routes"):
            raise RouteNotFound(
                f"No driving route found between ({origin_lat:.4f}, {origin_lon:.4f}) and ({dest_lat:.4f}, {dest_lon:.4f})."
            )

        geometry_data = data["routes"][0]["geometry"]
        if isinstance(geometry_data, str):
            coords = decode_polyline(geometry_data)
        elif isinstance(geometry_data, dict) and "coordinates" in geometry_data:
            coords = [(pt[1], pt[0]) for pt in geometry_data["coordinates"]]
        else:
            coords = []

        # Single source of truth for distances: calculate cumulative distance along polyline via numpy
        cum_dist = compute_cumulative_distances(coords)

        duration_sec = float(data["routes"][0].get("duration", 0.0))
        duration_hrs = round(duration_sec / 3600.0, 2)

        route = Route(
            coordinates=coords,
            total_distance_miles=cum_dist[-1] if cum_dist else 0.0,
            duration_hours=duration_hrs,
            cumulative_distances=cum_dist,
        )

        cache.set(cache_key, route, timeout=ROUTE_CACHE_TIMEOUT_SECONDS)
        return route


class GeocodingClient:
    """HTTP client for Nominatim geocoding with connection pooling and caching."""

    def __init__(self, session: requests.Session = None):
        self._session = session or _routing_session

    def geocode(self, query: str) -> Tuple[float, float, str]:
        """Geocode location string to (lat, lon, display_name)."""
        import hashlib
        q_hash = hashlib.md5(query.strip().lower().encode("utf-8")).hexdigest()
        cache_key = f"geo_{q_hash}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        params = {
            "q": query,
            "format": "json",
            "countrycodes": "us",
            "limit": 1,
        }
        headers = {"User-Agent": "FuelRouteOptimizerAssessment/2.0"}

        try:
            resp = self._session.get(
                NOMINATIM_BASE_URL,
                params=params,
                headers=headers,
                timeout=GEOCODING_HTTP_TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
            results = resp.json()
        except requests.RequestException as err:
            raise RoutingUnavailable(f"Geocoding service unavailable: {err}") from err

        if not results:
            raise RouteNotFound(f"Location not found in contiguous US: '{query}'.")

        lat = float(results[0]["lat"])
        lon = float(results[0]["lon"])
        name = results[0].get("display_name", query)
        result = (lat, lon, name)

        cache.set(cache_key, result, timeout=GEOCODE_CACHE_TIMEOUT_SECONDS)
        return result

    def reverse_geocode(self, lat: float, lon: float) -> str:
        """Resolve coordinates to human-readable address with caching."""
        cache_key = f"rev_{round(lat, 3)}_{round(lon, 3)}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        url = "https://nominatim.openstreetmap.org/reverse"
        params = {"lat": lat, "lon": lon, "format": "json"}
        headers = {"User-Agent": "FuelRouteOptimizerAssessment/2.0"}
        try:
            resp = self._session.get(url, params=params, headers=headers, timeout=5)
            if resp.ok:
                name = resp.json().get("display_name", f"{lat:.4f}, {lon:.4f}")
                cache.set(cache_key, name, timeout=GEOCODE_CACHE_TIMEOUT_SECONDS)
                return name
        except Exception:
            pass
        return f"{lat:.4f}, {lon:.4f}"
