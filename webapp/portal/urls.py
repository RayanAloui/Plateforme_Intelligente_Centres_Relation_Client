from django.urls import path

from accounts import views as account_views
from alerts import views as alert_views
from engine import views as engine_views
from planning import insights, monitoring, pages, scenarios
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
    path("administration/parametres/", engine_views.parameters_page, name="settings"),
    path("administration/parametres/enregistrer/", engine_views.parameters_save, name="settings_save"),
    path("administration/modeles/", monitoring.models_page, name="models"),
    path("administration/modeles/reentrainer/", monitoring.model_retrain, name="model_retrain"),
    path("administration/modeles/<int:pk>/activer/", monitoring.model_activate, name="model_activate"),
    path("administration/replanifier/", monitoring.replan, name="replan"),
    path("administration/utilisateurs/", account_views.users_page, name="users"),
    path("administration/utilisateurs/creer/", account_views.user_create, name="user_create"),
    path("administration/utilisateurs/<int:pk>/modifier/", account_views.user_update, name="user_update"),
    path("administration/utilisateurs/<int:pk>/reinitialiser/", account_views.user_reset, name="user_reset"),
    path("mon-compte/mot-de-passe/", account_views.PasswordChange.as_view(), name="password_change"),
]
