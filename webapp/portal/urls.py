from django.urls import path

from portal import views

urlpatterns = [
    path("", views.home, name="home"),
    path("alertes/", views.page("alerts"), name="alerts"),
    path("prevision/", views.page("forecast"), name="forecast"),
    path("planning/", views.page("planning"), name="planning"),
    path("risque/", views.page("risk"), name="risk"),
    path("what-if/", views.page("whatif"), name="whatif"),
    path("historique/", views.page("history"), name="history"),
    path("assistant/", views.page("assistant"), name="assistant"),
    path("administration/parametres/", views.page("settings"), name="settings"),
    path("administration/modeles/", views.page("models"), name="models"),
    path("administration/utilisateurs/", views.page("users"), name="users"),
]
