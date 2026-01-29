from django.urls import path

from project.views import IdeaCreateView, IdeaUpdateView, IdeaListView

urlpatterns = [
    path("", IdeaListView.as_view(), name="idea_list"),
    path("create", IdeaCreateView.as_view(), name="idea_create"),
    path("<int:pk>/update", IdeaUpdateView.as_view(), name="idea_update"),
]
