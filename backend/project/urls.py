from django.urls import path

from .views import IdeaCreateView, IdeaUpdateView, IdeaListView, ProjectUpdateView, DashboardView, ProjectCreateView, \
    ProjectListView

urlpatterns = [
    path("", DashboardView.as_view(), name="dashboard"),
    path("idea/create", IdeaCreateView.as_view(), name="idea_create"),
    path("idea/<int:pk>/update", IdeaUpdateView.as_view(), name="idea_update"),
    path("idea", IdeaListView.as_view(), name="idea_list"),
    path("project/create", ProjectCreateView.as_view(), name="project_create"),
    path("project/<int:pk>/update", ProjectUpdateView.as_view(), name="project_update"),
    path("project", ProjectListView.as_view(), name="project_list"),
]
