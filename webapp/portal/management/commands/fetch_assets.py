"""Telecharge les bibliotheques front-end dans webapp/static/vendor (une seule fois).

    python webapp/manage.py fetch_assets

Les fichiers sont servis localement : l'application fonctionne sans Internet,
ce qui evite toute mauvaise surprise le jour de la soutenance.
"""
import io
import tarfile
import urllib.request
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

# (paquet npm, version, fichier dans l'archive, nom local)
ASSETS = [
    ("@tailwindcss/browser", "4.1.11", "package/dist/index.global.js", "tailwind.js"),
    ("htmx.org", "2.0.4", "package/dist/htmx.min.js", "htmx.min.js"),
    ("alpinejs", "3.14.8", "package/dist/cdn.min.js", "alpine.min.js"),
    ("plotly.js-dist-min", "2.35.2", "package/plotly.min.js", "plotly.min.js"),
    ("lucide", "0.468.0", "package/dist/umd/lucide.min.js", "lucide.min.js"),
]


def tarball_url(package: str, version: str) -> str:
    name = package.split("/")[-1]
    return f"https://registry.npmjs.org/{package}/-/{name}-{version}.tgz"


class Command(BaseCommand):
    help = "Telecharge les bibliotheques JavaScript dans static/vendor."

    def handle(self, *args, **options):
        target = Path(settings.BASE_DIR) / "static" / "vendor"
        target.mkdir(parents=True, exist_ok=True)
        for package, version, member, local in ASSETS:
            with urllib.request.urlopen(tarball_url(package, version), timeout=60) as response:
                archive = tarfile.open(fileobj=io.BytesIO(response.read()), mode="r:gz")
            (target / local).write_bytes(archive.extractfile(member).read())
            self.stdout.write(f"  {package}@{version:<8} -> static/vendor/{local}")
        self.stdout.write(self.style.SUCCESS("Bibliotheques front-end installees."))
