-- ---------------------------------------------------------------
-- Calendrier : epine dorsale temporelle, un enregistrement par intervalle
-- ---------------------------------------------------------------
CREATE TABLE ref.calendar (
    ts                 TIMESTAMP   PRIMARY KEY,
    date               DATE        NOT NULL,
    year               SMALLINT    NOT NULL,
    month              SMALLINT    NOT NULL,
    week_iso           SMALLINT    NOT NULL,
    day_of_week        SMALLINT    NOT NULL,   -- 0 = lundi
    day_name           VARCHAR(10) NOT NULL,
    hour               SMALLINT    NOT NULL,
    minute             SMALLINT    NOT NULL,
    period_index       SMALLINT    NOT NULL,   -- 0..47
    is_weekend         BOOLEAN     NOT NULL,
    is_holiday         BOOLEAN     NOT NULL,
    holiday_name       VARCHAR(80),
    is_school_holiday  BOOLEAN     NOT NULL,
    season             VARCHAR(10) NOT NULL
);

CREATE INDEX idx_calendar_date ON ref.calendar (date);

COMMENT ON TABLE ref.calendar IS
    'Grille temporelle continue en heure locale naive, 48 intervalles par jour';

-- ---------------------------------------------------------------
-- Evenements exceptionnels influencant la demande
-- ---------------------------------------------------------------
CREATE TABLE ref.events (
    event_id      SERIAL      PRIMARY KEY,
    start_ts      TIMESTAMP   NOT NULL,
    end_ts        TIMESTAMP   NOT NULL,
    event_type    VARCHAR(40) NOT NULL,
    intensity     NUMERIC(5,2) NOT NULL DEFAULT 1.0,
    description   TEXT,
    CONSTRAINT chk_event_period    CHECK (end_ts > start_ts),
    CONSTRAINT chk_event_intensity CHECK (intensity > 0)
);

CREATE INDEX idx_events_period ON ref.events (start_ts, end_ts);

COMMENT ON COLUMN ref.events.intensity IS
    'Multiplicateur applique a l intensite d arrivee pendant l evenement';

-- ---------------------------------------------------------------
-- Parametres economiques : indispensables aux modules 10, 14, 15
-- ---------------------------------------------------------------
CREATE TABLE ref.cost_parameters (
    param_name   VARCHAR(50) PRIMARY KEY,
    value        NUMERIC(12,4) NOT NULL,
    unit         VARCHAR(30)   NOT NULL,
    source       TEXT,
    updated_at   TIMESTAMP     NOT NULL DEFAULT now()
);

INSERT INTO ref.cost_parameters (param_name, value, unit, source) VALUES
  ('cost_agent_hour',        28.0000, 'EUR/heure',        'Provisoire - a justifier dans le memoire'),
  ('cost_wait_second',        0.0050, 'EUR/seconde',      'Provisoire - cout d opportunite'),
  ('cost_abandoned_call',    12.0000, 'EUR/appel',        'Provisoire - perte commerciale estimee'),
  ('sla_target_seconds',     20.0000, 'secondes',         'Standard sectoriel 80/20 adapte'),
  ('sla_target_ratio',        0.8500, 'ratio',            'Contrainte du module 18'),
  ('penalty_sla_breach',     50.0000, 'EUR/intervalle',   'Provisoire'),
  ('max_shift_hours',         8.0000, 'heures',           'Contrainte reglementaire'),
  ('agents_max_available',   60.0000, 'agents',           'Taille de l effectif simule');