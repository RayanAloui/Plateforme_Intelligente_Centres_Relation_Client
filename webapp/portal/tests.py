import os
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from portal.navigation import ITEMS

PASSWORD = os.environ.get("DEMO_PASSWORD", "Demo2024!")
ADMIN_PAGES = ("settings", "models", "users")


class PortalTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("create_demo_users", stdout=StringIO())

    def login(self, username):
        self.client.login(username=username, password=PASSWORD)

    def test_home_for_every_role(self):
        for username, name in (("manager", "Sarah"), ("planificateur", "Karim"), ("admin", "Ines")):
            self.login(username)
            response = self.client.get(reverse("home"))
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, name)

    def test_administration_is_reserved_to_administrators(self):
        self.login("manager")
        for page in ADMIN_PAGES:
            self.assertEqual(self.client.get(reverse(page)).status_code, 403)
        self.login("admin")
        for page in ADMIN_PAGES:
            self.assertEqual(self.client.get(reverse(page)).status_code, 200)

    def test_menu_hides_administration_for_other_roles(self):
        self.login("planificateur")
        self.assertNotContains(self.client.get(reverse("home")), "Administration")
        self.login("admin")
        self.assertContains(self.client.get(reverse("home")), "Administration")

    def test_every_page_of_the_menu_answers(self):
        self.login("admin")
        for name in ITEMS:
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)

    def test_upcoming_page_announces_its_step(self):
        self.login("manager")
        self.assertContains(self.client.get(reverse("assistant")), "étape G")
