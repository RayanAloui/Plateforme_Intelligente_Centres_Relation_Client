# Modèle de données de l'application

Deux familles de tables cohabitent dans la même base PostgreSQL :

- **le moteur** (schémas `raw`, `core`, `ref`) : historique, calendrier, événements, paramètres ;
- **l'application** (schéma `app`) : ce que la plateforme a prévu, recommandé, décidé.

Les tables du moteur sont lues par Django sans être gérées par lui. Les paramètres
(`ref.cost_parameters`) sont modifiables depuis l'interface et relus par le moteur :
une seule source de vérité.

```mermaid
erDiagram
    USER ||--o{ STAFFING_PLAN : "crée"
    USER ||--o{ DECISION : "prend"
    USER ||--o{ ALERT : "traite"
    USER ||--o{ CONVERSATION : "ouvre"
    USER ||--o{ PARAMETER_CHANGE : "modifie"

    MODEL_VERSION ||--o{ DAILY_FORECAST : "produit"
    PIPELINE_RUN ||--o{ DAILY_FORECAST : "génère"
    DAILY_FORECAST ||--|{ INTERVAL_FORECAST : "48 demi-heures"
    DAILY_FORECAST ||--o{ STAFFING_PLAN : "sert de base à"

    STAFFING_PLAN ||--|{ PLAN_INTERVAL : "besoin et couverture"
    STAFFING_PLAN ||--o{ SHIFT : "vacations"
    STAFFING_PLAN ||--o{ DECISION : "piste d'audit"
    STAFFING_PLAN ||--o{ ALERT : "déclenche"
    STAFFING_PLAN ||--o{ STAFFING_PLAN : "ajusté depuis"

    CONVERSATION ||--|{ MESSAGE : "contient"

    INTERVAL_METRIC }o--|| CALENDAR_SLOT : "ref.calendar"
    PARAMETER ||--o{ PARAMETER_CHANGE : "historique"

    STAFFING_PLAN {
        date date
        string kind "actuel, ia, recommande, ajuste, scenario"
        string status "brouillon, soumis, valide, publie, remplace"
        float cost_agents
        float expected_loss
        float var95
        float es95
        float max_undercap_probability
    }
    SHIFT {
        datetime start
        datetime end
        int agents
    }
    ALERT {
        int level "faible, moyen, eleve"
        string source "risque, anomalie"
        string status "nouvelle, prise_en_compte, resolue"
        int recommended_reinforcement
    }
```

## Cycle de vie d'un planning

```mermaid
stateDiagram-v2
    [*] --> Brouillon : création (moteur ou planificateur)
    Brouillon --> Soumis : soumettre (planificateur, manager)
    Soumis --> Brouillon : refuser, avec motif (manager)
    Soumis --> Validé : valider (manager)
    Validé --> Publié : publier (manager)
    Publié --> Remplacé : un autre planning est publié pour le même jour
```

Chaque transition est vérifiée (statut de départ, rôle de l'utilisateur) et enregistrée
dans `Decision`. La base interdit physiquement deux plannings publiés le même jour.
