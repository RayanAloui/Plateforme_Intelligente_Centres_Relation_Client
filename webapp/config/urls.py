from django.conf import settings
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

urlpatterns = [
    path("connexion/", auth_views.LoginView.as_view(
        redirect_authenticated_user=True, extra_context={"demo_mode": settings.DEMO_MODE}), name="login"),
    path("deconnexion/", auth_views.LogoutView.as_view(), name="logout"),
    path("admin/", admin.site.urls),
    path("plateforme/", include("planning.urls")),
    path("plateforme/alertes/", include("alerts.urls")),
    path("", include("portal.urls")),
]

handler403 = "portal.views.forbidden"
