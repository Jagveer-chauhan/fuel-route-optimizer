"""API and Map views for fuel route optimization."""

import json
import urllib.parse

from django.shortcuts import render
from django.urls import reverse
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from api.exceptions import InfeasibleRoute, RouteNotFound, RoutingUnavailable
from api.serializers import RouteOptimizationRequestSerializer
from api.services import FuelOptimizationService


from rest_framework.exceptions import ValidationError
from api.exceptions import FuelOptimizerException, InfeasibleRoute, RouteNotFound, RoutingUnavailable


def handle_service_exception(err: Exception) -> Response:
    """Map domain exceptions to specific HTTP status codes."""
    if isinstance(err, RoutingUnavailable):
        return Response({"error": str(err)}, status=status.HTTP_502_BAD_GATEWAY)
    if isinstance(err, RouteNotFound):
        return Response({"error": str(err)}, status=status.HTTP_404_NOT_FOUND)
    if isinstance(err, InfeasibleRoute):
        return Response({"error": str(err)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
    if isinstance(err, (ValidationError, ValueError)):
        return Response({"error": str(err)}, status=status.HTTP_400_BAD_REQUEST)
    raise err


class RouteOptimizationAPIView(APIView):
    def _process(self, request, payload):
        serializer = RouteOptimizationRequestSerializer(data=payload)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        try:
            import hashlib
            from django.core.cache import cache

            results = FuelOptimizationService.calculate_optimal_fuel_stops(
                origin_lat=data["origin_latitude"],
                origin_lon=data["origin_longitude"],
                dest_lat=data["destination_latitude"],
                dest_lon=data["destination_longitude"],
                start_name=data.get("start_location_name"),
                finish_name=data.get("finish_location_name"),
                include_geojson=True,
            )

            route_geojson = results.pop("route_geojson", None)

            start_label = data.get("start_location_name") or f"{data['origin_latitude']:.4f}, {data['origin_longitude']:.4f}"
            finish_label = data.get("finish_location_name") or f"{data['destination_latitude']:.4f}, {data['destination_longitude']:.4f}"

            # Pre-cache the map visualization context so map_url makes ZERO redundant external calls
            route_id = hashlib.md5(
                f"{data['origin_latitude']:.4f}_{data['origin_longitude']:.4f}_"
                f"{data['destination_latitude']:.4f}_{data['destination_longitude']:.4f}".encode()
            ).hexdigest()[:12]

            map_context = {
                "start_name": start_label,
                "finish_name": finish_label,
                "total_distance": results["total_distance_miles"],
                "total_cost": results["total_fuel_cost_usd"],
                "stops_count": results["fuel_stops_count"],
                "route_geojson_json": json.dumps(route_geojson) if route_geojson else "{}",
            }
            cache.set(f"map_ctx_{route_id}", map_context, timeout=3600)

            base_map_url = request.build_absolute_uri(reverse("route-map"))
            start_q = payload.get("start_location") or payload.get("start") or start_label
            finish_q = payload.get("finish_location") or payload.get("finish") or finish_label

            results["map_url"] = (
                f"{base_map_url}?route_id={route_id}"
                f"&start_location={urllib.parse.quote_plus(start_q)}"
                f"&finish_location={urllib.parse.quote_plus(finish_q)}"
            )

            return Response(results, status=status.HTTP_200_OK)
        except (FuelOptimizerException, ValidationError, ValueError) as err:
            return handle_service_exception(err)

    def post(self, request):
        return self._process(request, request.data)

    def get(self, request):
        params = request.query_params.dict()
        if not params:
            return Response(
                {
                    "help": "Pass start_location (e.g. 'Dallas, TX') and finish_location (e.g. 'Chicago, IL').",
                    "example": {
                        "start_location": "Dallas, TX",
                        "finish_location": "Chicago, IL",
                    },
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return self._process(request, params)


class RouteMapView(APIView):
    def get(self, request):
        from django.core.cache import cache

        params = request.query_params.dict()
        route_id = params.get("route_id")

        # 1. Fast path: reuse pre-cached map context (0 external calls, <1ms render)
        if route_id:
            cached_context = cache.get(f"map_ctx_{route_id}")
            if cached_context is not None:
                return render(request, "map.html", cached_context)

        # 2. Fallback: resolve query parameters if accessed directly
        if not any(k in params for k in ["start_location", "start", "origin", "from", "origin_latitude"]):
            return Response(
                {"error": "Please provide start_location and finish_location query parameters."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = RouteOptimizationRequestSerializer(data=params)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        try:
            results = FuelOptimizationService.calculate_optimal_fuel_stops(
                origin_lat=data["origin_latitude"],
                origin_lon=data["origin_longitude"],
                dest_lat=data["destination_latitude"],
                dest_lon=data["destination_longitude"],
                start_name=data.get("start_location_name"),
                finish_name=data.get("finish_location_name"),
                include_geojson=True,
            )

            start_name = data.get("start_location_name") or f"{data['origin_latitude']:.4f}, {data['origin_longitude']:.4f}"
            finish_name = data.get("finish_location_name") or f"{data['destination_latitude']:.4f}, {data['destination_longitude']:.4f}"

            context = {
                "start_name": start_name,
                "finish_name": finish_name,
                "total_distance": results["total_distance_miles"],
                "total_cost": results["total_fuel_cost_usd"],
                "stops_count": results["fuel_stops_count"],
                "route_geojson_json": json.dumps(results["route_geojson"]),
            }
            return render(request, "map.html", context)
        except (FuelOptimizerException, ValidationError, ValueError) as err:
            return handle_service_exception(err)