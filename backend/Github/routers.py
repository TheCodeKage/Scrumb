from rest_framework.routers import DefaultRouter

from Github.views import InstallationViewSet

router = DefaultRouter()
router.register(r'', InstallationViewSet, basename="installation")
