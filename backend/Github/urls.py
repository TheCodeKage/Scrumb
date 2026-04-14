from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import github_setup, github_callback, github_webhook


urlpatterns = [
    path('setup/<int:project_id>/', github_setup, name='github_setup'),
    path('callback/', github_callback, name='github_callback'),
    path('webhook/', github_webhook, name='github_webhook'),
]
