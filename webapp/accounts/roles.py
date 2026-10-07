"""Controle d'acces par role, pour les vues fonctions et les vues classes."""
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied


def role_required(*roles: str):
    """Decorateur : connexion obligatoire, puis role parmi `roles` (l'administrateur passe toujours)."""
    def decorator(view):
        @login_required
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not request.user.has_role(*roles):
                raise PermissionDenied
            return view(request, *args, **kwargs)
        return wrapped
    return decorator


class RoleRequiredMixin(LoginRequiredMixin):
    allowed_roles: tuple[str, ...] = ()

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and self.allowed_roles and not request.user.has_role(*self.allowed_roles):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)
