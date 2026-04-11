from rest_framework.routers import DefaultRouter

from projects.views import (ProjectViewSet, ProjectPanicViewSet, ProjectAnalyticsViewSet, ProjectPlanningViewSet,
                            TaskViewSet, QuestionViewSet)

router = DefaultRouter()
router.register(r'project', ProjectViewSet, basename="project")
router.register(r'project/plan', ProjectPlanningViewSet, basename="project-plan")
router.register(r'project/panic', ProjectPanicViewSet, basename="project-panic")
router.register(r'project/analytics', ProjectAnalyticsViewSet, basename="project-analytics")
router.register(r'task', TaskViewSet, basename="task")
router.register(r'question', QuestionViewSet, basename="question")