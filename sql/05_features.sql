-- La table features.model_input est construite par le pipeline (Phase 1.4)
-- via pandas.to_sql, car le jeu de variables evoluera pendant la Phase 2.
-- Le schema est cree ici pour que la couche existe des l initialisation.

CREATE TABLE features.feature_catalog (
    feature_name  VARCHAR(60) PRIMARY KEY,
    family        VARCHAR(30) NOT NULL,   -- lag, rolling, calendar, cyclical, event
    description   TEXT,
    created_at    TIMESTAMP NOT NULL DEFAULT now()
);

COMMENT ON TABLE features.feature_catalog IS
    'Dictionnaire des variables explicatives : documente le feature engineering';