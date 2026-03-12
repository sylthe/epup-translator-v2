Identifie et analyse les références culturelles et propose des stratégies de traduction.

Réponds UNIQUEMENT en JSON valide selon ce schéma exact :

```json
{
  "references_culturelles": [
    {
      "element": "string",
      "type": "fête / institution / lieu / personnalité / œuvre / système scolaire / sport / nourriture / autre",
      "contexte": "string",
      "decision": "conserver / adapter / expliquer / supprimer",
      "traduction_ou_adaptation": "string ou null",
      "note": "string ou null"
    }
  ],
  "references_geographiques": [
    {
      "lieu": "string",
      "decision": "conserver / traduire",
      "forme_fr": "string ou null"
    }
  ],
  "marques_et_produits": [
    {
      "marque": "string",
      "decision": "conserver / adapter",
      "note": "string ou null"
    }
  ]
}
```

TEXTE À ANALYSER :
{sample_text}
