from django.urls import path

from alerts import views

urlpatterns = [
    path("<int:pk>/<str:action>/", views.alert_handle, name="alert_handle"),
]
