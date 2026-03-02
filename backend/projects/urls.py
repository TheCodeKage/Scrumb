from rest_framework.routers import DefaultRouter
from django.urls import path, include

from projects.views import ProjectViewSet

router = DefaultRouter()
router.register(r'project', ProjectViewSet, basename="project")

urlpatterns = [
    path('', include(router.urls)),
]