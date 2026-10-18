"""Serializers for route optimization input validation."""

import concurrent.futures
from typing import Tuple
from rest_framework import serializers

from api.constants import US_MAX_LAT, US_MAX_LON, US_MIN_LAT, US_MIN_LON
from api.exceptions import RouteNotFound, RoutingUnavailable
from api.routing import GeocodingClient

_geocoding_client = GeocodingClient()


def geocode_us_location(query: str) -> Tuple[float, float, str]:
    """Resolve location string to (lat, lon, display_name)."""
    try:
        lat, lon, display_name = _geocoding_client.geocode(query)
        return lat, lon, display_name
    except (RouteNotFound, RoutingUnavailable) as err:
        raise serializers.ValidationError(str(err))


class RouteOptimizationRequestSerializer(serializers.Serializer):
    """Validates start and finish locations (city names or coordinates) within contiguous USA."""

    start_location = serializers.CharField(required=False, allow_blank=True)
    finish_location = serializers.CharField(required=False, allow_blank=True)
    start = serializers.CharField(required=False, allow_blank=True, write_only=True)
    finish = serializers.CharField(required=False, allow_blank=True, write_only=True)

    origin_latitude = serializers.FloatField(required=False, allow_null=True)
    origin_longitude = serializers.FloatField(required=False, allow_null=True)
    destination_latitude = serializers.FloatField(required=False, allow_null=True)
    destination_longitude = serializers.FloatField(required=False, allow_null=True)

    def validate(self, data):
        start_query = data.get("start_location") or data.get("start")
        finish_query = data.get("finish_location") or data.get("finish")

        origin_lat = data.get("origin_latitude")
        origin_lon = data.get("origin_longitude")
        dest_lat = data.get("destination_latitude")
        dest_lon = data.get("destination_longitude")

        # 1. Both start and finish provided as text queries (geocoded concurrently)
        if start_query and finish_query:
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                f_start = executor.submit(geocode_us_location, start_query)
                f_finish = executor.submit(geocode_us_location, finish_query)
                lat1, lon1, addr1 = f_start.result()
                lat2, lon2, addr2 = f_finish.result()
            data["origin_latitude"] = lat1
            data["origin_longitude"] = lon1
            data["start_location_name"] = addr1
            data["destination_latitude"] = lat2
            data["destination_longitude"] = lon2
            data["finish_location_name"] = addr2

        # 2. Both start and finish provided directly as coordinates (reverse-geocoded concurrently)
        elif origin_lat is not None and origin_lon is not None and dest_lat is not None and dest_lon is not None:
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                f_rev1 = executor.submit(_geocoding_client.reverse_geocode, origin_lat, origin_lon)
                f_rev2 = executor.submit(_geocoding_client.reverse_geocode, dest_lat, dest_lon)
                data["start_location_name"] = f_rev1.result()
                data["finish_location_name"] = f_rev2.result()
            data["origin_latitude"] = origin_lat
            data["origin_longitude"] = origin_lon
            data["destination_latitude"] = dest_lat
            data["destination_longitude"] = dest_lon

        # 3. Mixed inputs (one coordinate pair, one text query)
        else:
            if start_query:
                lat, lon, address = geocode_us_location(start_query)
                data["origin_latitude"] = lat
                data["origin_longitude"] = lon
                data["start_location_name"] = address
            elif origin_lat is not None and origin_lon is not None:
                data["start_location_name"] = _geocoding_client.reverse_geocode(origin_lat, origin_lon)
            else:
                raise serializers.ValidationError(
                    "Provide start_location (e.g. 'Dallas, TX') or origin_latitude & origin_longitude."
                )

            if finish_query:
                lat, lon, address = geocode_us_location(finish_query)
                data["destination_latitude"] = lat
                data["destination_longitude"] = lon
                data["finish_location_name"] = address
            elif dest_lat is not None and dest_lon is not None:
                data["finish_location_name"] = _geocoding_client.reverse_geocode(dest_lat, dest_lon)
            else:
                raise serializers.ValidationError(
                    "Provide finish_location (e.g. 'Chicago, IL') or destination_latitude & destination_longitude."
                )

        # Validate bounding box for contiguous USA
        points = [
            ("Start", data["origin_latitude"], data["origin_longitude"]),
            ("Finish", data["destination_latitude"], data["destination_longitude"]),
        ]
        for label, lat, lon in points:
            if not (US_MIN_LAT <= lat <= US_MAX_LAT and US_MIN_LON <= lon <= US_MAX_LON):
                raise serializers.ValidationError(
                    f"{label} point ({lat:.4f}, {lon:.4f}) is outside the contiguous USA."
                )

        return data