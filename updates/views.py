from django.shortcuts import render

from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import ListView

from .models import Team


class TeamListView(LoginRequiredMixin, ListView):
    """
    View for displaying `Team`s where logged-in user is a member.
    """
    model = Team

    def get_queryset(self):
        return self.request.user.get_teams()
