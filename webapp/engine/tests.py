from datetime import datetime

from django.db import connection
from django.test import TestCase

from engine.catalog import CATALOG
from engine.models import IntervalMetric, Parameter


class EngineTablesTests(TestCase):
    def test_every_catalog_parameter_is_seeded(self):
        names = set(Parameter.objects.values_list("param_name", flat=True))
        self.assertTrue(set(CATALOG) <= names)

    def test_defaults_respect_their_bounds(self):
        for name, spec in CATALOG.items():
            self.assertTrue(spec.minimum <= spec.default <= spec.maximum, name)
        self.assertLess(CATALOG["alert_medium_threshold"].default, CATALOG["alert_high_threshold"].default)

    def test_engine_tables_are_readable_through_django(self):
        ts = datetime(2025, 1, 6, 10)
        with connection.cursor() as cur:
            cur.execute("INSERT INTO ref.calendar VALUES (%s, %s, 2025, 1, 2, 0, 'Lundi', 10, 0, 20, "
                        "false, false, NULL, false, 'Hiver')", [ts, ts.date()])
            cur.execute("INSERT INTO core.interval_metrics VALUES (%s, 200, 190, 10, 12.5, 290, 40, 38, 2, "
                        "0.88, 0.05, 0.8, 4.2, 15, false, NULL)", [ts])
        row = IntervalMetric.objects.get(ts=ts)
        self.assertEqual(row.offered, 200)
        self.assertEqual(row.answered + row.abandoned, row.offered)
