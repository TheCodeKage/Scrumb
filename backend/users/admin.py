from .models import Skill, Developer, Team
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User

# Register your models here.
admin.site.register(Skill)
admin.site.register(Team)


# Define an inline admin descriptor for Developer model
# which acts a bit like a singleton
class DeveloperInline(admin.StackedInline):
    model = Developer
    can_delete = False
    verbose_name_plural = 'Developer'


# Define a new User admin
class UserAdmin(BaseUserAdmin):
    inlines = (DeveloperInline,)


# Re-register UserAdmin
admin.site.unregister(User)
admin.site.register(User, UserAdmin)
