from rest_framework.routers import DefaultRouter

from projects.views import ProjectViewSet, TaskViewSet, QuestionViewSet

router = DefaultRouter()
router.register(r'project', ProjectViewSet, basename="project")
router.register(r'task', TaskViewSet, basename="task")
router.register(r'question', QuestionViewSet, basename="question")