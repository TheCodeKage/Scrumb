"""
URL configuration for backend project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from dj_rest_auth.views import PasswordResetConfirmView
from django.contrib import admin
from django.urls import path, include
import dj_rest_auth.urls as dj_rest_auth_urls, dj_rest_auth.registration.urls as dj_rest_auth_registration_urls
from projects.views import healthz
from projects.routers import router as project_router
from Users.routers import router as user_router
urlpatterns = [
    path("admin/", admin.site.urls),
    path('healthz', healthz),
    path('github/', include('Github.urls')),
    path('api/auth/registration/', include(dj_rest_auth_registration_urls)),
    path('api/auth/password-reset-confirm/<str:uidb64>/<str:token>', PasswordResetConfirmView.as_view(),name='password_reset_confirm'),
    path('api/auth/', include(dj_rest_auth_urls)),
    path('users/', include(user_router.urls)),
    path('', include(project_router.urls)),
]

