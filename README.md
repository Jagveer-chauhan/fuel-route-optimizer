# Spotter Fuel Route Optimizer

A high-performance backend API service built with Django and Django REST Framework that computes cost-optimized fuel stops along driving routes in the contiguous United States.

---

## Quickstart

```bash
# 1. Clone repository and navigate to project folder
git clone <repo-url>
cd "Python Django"

# 2. Create and activate a Python 3.10+ virtual environment
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Navigate to Django project, run migrations and seed stations
cd fuel_optimizer
python manage.py migrate
python manage.py seed_stations

# 5. Start the local development server
python manage.py runserver
```

* **API Endpoint**: `http://127.0.0.1:8000/api/optimize-route/?start_location=Dallas,%20TX&finish_location=Chicago,%20IL`
* **Interactive Map**: `http://127.0.0.1:8000/api/map/?start_location=Dallas,%20TX&finish_location=Chicago,%20IL`

---

## Dataset & CSV Import Command

The gas station data comes from the OPIS truckstop CSV dataset containing 8,151 rows with retail diesel prices and geocoded coordinates.

Run the import command:
```bash
python manage.py seed_stations
```

## Model Assumptions & Accounting Invariants

### 1. Departure Tank & Billing Policy
* **Departure State**: The vehicle departs with a **full tank** of 50.0 gallons (500 miles maximum vehicle range at 10 MPG).
* **Billing Policy**: **Only fuel purchased at stops en route is billed to `total_fuel_cost_usd`.**
  * Trips $\le 500$ miles require 0 stops and cost **$0.00**.
  * Trips $> 500$ miles purchase fuel only when needed.

### 2. Invariants Guaranteed by the Service:
1. `fuel_consumed_gallons == total_distance_miles / 10.0`
2. For trips $> 500$ miles: `fuel_purchased_gallons == fuel_consumed_gallons - 50.0`
3. `total_fuel_cost_usd == sum(stop.cost_at_stop for stop in fuel_stops)`
4. `fuel_stops` are strictly ordered ascending by route distance (`distance_along_route_miles`).
5. No gap exceeds 500 miles (origin to first stop, between consecutive stops, and last stop to destination).
6. **Detour Accounting**: If a station is $X$ miles off the highway polyline, the round-trip detour driving ($2 \times X$) is explicitly counted in `detour_distance_miles`, and the fuel consumed for that detour is accounted for in `fuel_consumed_gallons` and `fuel_purchased_gallons`.

### 3. Corridor & Detour Parameters
* **Highway Corridor Tolerance**: `MAX_DETOUR_MILES = 2.0` miles perpendicular distance off the route polyline.
* **Exit Cluster Pruning**: Stations within 0.5 miles along the route (e.g. at the same highway interchange) are clustered, retaining only the lowest-priced option (`STATION_CLUSTER_TOLERANCE_MILES = 0.5`).
* **Economic Detour Model**: A downstream station is only considered cheaper if the price savings across the distance exceed the round-trip detour fuel cost (`detour_cost = 2 * miles_off_route / 10 * price`).

---

## API Documentation

### 1. Route Optimization Endpoint

* **URL**: `POST /api/optimize-route/` or `GET /api/optimize-route/` (trailing slash optional)
* **Input Formats**:
  * **POST (JSON)**: `{"start_location": "Dallas, TX", "finish_location": "Chicago, IL"}` or coordinates `{"origin_latitude": 32.7767, "origin_longitude": -96.7970, "destination_latitude": 41.8781, "destination_longitude": -87.6298}`
  * **GET (Query Params)**: `?start_location=Dallas,%20TX&finish_location=Chicago,%20IL`

#### Example Request:
```bash
curl -X POST "http://127.0.0.1:8000/api/optimize-route" \
  -H "Content-Type: application/json" \
  -d '{"start_location": "Dallas, TX", "finish_location": "Chicago, IL"}'
```

