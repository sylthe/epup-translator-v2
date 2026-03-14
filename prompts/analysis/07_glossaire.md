Établis le glossaire des termes clés et des expressions idiomatiques du roman.

Réponds UNIQUEMENT en JSON valide selon ce schéma exact :

```json
{
  "glossaire": [
    {
      "en": "string (terme anglais)",
      "fr": "string (traduction française)",
      "contexte": "string (domaine ou usage : médecine, pompier, juridique, argot, etc.)"
    }
  ],
  "idiomes": [
    {
      "expression": "string (expression anglaise)",
      "sens": "string (sens idiomatique en français)",
      "traduction": "string (traduction française recommandée)"
    }
  ],
  "contraintes_grammaticales": [
    {
      "type": "string (ambiguïté de genre, phrasal verb, temps narratif, etc.)",
      "exemple_en": "string",
      "strategie": "string",
      "exemple_fr": "string ou null"
    }
  ]
}
```

TEXTE À ANALYSER :
{sample_text}
