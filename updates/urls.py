from django.conf.urls import url

from .views import TeamListView


urlpatterns = [
    url(regex=r'^my_teams/$',
        view=TeamListView.as_view(),
        name='my_teams'),
]
