from django.urls import path
from api.views import RouteOptimizationAPIView, RouteMapView

urlpatterns = [
    # API endpoints
    path('optimize-route', RouteOptimizationAPIView.as_view(), name='optimize-route-no-slash'),
    path('optimize-route/', RouteOptimizationAPIView.as_view(), name='optimize-route-slash'),

    # Interactive visual map views
    path('map', RouteMapView.as_view(), name='route-map-no-slash'),
    path('map/', RouteMapView.as_view(), name='route-map'),
]