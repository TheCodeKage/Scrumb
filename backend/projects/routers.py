from rest_framework.routers import DefaultRouter

from projects.views import ProjectViewSet, TaskViewSet

router = DefaultRouter()
router.register(r'project', ProjectViewSet, basename="project")
router.register(r'task', TaskViewSet, basename="task")
