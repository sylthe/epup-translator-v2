Identifie les contraintes grammaticales spécifiques à la traduction EN→FR.

Réponds UNIQUEMENT en JSON valide selon ce schéma exact :

```json
{
  "contraintes_grammaticales": [
    {
      "type": "string (ambiguïté de genre / pronom neutre / temps verbaux / etc.)",
      "description": "string",
      "exemples": [
        {
          "en": "string",
          "probleme": "string",
          "strategie": "string",
          "fr": "string"
        }
      ]
    }
  ],
  "pronoms_neutres": {
    "present": "bool",
    "personnages_concernes": ["string"],
    "strategie_choisie": "iel / reformulation / alternance / autre",
    "notes": "string ou null"
  },
  "temps_verbaux": {
    "predominant_en": "string",
    "recommandation_fr": "string",
    "exceptions": ["string"]
  },
  "accords_difficiles": [
    {
      "cas": "string",
      "strategie": "string"
    }
  ]
}
```

TEXTE À ANALYSER :
{sample_text}
