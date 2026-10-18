"""Custom domain exceptions for fuel route optimization."""


class FuelOptimizerException(Exception):
    """Base exception for fuel optimizer."""
    pass


class RoutingUnavailable(FuelOptimizerException):
    """External routing service (OSRM) failed or is unreachable."""
    pass


class RouteNotFound(FuelOptimizerException):
    """No driving route could be found between origin and destination."""
    pass


class InfeasibleRoute(FuelOptimizerException):
    """Route distance exceeds vehicle range and reachable fuel stops cannot be found."""
    pass
