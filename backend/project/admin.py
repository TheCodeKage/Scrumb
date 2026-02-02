from django.contrib import admin

from .models import Idea, Project, Feature, Task

# Register your models here.
admin.site.register(Idea)
admin.site.register(Project)
admin.site.register(Feature)
admin.site.register(Task)