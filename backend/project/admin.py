from django.contrib import admin

from project.models import Idea, Project, Feature

# Register your models here.
admin.site.register(Idea)
admin.site.register(Project)
admin.site.register(Feature)