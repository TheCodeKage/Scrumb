from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404
from django.urls import reverse_lazy
# Create your views here.
from django.views.generic import CreateView, UpdateView, ListView

from project.forms import IdeaForm
from project.models import Idea


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

    def get_object(self, queryset=None):
        return get_object_or_404(self.model, pk=self.kwargs['pk'], author=self.request.user)


class IdeaListView(LoginRequiredMixin, ListView):
    model = Idea
    context_object_name = "ideas"
    template_name = "projects/idea_list.html"
    paginate_by = 10

    def get_queryset(self):
        return Idea.objects.filter(author=self.request.user).order_by("-added_on")
