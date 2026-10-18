"""Route corridor matching and fuel optimization algorithms."""

import math
from typing import List, Optional, Tuple
import numpy as np
from scipy.spatial import cKDTree

from api.constants import (
    EARTH_RADIUS_MILES,
    MAX_DETOUR_MILES,
    MAX_VEHICLE_RANGE_MILES,
    MILES_PER_GALLON,
    STATION_CLUSTER_TOLERANCE_MILES,
)
from api.dataclasses import FuelStop, Route, Station
from api.exceptions import InfeasibleRoute


def lat_lon_to_cartesian(lat_deg: np.ndarray, lon_deg: np.ndarray) -> np.ndarray:
    """Convert latitude/longitude arrays in degrees to 3D Cartesian coordinates on unit sphere."""
    rad_lat = np.radians(lat_deg)
    rad_lon = np.radians(lon_deg)
    x = np.cos(rad_lat) * np.cos(rad_lon)
    y = np.cos(rad_lat) * np.sin(rad_lon)
    z = np.sin(rad_lat)
    return np.column_stack((x, y, z))


def project_point_to_segment(
    plat: float, plon: float,
    alat: float, alon: float,
    blat: float, blon: float,
) -> Tuple[float, float]:
    """
    Calculate cross-track distance (miles) and projection fraction t in [0, 1]
    of point P onto line segment AB using equirectangular projection.
    """
    mean_lat = math.radians((alat + blat) / 2.0)
    cos_lat = math.cos(mean_lat)

    ax = math.radians(alon) * cos_lat * EARTH_RADIUS_MILES
    ay = math.radians(alat) * EARTH_RADIUS_MILES
    bx = math.radians(blon) * cos_lat * EARTH_RADIUS_MILES
    by = math.radians(blat) * EARTH_RADIUS_MILES
    px = math.radians(plon) * cos_lat * EARTH_RADIUS_MILES
    py = math.radians(plat) * EARTH_RADIUS_MILES

    dx = bx - ax
    dy = by - ay
    seg_len_sq = dx * dx + dy * dy

    if seg_len_sq < 1e-12:
        dist = math.hypot(px - ax, py - ay)
        return dist, 0.0

    t = ((px - ax) * dx + (py - ay) * dy) / seg_len_sq
    t_clamped = max(0.0, min(1.0, t))

    proj_x = ax + t_clamped * dx
    proj_y = ay + t_clamped * dy
    dist = math.hypot(px - proj_x, py - proj_y)
    return dist, t_clamped


def match_stations_along_route(
    route: Route,
    candidate_stations: Optional[List[Station]] = None,
    max_detour_miles: float = MAX_DETOUR_MILES,
) -> List[Station]:
    """Find and project stations along the route corridor within max_detour_miles."""
    if candidate_stations is None:
        from api.stations import StationRepository
        candidate_stations = StationRepository.get_instance().find_nearby_stations(
            route.coordinates, max_detour_miles
        )

    if not candidate_stations or len(route.coordinates) < 2:
        return []

    coords = route.coordinates
    cum_dist = route.cumulative_distances
    total_miles = route.total_distance_miles

    # Index route vertices in 3D Cartesian space
    route_lats = np.array([c[0] for c in coords])
    route_lons = np.array([c[1] for c in coords])
    route_xyz = lat_lon_to_cartesian(route_lats, route_lons)
    route_tree = cKDTree(route_xyz)

    # Find nearest route vertex for each candidate station (sub-millisecond batch query)
    st_lats = np.array([st.latitude for st in candidate_stations])
    st_lons = np.array([st.longitude for st in candidate_stations])
    st_xyz = lat_lon_to_cartesian(st_lats, st_lons)
    _, nearest_indices = route_tree.query(st_xyz, k=1)

    matched_stations: List[Station] = []
    n_segments = len(coords) - 1

    for k, st in enumerate(candidate_stations):
        v_idx = nearest_indices[k]
        min_cross = float("inf")
        best_mile = 0.0

        # Only test the 2-4 segments adjacent to the nearest vertex
        start_seg = max(0, v_idx - 2)
        end_seg = min(n_segments, v_idx + 2)

        for seg_idx in range(start_seg, end_seg):
            cross, t = project_point_to_segment(
                st.latitude, st.longitude,
                coords[seg_idx][0], coords[seg_idx][1],
                coords[seg_idx + 1][0], coords[seg_idx + 1][1],
            )
            if cross < min_cross:
                min_cross = cross
                best_mile = cum_dist[seg_idx] + t * (cum_dist[seg_idx + 1] - cum_dist[seg_idx])

        if min_cross <= max_detour_miles and 0.0 <= best_mile <= total_miles:
            st.distance_along_route = best_mile
            st.miles_off_route = round(min_cross, 2)
            matched_stations.append(st)

    matched_stations.sort(key=lambda s: s.distance_along_route)

    # Deduplicate clustered stations at the same highway exit within tolerance
    pruned: List[Station] = []
    for st in matched_stations:
        if pruned and (st.distance_along_route - pruned[-1].distance_along_route) < STATION_CLUSTER_TOLERANCE_MILES:
            if st.retail_price < pruned[-1].retail_price:
                pruned[-1] = st
        else:
            pruned.append(st)

    return pruned


