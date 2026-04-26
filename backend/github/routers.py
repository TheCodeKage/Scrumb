from rest_framework.routers import DefaultRouter

from github.views import InstallationViewSet, EventsViewSet

router = DefaultRouter()
router.register(r'', InstallationViewSet, basename="installation")
router.register(r'webhook', EventsViewSet, basename="webhook")
