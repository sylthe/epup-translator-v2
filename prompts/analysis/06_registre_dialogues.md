Analyse le registre des dialogues et établis une table de traduction des expressions.

Réponds UNIQUEMENT en JSON valide selon ce schéma exact :

```json
{
  "registre_dialogues_complet": {
    "langage_familier": "bool",
    "vulgarite": "absente / légère / modérée / fréquente",
    "argot_type": "string (type d'argot : américain, professionnel, jeunes, etc.)",
    "interjections_courantes": ["string"],
    "table_traduction": {
      "yeah": "ouais",
      "damn": "merde",
      "shit": "putain / merde",
      "dude": "mec / gars",
      "babe": "bébé / mon cœur",
      "whatever": "peu importe / m'en fous",
      "holy crap": "bon sang / merde alors"
    },
    "expressions_contextuelles": [
      {
        "expression": "string",
        "contexte": "string",
        "traduction": "string",
        "notes": "string ou null"
      }
    ],
    "particularites_par_personnage": {
      "nom_personnage": ["expression spécifique"]
    }
  }
}
```

TEXTE À ANALYSER :
{sample_text}
