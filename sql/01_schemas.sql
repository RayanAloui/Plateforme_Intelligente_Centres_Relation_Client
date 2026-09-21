-- Couches de la plateforme
CREATE SCHEMA IF NOT EXISTS ref;
CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS features;

COMMENT ON SCHEMA ref      IS 'Donnees de reference : calendrier, evenements, parametres economiques';
COMMENT ON SCHEMA raw      IS 'Donnees brutes telles que collectees, imperfections incluses';
COMMENT ON SCHEMA core     IS 'Donnees nettoyees et validees, un enregistrement par intervalle';
COMMENT ON SCHEMA features IS 'Donnees preparees pour la modelisation';