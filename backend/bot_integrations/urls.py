from django.urls import path

from bot_integrations.views import LinkDiscordView

urlpatterns = [
    path('connect/', LinkDiscordView.as_view(), name='link-discord'),
]
