from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy

from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import CreateView, UpdateView, ListView, TemplateView, DeleteView, DetailView

from .forms import IdeaForm, ProjectForm, FeatureFormSet
from .models import Idea, Project


#---------------------------------------------------------------------------------------------------
#-------------------------------Dashboard--------------------------------------------------------------------

class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "projects/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["ideas"] = Idea.objects.filter(
            author=self.request.user,
            archived_on__isnull=True
        ).order_by("-added_on")[:5]

        context["projects"] = Project.objects.filter(
            author=self.request.user
        ).order_by("-created_at")[:5]

        return context


#-----------------------------------Ideas--------------------------------------------------------------------

class IdeaCreateView(LoginRequiredMixin, CreateView):
    model = Idea
    form_class = IdeaForm
    template_name = "projects/idea_form.html"
    success_url = reverse_lazy("idea_list")

    def form_valid(self, form):
        form.instance.author = self.request.user
        return super().form_valid(form)


class IdeaUpdateView(LoginRequiredMixin, UpdateView):
    model = Idea
    form_class = IdeaForm
    template_name = "projects/idea_form.html"
    success_url = reverse_lazy("idea_list")

    def get_queryset(self):
        return Idea.objects.filter(author=self.request.user, archived_on__isnull=True)


class IdeaListView(LoginRequiredMixin, ListView):
    model = Idea
    context_object_name = "ideas"
    template_name = "projects/idea_list.html"
    paginate_by = 10

    def get_queryset(self):
        return Idea.objects.filter(
            author=self.request.user,
            archived_on__isnull=True
        ).order_by("-added_on")


#--------------------------------------Project----------------------------------------------------------------

class ProjectListView(LoginRequiredMixin, ListView):
    model = Project
    context_object_name = "projects"
    template_name = "projects/project_list.html"
    paginate_by = 10

    def get_queryset(self):
        return Project.objects.filter(
            author=self.request.user
        ).order_by("-created_at")


class ProjectCreateView(LoginRequiredMixin, CreateView):
    model = Project
    form_class = ProjectForm
    template_name = "projects/project_form.html"
    success_url = reverse_lazy("idea_list")

    def dispatch(self, request, *args, **kwargs):
        self.idea = None
        idea_pk = request.GET.get('idea_pk')

        if idea_pk:
            self.idea = get_object_or_404(
                Idea,
                pk=idea_pk,
                author=self.request.user,
                archived_on__isnull=True,
            )

        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        if self.request.POST:
            context["feature_formset"] = FeatureFormSet(self.request.POST)
        else:
            context["feature_formset"] = FeatureFormSet()

        return context

    def get_initial(self):
        initial = super().get_initial()
        if self.idea:
            initial['description'] = self.idea.idea
        return initial

    def form_valid(self, form):
        context = self.get_context_data()
        feature_formset = context["feature_formset"]

        with transaction.atomic():
            project = form.save(commit=False)
            project.author = self.request.user
            project.save()

            if feature_formset.is_valid():
                feature_formset.instance = project
                feature_formset.save()
            else:
                return self.form_invalid(form)

        return redirect(self.success_url)


class ProjectUpdateView(LoginRequiredMixin, UpdateView):
    model = Project
    form_class = ProjectForm
    template_name = "projects/project_form.html"
    success_url = reverse_lazy("idea_list")

    def get_queryset(self):
        return Project.objects.filter(author=self.request.user)

    def form_invalid(self, form):
        return self.render_to_response(self.get_context_data(form=form))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        if self.request.POST:
            context["feature_formset"] = FeatureFormSet(self.request.POST, instance=self.object)
        else:
            context["feature_formset"] = FeatureFormSet(instance=self.object)

        return context

    def form_valid(self, form):
        context = self.get_context_data()
        feature_formset = context["feature_formset"]

        with transaction.atomic():
            form.save()

            if feature_formset.is_valid():
                feature_formset.save()
            else:
                return self.form_invalid(form)

        return redirect(self.success_url)


class ProjectDetailView(LoginRequiredMixin, DetailView):
    model = Project
    template_name = "projects/project_detail.html"
    context_object_name = "project"

    def get_queryset(self):
        return (
            Project.objects
            .filter(author=self.request.user)
            .select_related("source_idea")
            .prefetch_related(
                "features__tasks",
                "tasks",
            )
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        project = self.object

        context["features"] = project.features.all()
        context["unassigned_tasks"] = project.tasks.filter(feature__isnull=True)

        return context


#------------------------------------------------------------------------------------------------------------
