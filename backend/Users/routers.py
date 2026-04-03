from rest_framework import routers

from Users.views import TeamViewSet, InvitationViewSet, DeveloperViewSet

router = routers.DefaultRouter()
router.register(r'developer', DeveloperViewSet, basename="developer")
router.register(r'team', TeamViewSet, basename="team")
router.register(r'invite', InvitationViewSet, basename="invite")
