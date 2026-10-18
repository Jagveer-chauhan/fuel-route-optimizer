import math
import random
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient
from scipy.optimize import linprog

from api.dataclasses import Route, Station
from api.exceptions import InfeasibleRoute
from api.models import GasStation
from api.optimizer import FuelOptimizer
from api.services import FuelOptimizationService
from api.stations import StationRepository


class FuelOptimizationServiceTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        GasStation.objects.create(
            opis_truckstop_id=101,
            truckstop_name="SHEETZ YOUNGSTOWN",
            address="123 Highway 80",
            city="Youngstown",
            state="OH",
            rack_id=1,
            retail_price=3.05,
            latitude=41.147571,
            longitude=-80.675688,
        )
        GasStation.objects.create(
            opis_truckstop_id=102,
            truckstop_name="FLYING J TOLEDO",
            address="456 Turnpike Rd",
            city="Toledo",
            state="OH",
            rack_id=2,
            retail_price=3.25,
            latitude=41.5833,
            longitude=-83.5333,
        )
        StationRepository.reset()

    def tearDown(self):
        StationRepository.reset()

    def test_same_origin_and_destination(self):
        res = FuelOptimizationService.calculate_optimal_fuel_stops(
            origin_lat=40.7128,
            origin_lon=-74.0060,
            dest_lat=40.7128,
            dest_lon=-74.0060,
        )
        self.assertEqual(res["total_distance_miles"], 0.0)
        self.assertEqual(res["total_fuel_cost_usd"], 0.0)
        self.assertEqual(res["fuel_stops_count"], 0)
        self.assertEqual(res["fuel_stops"], [])
        self.assertEqual(res["status"], "OPTIMIZED")

    def test_trip_under_500_miles(self):
        # Trip under 500 miles (covered by initial full tank, 0 stops, $0.00 cost)
        route = Route(coordinates=[(40.7, -74.0), (39.9, -75.1)], total_distance_miles=350.0)
        station = Station(
            opis_truckstop_id=1,
            truckstop_name="TEST",
            address="1 St",
            city="City",
            state="PA",
            retail_price=3.20,
            latitude=40.0,
            longitude=-74.5,
            distance_along_route=200.0,
        )
        stops, cost = FuelOptimizer.optimize(route, [station])
        self.assertEqual(len(stops), 0)
        self.assertEqual(cost, 0.0)

    def test_gap_over_500_miles_with_no_station(self):
        route = Route(coordinates=[(40.0, -75.0), (41.0, -85.0)], total_distance_miles=1200.0)

        # Gap from origin > 500 miles
        st_late = Station(
            opis_truckstop_id=1,
            truckstop_name="Late",
            address="",
            city="",
            state="",
            retail_price=3.20,
            latitude=40.5,
            longitude=-76.0,
            distance_along_route=550.0,
        )
        with self.assertRaises(InfeasibleRoute):
            FuelOptimizer.optimize(route, [st_late])

        # Gap between stations > 500 miles
        st1 = Station(
            opis_truckstop_id=1,
            truckstop_name="S1",
            address="",
            city="",
            state="",
            retail_price=3.20,
            latitude=40.5,
            longitude=-76.0,
            distance_along_route=200.0,
        )
        st2 = Station(
            opis_truckstop_id=2,
            truckstop_name="S2",
            address="",
            city="",
            state="",
            retail_price=3.10,
            latitude=40.8,
            longitude=-78.0,
            distance_along_route=750.0,
        )
        with self.assertRaises(InfeasibleRoute):
            FuelOptimizer.optimize(route, [st1, st2])

        # Gap from last station to destination > 500 miles
        st_early = Station(
            opis_truckstop_id=1,
            truckstop_name="Early",
            address="",
            city="",
            state="",
            retail_price=3.20,
            latitude=40.5,
            longitude=-76.0,
            distance_along_route=400.0,
        )
        with self.assertRaises(InfeasibleRoute):
            FuelOptimizer.optimize(route, [st_early])

    def test_equal_prices(self):
        # 1200 mile route with 3 stations having identical prices
        route = Route(coordinates=[(40.0, -75.0), (41.0, -85.0)], total_distance_miles=1200.0)
        st1 = Station(
            opis_truckstop_id=1,
            truckstop_name="S1",
            address="",
            city="",
            state="",
            retail_price=3.25,
            latitude=40.5,
            longitude=-76.0,
            distance_along_route=300.0,
        )
        st2 = Station(
            opis_truckstop_id=2,
            truckstop_name="S2",
            address="",
            city="",
            state="",
            retail_price=3.25,
            latitude=40.8,
            longitude=-78.0,
            distance_along_route=600.0,
        )
        st3 = Station(
            opis_truckstop_id=3,
            truckstop_name="S3",
            address="",
            city="",
            state="",
            retail_price=3.25,
            latitude=41.0,
            longitude=-80.0,
            distance_along_route=900.0,
        )

        stops, cost = FuelOptimizer.optimize(route, [st1, st2, st3])
        self.assertGreater(len(stops), 0)
        # Total fuel needed: (1200 - 500) / 10 = 70 gallons @ $3.25 = $227.50
        expected_cost = round(((1200.0 - 500.0) / 10.0) * 3.25, 2)
        self.assertEqual(cost, expected_cost)

    def test_single_station_on_the_route(self):
        # 800 mile route with exactly one station at mile 400
        route = Route(coordinates=[(40.0, -75.0), (41.0, -85.0)], total_distance_miles=800.0)
        st = Station(
            opis_truckstop_id=1,
            truckstop_name="Midway",
            address="Highway 1",
            city="Mid",
            state="OH",
            retail_price=3.50,
            latitude=40.5,
            longitude=-77.0,
            distance_along_route=400.0,
        )

        stops, cost = FuelOptimizer.optimize(route, [st])
        self.assertEqual(len(stops), 1)
        self.assertEqual(stops[0].truckstop_name, "Midway")
        # Arrives at 400 with 100 miles of fuel. Needs 400 miles to finish. Buys 300 miles = 30 gallons.
        self.assertEqual(stops[0].gallons_purchased, 30.0)
        self.assertEqual(cost, 105.00)

    def test_greedy_result_compared_against_exact_solution(self):
        """
        Compare the greedy algorithm against a linear programming exact global optimum
        on randomly generated feasible station corridors.
        """
        rng = random.Random(42)

        for _ in range(15):
            # Generate random route distance between 700 and 1500 miles
            total_dist = round(rng.uniform(700.0, 1500.0), 1)

            # Generate 3 to 6 stations ensuring gaps are <= 450 miles
            num_stations = rng.randint(3, 6)
            stations = []
            curr_mile = round(rng.uniform(150.0, 400.0), 1)

            for i in range(num_stations):
                price = round(rng.uniform(2.80, 4.20), 2)
                st = Station(
                    opis_truckstop_id=1000 + i,
                    truckstop_name=f"RandSt_{i}",
                    address="",
                    city="",
                    state="US",
                    retail_price=price,
                    latitude=40.0,
                    longitude=-80.0,
                    distance_along_route=curr_mile,
                )
                stations.append(st)
                curr_mile = round(curr_mile + rng.uniform(180.0, 380.0), 1)
                if curr_mile >= total_dist - 50.0:
                    break

            if total_dist - stations[-1].distance_along_route > 500.0:
                continue

            route = Route(coordinates=[(40.0, -75.0), (41.0, -85.0)], total_distance_miles=total_dist)

            # 1. Greedy solver
            stops, greedy_cost = FuelOptimizer.optimize(route, stations)

            # 2. Exact Linear Program solver:
            # Let x_i be gallons bought at station i.
            # Objective: min sum(price_i * x_i)
            # Constraints:
            # - Arrival at each station: 50 + sum_{k<i} x_k >= d_i / 10
            # - Capacity at each station: 50 + sum_{k<=i} x_k - d_i / 10 <= 50  => sum_{k<=i} x_k <= d_i / 10
            # - Arrival at destination: 50 + sum_{k} x_k >= total_dist / 10
            n = len(stations)
            c = [s.retail_price for s in stations]

            A_ub = []
            b_ub = []

            for i in range(1, n):
                row = [-1.0 if k < i else 0.0 for k in range(n)]
                A_ub.append(row)
                b_ub.append(50.0 - (stations[i].distance_along_route / 10.0))

            for i in range(n):
                row = [1.0 if k <= i else 0.0 for k in range(n)]
                A_ub.append(row)
                b_ub.append(stations[i].distance_along_route / 10.0)

            # Destination reach constraint
            A_ub.append([-1.0] * n)
            b_ub.append(50.0 - (total_dist / 10.0))

            bounds = [(0.0, 50.0) for _ in range(n)]
            lp_res = linprog(c, A_ub=A_ub, b_ub=b_ub, bounds=bounds, method="highs")

            self.assertTrue(lp_res.success)
            exact_cost = round(lp_res.fun, 2)
            self.assertAlmostEqual(greedy_cost, exact_cost, delta=0.10)

    def test_api_with_coordinates(self):
        payload = {
            "origin_latitude": 40.7128,
            "origin_longitude": -74.0060,
            "destination_latitude": 41.8781,
            "destination_longitude": -87.6298,
        }
        response = self.client.post("/api/optimize-route", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn("total_distance_miles", data)
        self.assertIn("route_duration_hours", data)
        self.assertIn("fuel_consumed_gallons", data)
        self.assertIn("starting_fuel_gallons", data)
        self.assertIn("fuel_purchased_gallons", data)
        self.assertIn("total_fuel_cost_usd", data)
        self.assertIn("assumptions", data)
        self.assertIn("start_location", data)
        self.assertIn("finish_location", data)
        self.assertIn("route_geometry", data)
        self.assertIn("fuel_stops", data)
        self.assertIn("fuel_stops_count", data)
        self.assertIn("map_url", data)
        self.assertEqual(data["status"], "OPTIMIZED")

        if data["fuel_stops"]:
            stop = data["fuel_stops"][0]
            self.assertIn("miles_off_route", stop)
            self.assertNotIn("rack_id", stop)

    def test_api_with_addresses(self):
        payload = {
            "start_location": "New York, NY",
            "finish_location": "Philadelphia, PA",
        }
        response = self.client.post("/api/optimize-route", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn("total_distance_miles", data)
        self.assertEqual(data["total_fuel_cost_usd"], 0.0)
        self.assertEqual(data["fuel_stops_count"], 0)
        self.assertEqual(data["fuel_purchased_gallons"], 0.0)
        self.assertIn("map_url", data)
        self.assertIn("route_geometry", data)
        self.assertEqual(data["status"], "OPTIMIZED")

    def test_reject_non_us_locations(self):
        payload = {
            "start_location": "Paris, France",
            "finish_location": "Berlin, Germany",
        }
        response = self.client.post("/api/optimize-route", payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_map_view_endpoint(self):
        response = self.client.get("/api/map/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        response_map = self.client.get(
            "/api/map/?origin_latitude=40.7128&origin_longitude=-74.0060&destination_latitude=41.8781&destination_longitude=-87.6298"
        )
        self.assertEqual(response_map.status_code, status.HTTP_200_OK)
        self.assertIn(b"leaflet", response_map.content)

    def test_infeasible_route_raises_error(self):
        GasStation.objects.all().delete()
        StationRepository.reset()
        with self.assertRaises(InfeasibleRoute) as ctx:
            FuelOptimizationService.calculate_optimal_fuel_stops(
                origin_lat=40.7128,
                origin_lon=-74.0060,
                dest_lat=41.8781,
                dest_lon=-87.6298,
            )
        self.assertIn("Route infeasible", str(ctx.exception))

    def test_routing_api_called_exactly_once(self):
        """Verify external OSRM routing is called at most once per request."""
        from unittest.mock import patch
        from api.routing import OSRMClient

        fake_route = Route(
            coordinates=[(40.7128, -74.0060), (39.9526, -75.1652)],
            total_distance_miles=95.0,
            duration_hours=1.8,
            cumulative_distances=[0.0, 95.0],
        )

        with patch.object(OSRMClient, "get_route", return_value=fake_route) as mock_osrm:
            # Clear cache for this coordinate key to ensure call hits client
            from django.core.cache import cache
            cache.clear()

            payload = {
                "origin_latitude": 40.7128,
                "origin_longitude": -74.0060,
                "destination_latitude": 39.9526,
                "destination_longitude": -75.1652,
            }
            response = self.client.post("/api/optimize-route", payload, format="json")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            mock_osrm.assert_called_once()

    def test_view_status_404_route_not_found(self):
        """Assert view returns 404 when route cannot be found between locations."""
        from unittest.mock import patch
        from api.routing import OSRMClient
        from api.exceptions import RouteNotFound

        with patch.object(OSRMClient, "get_route", side_effect=RouteNotFound("No driving route found.")):
            payload = {
                "origin_latitude": 40.7128,
                "origin_longitude": -74.0060,
                "destination_latitude": 41.8781,
                "destination_longitude": -87.6298,
            }
            response = self.client.post("/api/optimize-route", payload, format="json")
            self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
            self.assertIn("error", response.json())

    def test_view_status_422_infeasible_route(self):
        """Assert view returns 422 when trip distance exceeds reach without fuel stops."""
        from unittest.mock import patch
        from api.routing import OSRMClient

        long_route = Route(
            coordinates=[(40.0, -75.0), (41.0, -85.0)],
            total_distance_miles=1500.0,
            duration_hours=24.0,
            cumulative_distances=[0.0, 1500.0],
        )
        GasStation.objects.all().delete()
        StationRepository.reset()

        with patch.object(OSRMClient, "get_route", return_value=long_route):
            payload = {
                "origin_latitude": 40.0,
                "origin_longitude": -75.0,
                "destination_latitude": 41.0,
                "destination_longitude": -85.0,
            }
            response = self.client.post("/api/optimize-route", payload, format="json")
            self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
            self.assertIn("error", response.json())

    def test_view_status_502_routing_unavailable(self):
        """Assert view returns 502 when external routing service is unreachable."""
        from unittest.mock import patch
        from api.routing import OSRMClient
        from api.exceptions import RoutingUnavailable

        with patch.object(OSRMClient, "get_route", side_effect=RoutingUnavailable("Service timeout")):
            payload = {
                "origin_latitude": 40.7128,
                "origin_longitude": -74.0060,
                "destination_latitude": 41.8781,
                "destination_longitude": -87.6298,
            }
            response = self.client.post("/api/optimize-route", payload, format="json")
            self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
            self.assertIn("error", response.json())


class CanonicalOptimizerTests(TestCase):
    """
    Exact required optimizer test cases:
    Vehicle starts full (500-mile tank, 10 MPG = 50 gallons).
    """

    def _station(self, opis_id: int, dist: float, price: float) -> Station:
        return Station(
            opis_truckstop_id=opis_id,
            truckstop_name=f"Station_{opis_id}",
            address="Addr",
            city="City",
            state="ST",
            retail_price=price,
            latitude=40.0,
            longitude=-80.0,
            distance_along_route=dist,
            miles_off_route=0.0,
        )

    def test_case_a_400_miles_any_stations(self):
        """Case A: 400 mi, any stations -> 0 stops, $0.00"""
        route = Route([(40.0, -80.0), (41.0, -81.0)], 400.0)
        stations = [self._station(1, 200.0, 3.00)]
        stops, cost = FuelOptimizer.optimize(route, stations)
        self.assertEqual(len(stops), 0)
        self.assertEqual(cost, 0.0)

    def test_case_b_800_miles_single_station(self):
        """Case B: 800 mi, station at 300 @ $3.00 -> 1 stop, 30 gal, $90.00"""
        route = Route([(40.0, -80.0), (41.0, -81.0)], 800.0)
        stations = [self._station(1, 300.0, 3.00)]
        stops, cost = FuelOptimizer.optimize(route, stations)
        self.assertEqual(len(stops), 1)
        self.assertEqual(stops[0].gallons_purchased, 30.0)
        self.assertEqual(cost, 90.00)

    def test_case_c_1000_miles_three_stations(self):
        """Case C: 1000 mi, stations 200@3.50, 450@3.00, 700@3.20 -> stops at 450 (45 gal, $135) and 700 (5 gal, $16), total $151.00"""
        route = Route([(40.0, -80.0), (41.0, -81.0)], 1000.0)
        stations = [
            self._station(1, 200.0, 3.50),
            self._station(2, 450.0, 3.00),
            self._station(3, 700.0, 3.20),
        ]
        stops, cost = FuelOptimizer.optimize(route, stations)
        self.assertEqual(len(stops), 2)
        self.assertEqual(stops[0].opis_truckstop_id, 2)
        self.assertEqual(stops[0].gallons_purchased, 45.0)
        self.assertEqual(stops[0].cost_at_stop, 135.00)
        self.assertEqual(stops[1].opis_truckstop_id, 3)
        self.assertEqual(stops[1].gallons_purchased, 5.0)
        self.assertEqual(stops[1].cost_at_stop, 16.00)
        self.assertEqual(cost, 151.00)

    def test_case_d_700_miles_two_stations(self):
        """Case D: 700 mi, stations 50@2.50, 400@4.00 -> 5 gal at 50 ($12.50) and 15 gal at 400 ($60), total $72.50"""
        route = Route([(40.0, -80.0), (41.0, -81.0)], 700.0)
        stations = [
            self._station(1, 50.0, 2.50),
            self._station(2, 400.0, 4.00),
        ]
        stops, cost = FuelOptimizer.optimize(route, stations)
        self.assertEqual(len(stops), 2)
        self.assertEqual(stops[0].opis_truckstop_id, 1)
        self.assertEqual(stops[0].gallons_purchased, 5.0)
        self.assertEqual(stops[0].cost_at_stop, 12.50)
        self.assertEqual(stops[1].opis_truckstop_id, 2)
        self.assertEqual(stops[1].gallons_purchased, 15.0)
        self.assertEqual(stops[1].cost_at_stop, 60.00)
        self.assertEqual(cost, 72.50)

    def test_case_e_1200_miles_infeasible(self):
        """Case E: 1200 mi, stations 100 and 900 -> InfeasibleRoute error"""
        route = Route([(40.0, -80.0), (41.0, -81.0)], 1200.0)
        stations = [
            self._station(1, 100.0, 3.00),
            self._station(2, 900.0, 3.00),
        ]
        with self.assertRaises(InfeasibleRoute):
            FuelOptimizer.optimize(route, stations)
