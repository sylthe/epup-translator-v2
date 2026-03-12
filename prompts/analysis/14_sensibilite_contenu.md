Analyse la sensibilité du contenu et les points d'attention pour la traduction.

Réponds UNIQUEMENT en JSON valide selon ce schéma exact :

```json
{
  "sensibilite_contenu": {
    "scenes_sexuelles": {
      "present": "bool",
      "niveau_explicite": "absent / suggestif / modéré / explicite",
      "recommandation": "string ou null"
    },
    "violence": {
      "present": "bool",
      "niveau": "absent / léger / modéré / intense",
      "recommandation": "string ou null"
    },
    "langage_offensant": {
      "present": "bool",
      "types": ["string"],
      "recommandation": "string ou null"
    },
    "themes_sensibles": [
      {
        "theme": "string",
        "traitement": "string",
        "recommandation": "string ou null"
      }
    ],
    "representation_identite": {
      "lgbtq": "bool",
      "ethnicite": "bool",
      "handicap": "bool",
      "notes": "string ou null"
    },
    "note_generale": "string"
  }
}
```

TEXTE À ANALYSER :
{sample_text}
