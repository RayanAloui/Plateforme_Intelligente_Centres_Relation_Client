"""Gestion des utilisateurs (administrateur) et changement de mot de passe (tous)."""
import secrets
import string

from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.db import transaction
from django.shortcuts import get_object_or_404, render
from django.urls import reverse_lazy
from django.views.decorators.http import require_POST

from accounts.models import ROLE_DESCRIPTIONS, Role, User
from accounts.roles import role_required

ALPHABET = string.ascii_letters + string.digits


def temporary_password() -> str:
    """Mot de passe provisoire lisible (sans caracteres ambigus), a changer a la premiere connexion."""
    alphabet = "".join(c for c in ALPHABET if c not in "0O1lI")
    return "-".join("".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(3))


def active_admins() -> int:
    return User.objects.filter(is_active=True).filter(role=Role.ADMINISTRATEUR).count()


def users_context(**extra) -> dict:
    return {"page_title": "Utilisateurs", "users": User.objects.order_by("-is_active", "role", "last_name"),
            "roles": Role.choices, "descriptions": {k.value: v for k, v in ROLE_DESCRIPTIONS.items()}, **extra}


@role_required(Role.ADMINISTRATEUR)
def users_page(request):
    return render(request, "administration/users.html", users_context())


@require_POST
@role_required(Role.ADMINISTRATEUR)
def user_create(request):
    username = request.POST.get("username", "").strip().lower()
    role = request.POST.get("role")
    errors = []
    if not username.isidentifier() and not username.replace(".", "").replace("-", "").isalnum():
        errors.append("Identifiant invalide : lettres, chiffres, points ou tirets.")
    if User.objects.filter(username=username).exists():
        errors.append(f"L'identifiant « {username} » existe déjà.")
    if role not in Role.values:
        errors.append("Rôle invalide.")
    if errors:
        return render(request, "administration/users.html", users_context(errors=errors, form=request.POST))
    password = temporary_password()
    user = User(username=username, first_name=request.POST.get("first_name", "").strip(),
                last_name=request.POST.get("last_name", "").strip(), role=role)
    user.is_staff = user.is_superuser = role == Role.ADMINISTRATEUR
    user.set_password(password)
    user.save()
    return render(request, "administration/users.html", users_context(credentials=(user, password)))


@require_POST
@role_required(Role.ADMINISTRATEUR)
@transaction.atomic
def user_update(request, pk):
    user = get_object_or_404(User.objects.select_for_update(), pk=pk)
    role = request.POST.get("role", user.role)
    active = "is_active" in request.POST          # case decochee : absente du formulaire
    loses_admin = user.role == Role.ADMINISTRATEUR and user.is_active and (role != Role.ADMINISTRATEUR or not active)
    if user == request.user and (not active or role != user.role):
        messages.error(request, "Vous ne pouvez pas modifier votre propre rôle ni désactiver votre compte.")
    elif loses_admin and active_admins() <= 1:
        messages.error(request, "Il doit rester au moins un administrateur actif.")
    elif role in Role.values:
        user.role, user.is_active = role, active
        user.is_staff = user.is_superuser = role == Role.ADMINISTRATEUR
        user.save(update_fields=["role", "is_active", "is_staff", "is_superuser"])
        messages.success(request, f"Compte « {user.username} » mis à jour.")
    return render(request, "administration/users.html", users_context())


@require_POST
@role_required(Role.ADMINISTRATEUR)
def user_reset(request, pk):
    user = get_object_or_404(User, pk=pk)
    password = temporary_password()
    user.set_password(password)
    user.save(update_fields=["password"])
    return render(request, "administration/users.html", users_context(credentials=(user, password), reset=True))


class PasswordChange(auth_views.PasswordChangeView):
    template_name = "registration/password_change.html"
    success_url = reverse_lazy("home")
    extra_context = {"page_title": "Mon mot de passe"}

    def form_valid(self, form):
        messages.success(self.request, "Mot de passe modifié.")
        return super().form_valid(form)
