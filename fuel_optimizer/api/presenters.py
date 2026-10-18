"""Presenter for converting route and fuel stops to GeoJSON."""

from typing import Any, Dict, List, Optional
import numpy as np
from api.constants import DEFAULT_RDP_EPSILON
from api.dataclasses import FuelStop, Route


def rdp_simplify(points: List[List[float]], epsilon: float = DEFAULT_RDP_EPSILON) -> List[List[float]]:
    """Ramer-Douglas-Peucker polyline simplification in degrees using fast numpy vectorization."""
    if len(points) <= 2:
        return points

    pts = np.asarray(points, dtype=np.float64)
    stack = [(0, len(pts) - 1)]
    keep = np.zeros(len(pts), dtype=bool)
    keep[0] = True
    keep[-1] = True

    while stack:
        start_idx, end_idx = stack.pop()
        if end_idx - start_idx <= 1:
            continue

        p_start = pts[start_idx]
        p_end = pts[end_idx]
        segment = pts[start_idx + 1 : end_idx]

        dx = p_end[0] - p_start[0]
        dy = p_end[1] - p_start[1]
        norm = np.hypot(dx, dy)

        if norm < 1e-12:
            dist = np.hypot(segment[:, 0] - p_start[0], segment[:, 1] - p_start[1])
        else:
            dist = np.abs((segment[:, 1] - p_start[1]) * dx - (segment[:, 0] - p_start[0]) * dy) / norm

        max_idx = int(np.argmax(dist))
        max_dist = dist[max_idx]

        if max_dist > epsilon:
            split_idx = start_idx + 1 + max_idx
            keep[split_idx] = True
            stack.append((start_idx, split_idx))
            stack.append((split_idx, end_idx))

    return pts[keep].tolist()


def build_route_geojson(
    route: Route,
    fuel_stops: List[FuelStop],
    start_name: str,
    finish_name: str,
    simplified_coordinates: Optional[List[List[float]]] = None,
) -> Dict[str, Any]:
    """Format driving route polyline and fuel stops into standard GeoJSON FeatureCollection."""
    coords = route.coordinates
    if not coords:
        return {"type": "FeatureCollection", "features": []}

    if simplified_coordinates is not None:
        simplified_line = simplified_coordinates
    else:
        raw_lon_lat = [[pt[1], pt[0]] for pt in coords]
        simplified_line = rdp_simplify(raw_lon_lat, epsilon=DEFAULT_RDP_EPSILON)

    origin_lat, origin_lon = coords[0]
    dest_lat, dest_lon = coords[-1]

    features: List[Dict[str, Any]] = [
        {
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": simplified_line,
            },
            "properties": {
                "type": "route_polyline",
                "stroke": "#2563eb",
                "stroke-width": 4,
            },
        },
        {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [origin_lon, origin_lat],
            },
            "properties": {
                "type": "start_point",
                "title": "Start Location",
                "name": start_name,
                "marker_color": "#16a34a",
            },
        },
        {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [dest_lon, dest_lat],
            },
            "properties": {
                "type": "destination_point",
                "title": "Destination Location",
                "name": finish_name,
                "marker_color": "#dc2626",
            },
        },
    ]

    for stop in fuel_stops:
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [stop.longitude, stop.latitude],
            },
            "properties": {
                "type": "fuel_stop",
                "stop_number": stop.stop_number,
                "truckstop_name": stop.truckstop_name,
                "address": stop.address,
                "city": stop.city,
                "state": stop.state,
                "retail_price_per_gallon": stop.retail_price_per_gallon,
                "distance_along_route_miles": stop.distance_along_route_miles,
                "miles_off_route": stop.miles_off_route,
                "gallons_purchased": stop.gallons_purchased,
                "cost_at_stop": stop.cost_at_stop,
                "marker_color": "#ea580c",
            },
        })

    return {"type": "FeatureCollection", "features": features}


class GeoJsonPresenter:
    present = staticmethod(build_route_geojson)
