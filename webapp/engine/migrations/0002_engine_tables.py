"""Garantit l'existence des tables du moteur et initialise les parametres de la plateforme.

En exploitation, ces tables sont deja creees par les scripts sql/ : chaque instruction est
idempotente (IF NOT EXISTS, ON CONFLICT DO NOTHING) et ne modifie rien d'existant.
Dans la base de test de Django, elles sont creees a vide : les tests peuvent les utiliser.
Aucune instruction inverse : une migration arriere ne supprime jamais les donnees du moteur.
"""
from django.db import migrations

from engine.catalog import seed_rows

TABLES = """
CREATE SCHEMA IF NOT EXISTS ref;
CREATE SCHEMA IF NOT EXISTS core;
CREATE TABLE IF NOT EXISTS ref.calendar (
    ts TIMESTAMP PRIMARY KEY, date DATE NOT NULL, year SMALLINT NOT NULL, month SMALLINT NOT NULL,
    week_iso SMALLINT NOT NULL, day_of_week SMALLINT NOT NULL, day_name VARCHAR(10) NOT NULL,
    hour SMALLINT NOT NULL, minute SMALLINT NOT NULL, period_index SMALLINT NOT NULL,
    is_weekend BOOLEAN NOT NULL, is_holiday BOOLEAN NOT NULL, holiday_name VARCHAR(80),
    is_school_holiday BOOLEAN NOT NULL, season VARCHAR(10) NOT NULL);
CREATE TABLE IF NOT EXISTS ref.events (
    event_id SERIAL PRIMARY KEY, start_ts TIMESTAMP NOT NULL, end_ts TIMESTAMP NOT NULL,
    event_type VARCHAR(40) NOT NULL, intensity NUMERIC(5,2) NOT NULL DEFAULT 1.0, description TEXT);
CREATE TABLE IF NOT EXISTS ref.cost_parameters (
    param_name VARCHAR(50) PRIMARY KEY, value NUMERIC(12,4) NOT NULL, unit VARCHAR(30) NOT NULL,
    source TEXT, updated_at TIMESTAMP NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS core.interval_metrics (
    ts TIMESTAMP PRIMARY KEY REFERENCES ref.calendar(ts),
    offered INTEGER NOT NULL, answered INTEGER NOT NULL, abandoned INTEGER NOT NULL,
    avg_wait_seconds NUMERIC(8,2) NOT NULL, avg_handle_seconds NUMERIC(8,2) NOT NULL,
    agents_scheduled SMALLINT NOT NULL, agents_present SMALLINT NOT NULL, agents_absent SMALLINT NOT NULL,
    service_level NUMERIC(5,4) NOT NULL, abandon_rate NUMERIC(5,4) NOT NULL, occupancy NUMERIC(5,4) NOT NULL,
    csat_mean NUMERIC(4,3), csat_responses SMALLINT NOT NULL DEFAULT 0,
    is_imputed BOOLEAN NOT NULL DEFAULT FALSE, imputed_columns TEXT[]);
"""


def seed_parameters(apps, schema_editor):
    with schema_editor.connection.cursor() as cur:
        for name, value, unit, source in seed_rows():
            cur.execute("INSERT INTO ref.cost_parameters (param_name, value, unit, source) "
                        "VALUES (%s, %s, %s, %s) ON CONFLICT (param_name) DO NOTHING",
                        [name, value, unit, source])


class Migration(migrations.Migration):
    dependencies = [("engine", "0001_initial")]
    operations = [
        migrations.RunSQL(TABLES, reverse_sql=migrations.RunSQL.noop),
        migrations.RunPython(seed_parameters, migrations.RunPython.noop),
    ]
