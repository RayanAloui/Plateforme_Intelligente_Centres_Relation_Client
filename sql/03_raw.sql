-- ---------------------------------------------------------------
-- Export ACD (distributeur d appels) : volumetrie, temps, satisfaction
-- Volontairement permissif : c est la couche a nettoyer
-- ---------------------------------------------------------------
CREATE TABLE raw.acd_export (
    id                  BIGSERIAL PRIMARY KEY,
    ts_text             TEXT,              -- timestamp en texte : formats et doublons possibles
    offered             NUMERIC,
    answered            NUMERIC,
    abandoned           NUMERIC,
    avg_wait_seconds    NUMERIC,
    avg_handle_seconds  NUMERIC,
    service_level_pct   NUMERIC,           -- en pourcentage (0-100)
    occupancy_pct       NUMERIC,           -- en pourcentage (0-100)
    csat_mean           NUMERIC,           -- vide si aucune reponse a l enquete
    csat_responses      NUMERIC,
    source_file         VARCHAR(80),
    ingested_at         TIMESTAMP NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------
-- Export WFM (gestion des effectifs)
-- ---------------------------------------------------------------
CREATE TABLE raw.wfm_roster (
    id                BIGSERIAL PRIMARY KEY,
    ts_text           TEXT,
    agents_scheduled  NUMERIC,
    agents_present    NUMERIC,
    agents_absent     NUMERIC,
    source_file       VARCHAR(80),
    ingested_at       TIMESTAMP NOT NULL DEFAULT now()
);

CREATE INDEX idx_acd_ingested  ON raw.acd_export (ingested_at);
CREATE INDEX idx_wfm_ingested  ON raw.wfm_roster (ingested_at);