"""Service layer orchestrating routing, station matching, optimization, and presentation."""

from dataclasses import asdict
from typing import Any, Dict, Optional

from api.constants import DEFAULT_RDP_EPSILON, MILES_PER_GALLON, TANK_CAPACITY_GALLONS
from api.dataclasses import Route
from api.optimizer import match_stations_along_route, optimize_fuel_stops
from api.presenters import build_route_geojson, rdp_simplify
from api.routing import OSRMClient, haversine_miles


def calculate_optimal_fuel_stops(
    origin_lat: float,
    origin_lon: float,
    dest_lat: float,
    dest_lon: float,
    start_name: Optional[str] = None,
    finish_name: Optional[str] = None,
    include_geojson: bool = False,
) -> Dict[str, Any]:
    """
    Calculate cost-optimized fuel stops along the driving route between origin and destination.

    Assumption: Vehicle begins with a full tank (50.0 gallons = 500 miles range).
    Only fuel purchased at stops en route is billed to total_fuel_cost_usd.
    """
    start_label = start_name or f"{origin_lat:.4f}, {origin_lon:.4f}"
    finish_label = finish_name or f"{dest_lat:.4f}, {dest_lon:.4f}"

    # Zero distance check
    if haversine_miles(origin_lat, origin_lon, dest_lat, dest_lon) < 0.1:
        res: Dict[str, Any] = {
            "start_location": {
                "name": start_label,
                "latitude": origin_lat,
                "longitude": origin_lon,
            },
            "finish_location": {
                "name": finish_label,
                "latitude": dest_lat,
                "longitude": dest_lon,
            },
            "total_distance_miles": 0.0,
            "highway_distance_miles": 0.0,
            "detour_distance_miles": 0.0,
            "route_duration_hours": 0.0,
            "fuel_consumed_gallons": 0.0,
            "starting_fuel_gallons": TANK_CAPACITY_GALLONS,
            "fuel_purchased_gallons": 0.0,
            "total_fuel_cost_usd": 0.0,
            "fuel_stops_count": 0,
            "assumptions": [
                "Vehicle starts with a full 500-mile tank (cost not included)",
                "Only fuel purchased en route is billed to total_fuel_cost_usd",
            ],
            "fuel_stops": [],
            "route_geometry": {
                "type": "LineString",
                "coordinates": [[origin_lon, origin_lat]],
            },
            "status": "OPTIMIZED",
        }
        if include_geojson:
            route = Route(
                coordinates=[(origin_lat, origin_lon)],
                total_distance_miles=0.0,
                duration_hours=0.0,
                cumulative_distances=[0.0],
            )
            res["route_geojson"] = build_route_geojson(route, [], start_label, finish_label)
        return res

    # 1. Fetch driving route geometry (OSRMClient with session + cache)
    routing_client = OSRMClient()
    route = routing_client.get_route(origin_lat, origin_lon, dest_lat, dest_lon)

    # 2. Match stations within detour corridor using in-memory cKDTree
    stations_along_route = match_stations_along_route(route)

    # 3. Calculate optimal fuel stops
    fuel_stops, total_cost = optimize_fuel_stops(route, stations_along_route)

    stops_data = [asdict(stop) for stop in fuel_stops]
    highway_miles = round(route.total_distance_miles, 2)
    total_detour_miles = round(sum(2.0 * s.miles_off_route for s in fuel_stops), 2)
    total_trip_miles = round(highway_miles + total_detour_miles, 2)
    fuel_consumed = round(total_trip_miles / MILES_PER_GALLON, 2)
    fuel_purchased = round(sum(s.gallons_purchased for s in fuel_stops), 2)

    # Compact route geometry for API consumers using RDP algorithm
    raw_lon_lat = [[pt[1], pt[0]] for pt in route.coordinates]
    geometry_coords = rdp_simplify(raw_lon_lat, epsilon=DEFAULT_RDP_EPSILON)

    result: Dict[str, Any] = {
        "start_location": {
            "name": start_label,
            "latitude": origin_lat,
            "longitude": origin_lon,
        },
        "finish_location": {
            "name": finish_label,
            "latitude": dest_lat,
            "longitude": dest_lon,
        },
        "total_distance_miles": total_trip_miles,
        "highway_distance_miles": highway_miles,
        "detour_distance_miles": total_detour_miles,
        "route_duration_hours": route.duration_hours,
        "fuel_consumed_gallons": fuel_consumed,
        "starting_fuel_gallons": TANK_CAPACITY_GALLONS,
        "fuel_purchased_gallons": fuel_purchased,
        "total_fuel_cost_usd": total_cost,
        "fuel_stops_count": len(fuel_stops),
        "assumptions": [
            "Vehicle starts with a full 500-mile tank (cost not included)",
            "Only fuel purchased en route is billed to total_fuel_cost_usd",
        ],
        "fuel_stops": stops_data,
        "route_geometry": {
            "type": "LineString",
            "coordinates": geometry_coords,
        },
        "status": "OPTIMIZED",
    }

    if include_geojson:
        result["route_geojson"] = build_route_geojson(
            route, fuel_stops, start_label, finish_label, simplified_coordinates=geometry_coords
        )

    return result


class FuelOptimizationService:
    calculate_optimal_fuel_stops = staticmethod(calculate_optimal_fuel_stops)