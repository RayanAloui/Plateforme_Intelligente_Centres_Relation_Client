from django.urls import path

from planning import pages
from portal import views

urlpatterns = [
    path("", views.home, name="home"),
    path("alertes/", views.page("alerts"), name="alerts"),
    path("prevision/", pages.forecast_page, name="forecast"),
    path("planning/", pages.planning_page, name="planning"),
    path("risque/", pages.risk_page, name="risk"),
    path("what-if/", views.page("whatif"), name="whatif"),
    path("historique/", views.page("history"), name="history"),
    path("assistant/", views.page("assistant"), name="assistant"),
    path("administration/parametres/", views.page("settings"), name="settings"),
    path("administration/modeles/", views.page("models"), name="models"),
    path("administration/utilisateurs/", views.page("users"), name="users"),
]
