Établis le glossaire des termes techniques, jargon professionnel, et idiomes du roman.

Réponds UNIQUEMENT en JSON valide selon ce schéma exact :

```json
{
  "glossaire": {
    "termes_techniques": [
      {
        "en": "string",
        "fr": "string",
        "contexte": "string",
        "domaine": "string (médecine, pompier, juridique, etc.)"
      }
    ],
    "jargon_professionnel": [
      {
        "en": "string",
        "fr": "string",
        "contexte": "string"
      }
    ],
    "termes_recurrents": [
      {
        "en": "string",
        "fr": "string",
        "frequence": "élevée / moyenne / faible",
        "notes": "string ou null"
      }
    ]
  },
  "idiomes": [
    {
      "expression": "string",
      "sens_litteral": "string",
      "sens_idiomatique": "string",
      "traduction_fr": "string",
      "contexte": "string"
    }
  ],
  "contraintes_grammaticales": [
    {
      "type": "string (ambiguïté de genre, phrasal verb, etc.)",
      "exemple_en": "string",
      "strategie": "string",
      "exemple_fr": "string ou null"
    }
  ]
}
```

TEXTE À ANALYSER :
{sample_text}
