from django.urls import path

from assistant import views

urlpatterns = [
    path("", views.assistant_page, name="assistant"),
    path("<int:pk>/", views.assistant_page, name="assistant_conversation"),
    path("demander/", views.assistant_ask, name="assistant_ask"),
]
