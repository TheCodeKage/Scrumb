from django.contrib import admin

from .models import Task, Project, TaskHistory

# Register your models here.
admin.site.register(Project)

class TaskHistoryInline(admin.TabularInline):
    model = TaskHistory
    extra = 0
    fields = ('from_status', 'to_status', 'change_reason', 'timestamp')
    readonly_fields = ('from_status', 'to_status', 'change_reason', 'timestamp')
    can_delete = False

@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ('title', 'status', 'project')
    inlines = [TaskHistoryInline]