#### Example Response (HTTP 200 OK):
```json
{
  "start_location": {
    "name": "Dallas, Dallas County, Texas, United States",
    "latitude": 32.7767,
    "longitude": -96.7970
  },
  "finish_location": {
    "name": "Chicago, Cook County, Illinois, United States",
    "latitude": 41.8781,
    "longitude": -87.6298
  },
  "total_distance_miles": 969.83,
  "highway_distance_miles": 966.73,
  "detour_distance_miles": 3.10,
  "route_duration_hours": 14.85,
  "fuel_consumed_gallons": 96.98,
  "starting_fuel_gallons": 50.0,
  "fuel_purchased_gallons": 46.98,
  "total_fuel_cost_usd": 134.78,
  "fuel_stops_count": 4,
  "assumptions": [
    "Vehicle starts with a full 500-mile tank (cost not included)",
    "Only fuel purchased en route is billed to total_fuel_cost_usd"
  ],
  "fuel_stops": [
    {
      "stop_number": 1,
      "opis_truckstop_id": 1493,
      "truckstop_name": "VALERO",
      "address": "401 W 1ST ST",
      "city": "Atoka",
      "state": "OK",
      "retail_price_per_gallon": 2.799,
      "latitude": 34.3800,
      "longitude": -96.1283,
      "distance_along_route_miles": 128.45,
      "miles_off_route": 0.35,
      "gallons_purchased": 10.0,
      "cost_at_stop": 27.99
    }
  ],
  "route_geometry": {
    "type": "LineString",
    "coordinates": [[-96.797, 32.7767], [-96.754, 32.842], ...]
  },
  "map_url": "http://127.0.0.1:8000/api/map/?route_id=a1b2c3d4e5f6...",
  "status": "OPTIMIZED"
}
```

### 2. Route Map Visualization Endpoint

* **URL**: `GET /api/map/`
* **Query Parameters**: `route_id` (pre-cached) or `start_location` & `finish_location`.
* **Zero External Calls**: When opening `map_url`, the pre-computed GeoJSON and metrics are served directly from cache in under **2ms**, eliminating redundant OSRM or Nominatim API calls.

---

## Architectural Highlights & Latency Optimization

| Layer | Implementation | Latency Impact |
| :--- | :--- | :--- |
| **Routing Protocol** | Encoded Google Polyline format (`geometries=polyline`) over public OSRM. | Shrinks network payload from 210 KB to 33 KB; transfer time dropped from **1.94s to 0.21s**. |
| **Distance Calculation** | Vectorized spherical trigonometry via `numpy.cumsum(np.arcsin(...))`. | Computes cumulative distances for 9,000+ points in **6.5ms**. |
| **Spatial Matching** | 3D Cartesian coordinates with `scipy.spatial.cKDTree` vertex windowing. | Corridor matching dropped from **3,019ms to 28ms (~100x speedup)**. |
| **Polyline Simplification** | Non-recursive vectorized Ramer-Douglas-Peucker (RDP). | Reduces 9,000+ vertices to ~90 points in **1.2ms**, cutting JSON size to ~13 KB raw (~2 KB gzipped). |
| **HTTP Connection Pooling** | Persistent `requests.Session` with `HTTPAdapter`. | Eliminates TCP/TLS handshake round-trips. |
| **Dual Caching Layer** | In-memory `LocMemCache` for routes, geocoding, and map contexts. | Repeated queries return in **< 50ms**. |

---

## Error Handling & HTTP Status Codes

The application uses custom domain exceptions mapped directly to appropriate HTTP responses:

| Exception | HTTP Status Code | Scenario |
| :--- | :--- | :--- |
| `ValidationError` | `400 Bad Request` | Missing parameters or coordinates outside the contiguous USA (`24°N - 50°N`, `125°W - 66°W`). |
| `RouteNotFound` | `404 Not Found` | Driving route between locations cannot be navigated. |
| `InfeasibleRoute` | `422 Unprocessable Entity` | Trip distance exceeds vehicle range and reachable fuel stations do not exist within 500-mile intervals. |
| `RoutingUnavailable` | `502 Bad Gateway` | External OSRM routing service is unreachable or timed out. |

---

## Testing

Run the automated test suite:
```bash
python manage.py test api
```

The test suite covers:
* **Canonical Optimizer Tests (Cases A, B, C, D, E)**.
* **Exact Linear Programming (LP) Global Optimum comparison** using `scipy.optimize.linprog`.
* **Single routing call assertion** (`mock_osrm.assert_called_once()`).
* **HTTP Status Code view tests**: 200, 400, 404, 422, and 502.
* **Corridor detour and cluster deduplication tests**.

---

## Known Limitations

1. **Contiguous United States**: Geocoding and station matching are bounded to the 48 contiguous US states. Trips originating or terminating in Alaska, Hawaii, or international destinations are rejected with HTTP 400.
2. **Public Demo Server Latency**: The application connects to `router.project-osrm.org` by default. For enterprise high-throughput deployments, point `OSRM_BASE_URL` in `.env` to a local or private OSRM container instance.
3. **OpenStreetMap Nominatim Rate Guidelines**: Nominatim requests comply with User-Agent policies and are cached for 24 hours to minimize upstream traffic.
