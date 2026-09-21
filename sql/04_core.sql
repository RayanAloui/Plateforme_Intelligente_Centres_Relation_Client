-- ---------------------------------------------------------------
-- Table centrale : un enregistrement par intervalle de 30 minutes
-- ---------------------------------------------------------------
CREATE TABLE core.interval_metrics (
    ts                  TIMESTAMP PRIMARY KEY REFERENCES ref.calendar(ts),

    -- Demande
    offered             INTEGER   NOT NULL,
    answered            INTEGER   NOT NULL,
    abandoned           INTEGER   NOT NULL,

    -- Temps
    avg_wait_seconds    NUMERIC(8,2)  NOT NULL,
    avg_handle_seconds  NUMERIC(8,2)  NOT NULL,

    -- Effectifs
    agents_scheduled    SMALLINT  NOT NULL,
    agents_present      SMALLINT  NOT NULL,
    agents_absent       SMALLINT  NOT NULL,

    -- KPI derives
    service_level       NUMERIC(5,4) NOT NULL,
    abandon_rate        NUMERIC(5,4) NOT NULL,
    occupancy           NUMERIC(5,4) NOT NULL,

    -- Satisfaction (agregee, potentiellement absente)
    csat_mean           NUMERIC(4,3),
    csat_responses      SMALLINT NOT NULL DEFAULT 0,

    -- Tracabilite qualite
    is_imputed          BOOLEAN NOT NULL DEFAULT FALSE,
    imputed_columns     TEXT[],

    CONSTRAINT chk_counts_positive  CHECK (offered >= 0 AND answered >= 0 AND abandoned >= 0),
    CONSTRAINT chk_flow_balance     CHECK (answered + abandoned <= offered),
    CONSTRAINT chk_times_positive   CHECK (avg_wait_seconds >= 0 AND avg_handle_seconds > 0),
    CONSTRAINT chk_agents           CHECK (agents_present >= 0 AND agents_scheduled >= agents_present),
    CONSTRAINT chk_ratios           CHECK (service_level BETWEEN 0 AND 1
                                       AND abandon_rate  BETWEEN 0 AND 1
                                       AND occupancy     BETWEEN 0 AND 1.5)
);

CREATE INDEX idx_metrics_imputed ON core.interval_metrics (is_imputed) WHERE is_imputed;

COMMENT ON COLUMN core.interval_metrics.imputed_columns IS
    'Colonnes reconstituees par le pipeline : indispensable pour ne pas fausser l evaluation';

-- ---------------------------------------------------------------
-- Journal d execution du pipeline
-- ---------------------------------------------------------------
CREATE TABLE core.etl_runs (
    run_id       BIGSERIAL PRIMARY KEY,
    step_name    VARCHAR(60) NOT NULL,
    started_at   TIMESTAMP   NOT NULL DEFAULT now(),
    finished_at  TIMESTAMP,
    rows_in      BIGINT,
    rows_out     BIGINT,
    status       VARCHAR(20) NOT NULL DEFAULT 'running',
    message      TEXT,
    CONSTRAINT chk_status CHECK (status IN ('running','success','failed'))
);