import os
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from accounts.models import Role, User

PASSWORD = os.environ.get("DEMO_PASSWORD", "Demo2024!")


class DemoUsersTests(TestCase):
    def test_one_account_per_role_and_idempotent(self):
        call_command("create_demo_users", stdout=StringIO())
        call_command("create_demo_users", stdout=StringIO())
        self.assertEqual(User.objects.count(), 3)
        self.assertEqual(User.objects.get(username="planificateur").role, Role.PLANIFICATEUR)
        admin = User.objects.get(username="admin")
        self.assertTrue(admin.is_superuser and admin.is_administrator)

    def test_administrator_has_every_role(self):
        admin = User(role=Role.ADMINISTRATEUR)
        manager = User(role=Role.MANAGER)
        self.assertTrue(admin.has_role(Role.MANAGER, Role.PLANIFICATEUR))
        self.assertFalse(manager.has_role(Role.ADMINISTRATEUR))
        self.assertEqual(User(first_name="Sarah", last_name="Benali").initials, "SB")


class AuthenticationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("create_demo_users", stdout=StringIO())

    def test_pages_require_login(self):
        response = self.client.get(reverse("home"))
        self.assertRedirects(response, f"{reverse('login')}?next=/")

    def test_login_then_logout(self):
        response = self.client.post(reverse("login"), {"username": "manager", "password": PASSWORD})
        self.assertRedirects(response, reverse("home"))
        response = self.client.post(reverse("logout"))
        self.assertRedirects(response, reverse("login"))

    def test_wrong_password_shows_error(self):
        response = self.client.post(reverse("login"), {"username": "manager", "password": "faux"})
        self.assertContains(response, "Identifiant ou mot de passe incorrect")
