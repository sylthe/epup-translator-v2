Analyse les personnages, leurs relations et le registre des dialogues.

Réponds UNIQUEMENT en JSON valide selon ce schéma exact :

```json
{
  "personnages": [
    {
      "nom": "string",
      "genre": "string",
      "age": "string",
      "role_narratif": "protagoniste / antagoniste / secondaire / figurant",
      "personnalite": "string (description concise)",
      "style_parole": "string",
      "particularites_linguistiques": ["string"],
      "exemples_dialogue": [
        {"en": "citation originale", "fr_suggere": "traduction suggérée"}
      ]
    }
  ],
  "relations": [
    {
      "personnages": ["Nom A", "Nom B"],
      "relation": "string",
      "registre": "tu ou vous",
      "evolution_registre": "string ou null",
      "termes_affectifs": ["string"],
      "surnoms": ["string"]
    }
  ],
  "registre_dialogues": {
    "langage_familier": "bool",
    "niveau_argot": "léger / modéré / fréquent",
    "type_humour": "string",
    "frequence_interjections": "rares / occasionnelles / fréquentes",
    "table_traduction_expressions": {
      "expression_en": "traduction_fr"
    }
  }
}
```

TEXTE À ANALYSER :
{sample_text}
