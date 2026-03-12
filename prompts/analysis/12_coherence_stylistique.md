Identifie les expressions récurrentes et établis les règles de cohérence stylistique.

Réponds UNIQUEMENT en JSON valide selon ce schéma exact :

```json
{
  "coherence_stylistique": {
    "expressions_recurrentes": [
      {
        "en": "string",
        "fr": "string",
        "frequence": "élevée / moyenne / faible",
        "contexte": "string"
      }
    ],
    "metaphores_filees": [
      {
        "metaphore": "string",
        "occurrences": ["citation 1", "citation 2"],
        "traduction_coherente": "string"
      }
    ],
    "phrases_signature": [
      {
        "en": "string",
        "fr": "string",
        "personnage": "string ou null",
        "note": "string ou null"
      }
    ],
    "tics_linguistiques": [
      {
        "personnage": "string",
        "tic": "string",
        "traduction": "string"
      }
    ],
    "regles_cohérence": [
      "Règle de cohérence à respecter sur tout le texte"
    ]
  }
}
```

TEXTE À ANALYSER :
{sample_text}
