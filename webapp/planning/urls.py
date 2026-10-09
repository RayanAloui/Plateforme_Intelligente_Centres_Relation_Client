from django.urls import path

from planning import pages, views

urlpatterns = [
    path("cycle/lancer/", views.cycle_launch, name="cycle_launch"),
    path("cycle/<int:pk>/", views.cycle_status, name="cycle_status"),
    path("prevision/explication/", pages.forecast_explain, name="forecast_explain"),
    path("planning/<int:pk>/action/<str:action>/", pages.plan_transition, name="plan_transition"),
    path("planning/<int:pk>/ajuster/", pages.plan_adjust, name="plan_adjust"),
    path("planning/<int:pk>/vacation/<int:shift_id>/plus/", pages.shift_change, {"delta": 1}, name="shift_plus"),
    path("planning/<int:pk>/vacation/<int:shift_id>/moins/", pages.shift_change, {"delta": -1}, name="shift_minus"),
    path("planning/<int:pk>/vacation/ajouter/", pages.shift_add, name="shift_add"),
    path("planning/<int:pk>/export.<str:fmt>", pages.plan_export, name="plan_export"),
]
