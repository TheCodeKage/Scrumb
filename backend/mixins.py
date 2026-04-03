class ActionPermissionMixin:
    permission_map = {}

    def get_permissions(self):
        permission_classes = self.permission_map.get(
            self.action,
            self.permission_classes
        )
        return [permission() for permission in permission_classes]
