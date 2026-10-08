from django.urls import path

from planning import views

urlpatterns = [
    path("cycle/lancer/", views.cycle_launch, name="cycle_launch"),
    path("cycle/<int:pk>/", views.cycle_status, name="cycle_status"),
]
