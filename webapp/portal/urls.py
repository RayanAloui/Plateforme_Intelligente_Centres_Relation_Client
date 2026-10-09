from django.urls import path

from alerts import views as alert_views
from planning import insights, pages, scenarios
from portal import views

urlpatterns = [
    path("", views.home, name="home"),
    path("alertes/", alert_views.alert_list, name="alerts"),
    path("capacite/", insights.capacity_page, name="capacity"),
    path("prevision/", pages.forecast_page, name="forecast"),
    path("planning/", pages.planning_page, name="planning"),
    path("risque/", pages.risk_page, name="risk"),
    path("what-if/", scenarios.whatif_page, name="whatif"),
    path("historique/", insights.history_page, name="history"),
    path("assistant/", views.page("assistant"), name="assistant"),
    path("administration/parametres/", views.page("settings"), name="settings"),
    path("administration/modeles/", views.page("models"), name="models"),
    path("administration/utilisateurs/", views.page("users"), name="users"),
]