def optimize_fuel_stops(
    route: Route,
    stations: List[Station],
) -> Tuple[List[FuelStop], float]:
    """
    Cost-optimal fuel stop calculator.

    Assumption:
    The vehicle starts with a full tank (50 gallons = 500 miles of range).
    The user only pays for fuel purchased at stops en route to complete the journey.
    """
    total_miles = route.total_distance_miles

    # Route achievable within initial tank (500 miles): 0 stops, $0.00 en route
    if total_miles <= MAX_VEHICLE_RANGE_MILES:
        return [], 0.0

    if not stations:
        raise InfeasibleRoute(
            f"Route infeasible: Total distance {total_miles:.1f} mi exceeds vehicle range "
            f"({MAX_VEHICLE_RANGE_MILES:.0f} mi) and no stations exist within {MAX_DETOUR_MILES:.0f} miles."
        )

    sorted_stations = sorted(stations, key=lambda s: s.distance_along_route)

    # Check gap between origin and first station
    if sorted_stations[0].distance_along_route > MAX_VEHICLE_RANGE_MILES:
        raise InfeasibleRoute(
            f"Route infeasible: First station is at mile {sorted_stations[0].distance_along_route:.1f}, "
            f"exceeding vehicle range of {MAX_VEHICLE_RANGE_MILES:.0f} miles."
        )

    # Check gaps between consecutive stations
    for i in range(len(sorted_stations) - 1):
        gap = sorted_stations[i + 1].distance_along_route - sorted_stations[i].distance_along_route
        if gap > MAX_VEHICLE_RANGE_MILES:
            if total_miles > sorted_stations[i].distance_along_route + MAX_VEHICLE_RANGE_MILES:
                raise InfeasibleRoute(
                    f"Route infeasible: Gap of {gap:.1f} miles between mile "
                    f"{sorted_stations[i].distance_along_route:.1f} and "
                    f"{sorted_stations[i + 1].distance_along_route:.1f} exceeds {MAX_VEHICLE_RANGE_MILES:.0f} miles."
                )

    # Check gap from last station to destination
    if total_miles - sorted_stations[-1].distance_along_route > MAX_VEHICLE_RANGE_MILES:
        raise InfeasibleRoute(
            f"Route infeasible: Destination is {total_miles - sorted_stations[-1].distance_along_route:.1f} miles "
            f"from last station, exceeding {MAX_VEHICLE_RANGE_MILES:.0f} miles."
        )

    reachable_from_origin = [
        s for s in sorted_stations if s.distance_along_route <= MAX_VEHICLE_RANGE_MILES
    ]
    curr_station = min(
        reachable_from_origin, key=lambda s: (s.retail_price, -s.distance_along_route)
    )
    current_fuel = MAX_VEHICLE_RANGE_MILES - curr_station.distance_along_route
    curr_idx = sorted_stations.index(curr_station)

    stops: List[FuelStop] = []
    stop_counter = 1

    while True:
        dist_to_dest = total_miles - curr_station.distance_along_route
        can_reach_dest = dist_to_dest <= MAX_VEHICLE_RANGE_MILES

        downstream = [
            s for s in sorted_stations[curr_idx + 1 :]
            if s.distance_along_route - curr_station.distance_along_route <= MAX_VEHICLE_RANGE_MILES
        ]

        # Round-trip detour distance to exit and return to highway
        curr_detour_miles = 2.0 * curr_station.miles_off_route

        # Filter downstream stations: only consider a station cheaper if price savings beat its detour cost
        cheaper = []
        for s in downstream:
            if s.retail_price < curr_station.retail_price:
                dist_to_s = s.distance_along_route - curr_station.distance_along_route
                gallons_at_s = dist_to_s / MILES_PER_GALLON
                detour_cost_s = (2.0 * s.miles_off_route / MILES_PER_GALLON) * s.retail_price
                price_savings = gallons_at_s * (curr_station.retail_price - s.retail_price)
                if price_savings >= detour_cost_s:
                    cheaper.append(s)

        if cheaper:
            target = cheaper[0]
            dist_needed = target.distance_along_route - curr_station.distance_along_route
            fuel_to_buy = max(0.0, (dist_needed + curr_detour_miles) - current_fuel)

            if fuel_to_buy > 0.0:
                gallons = fuel_to_buy / MILES_PER_GALLON
                cost = gallons * curr_station.retail_price
                stops.append(
                    FuelStop(
                        stop_number=stop_counter,
                        opis_truckstop_id=curr_station.opis_truckstop_id,
                        truckstop_name=curr_station.truckstop_name,
                        address=curr_station.address,
                        city=curr_station.city,
                        state=curr_station.state,
                        retail_price_per_gallon=round(curr_station.retail_price, 3),
                        latitude=curr_station.latitude,
                        longitude=curr_station.longitude,
                        distance_along_route_miles=round(curr_station.distance_along_route, 2),
                        miles_off_route=round(curr_station.miles_off_route, 2),
                        gallons_purchased=round(gallons, 2),
                        cost_at_stop=round(cost, 2),
                    )
                )
                stop_counter += 1
                current_fuel += fuel_to_buy

            current_fuel -= (dist_needed + curr_detour_miles)
            curr_idx = sorted_stations.index(target)
            curr_station = target
        else:
            if can_reach_dest:
                fuel_to_buy = max(0.0, (dist_to_dest + curr_detour_miles) - current_fuel)
                if fuel_to_buy > 0.0:
                    gallons = fuel_to_buy / MILES_PER_GALLON
                    cost = gallons * curr_station.retail_price
                    stops.append(
                        FuelStop(
                            stop_number=stop_counter,
                            opis_truckstop_id=curr_station.opis_truckstop_id,
                            truckstop_name=curr_station.truckstop_name,
                            address=curr_station.address,
                            city=curr_station.city,
                            state=curr_station.state,
                            retail_price_per_gallon=round(curr_station.retail_price, 3),
                            latitude=curr_station.latitude,
                            longitude=curr_station.longitude,
                            distance_along_route_miles=round(curr_station.distance_along_route, 2),
                            miles_off_route=round(curr_station.miles_off_route, 2),
                            gallons_purchased=round(gallons, 2),
                            cost_at_stop=round(cost, 2),
                        )
                    )
                break
            else:
                fuel_to_buy = max(0.0, MAX_VEHICLE_RANGE_MILES - current_fuel)
                if fuel_to_buy > 0.0:
                    gallons = fuel_to_buy / MILES_PER_GALLON
                    cost = gallons * curr_station.retail_price
                    stops.append(
                        FuelStop(
                            stop_number=stop_counter,
                            opis_truckstop_id=curr_station.opis_truckstop_id,
                            truckstop_name=curr_station.truckstop_name,
                            address=curr_station.address,
                            city=curr_station.city,
                            state=curr_station.state,
                            retail_price_per_gallon=round(curr_station.retail_price, 3),
                            latitude=curr_station.latitude,
                            longitude=curr_station.longitude,
                            distance_along_route_miles=round(curr_station.distance_along_route, 2),
                            miles_off_route=round(curr_station.miles_off_route, 2),
                            gallons_purchased=round(gallons, 2),
                            cost_at_stop=round(cost, 2),
                        )
                    )
                    stop_counter += 1
                    current_fuel = MAX_VEHICLE_RANGE_MILES

                if not downstream:
                    raise InfeasibleRoute(
                        f"Route infeasible: No stations downstream within {MAX_VEHICLE_RANGE_MILES:.0f} miles from mile {curr_station.distance_along_route:.1f}."
                    )

                next_st = min(
                    downstream,
                    key=lambda s: (s.retail_price, -s.distance_along_route),
                )
                current_fuel -= (next_st.distance_along_route - curr_station.distance_along_route + curr_detour_miles)
                curr_idx = sorted_stations.index(next_st)
                curr_station = next_st

    total_cost = sum(s.cost_at_stop for s in stops)
    return stops, round(total_cost, 2)


# Backwards-compatible aliases
class CorridorMatcher:
    _project_point_to_segment = staticmethod(project_point_to_segment)
    match_stations_along_route = staticmethod(match_stations_along_route)


class FuelOptimizer:
    optimize = staticmethod(optimize_fuel_stops)
