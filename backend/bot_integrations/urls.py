from django.urls import path, include
from rest_framework.routers import DefaultRouter
from bot_integrations.views import LinkDiscordView, DiscordBotViews, CronJobViews

router = DefaultRouter()
router.register(r'', DiscordBotViews, basename="discord-bot-views")
router.register(r'', CronJobViews, basename="cron-job-views")

urlpatterns = [
    path('connect/', LinkDiscordView.as_view(), name='link-discord'),
    path('', include(router.urls)),
]

