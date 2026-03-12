Analyse le cadre narratif et le ton stylistique du roman.

Réponds UNIQUEMENT en JSON valide selon ce schéma exact :

```json
{
  "cadre_narratif": {
    "point_de_vue": "1re personne / 3e personne / omniscient / alterné",
    "narrateur": "string (description du/des narrateur(s))",
    "temps_narratif": "passé / présent / mixte",
    "alternance_pov": "bool",
    "personnages_pov": ["string"],
    "distance_narrative": "interne / externe / variable",
    "monologue_interieur": "bool",
    "style_indirect_libre": "bool"
  },
  "ton_style": {
    "niveau_langue": "soutenu / standard / familier / argotique / mixte",
    "ton": "string (description du ton général)",
    "style": "string (description du style d'écriture)",
    "longueur_phrases": "courte / moyenne / longue / variable",
    "rythme": "lent / modéré / rapide / variable",
    "repetitions_stylistiques": ["string"],
    "metaphores_recurrentes": ["string"],
    "figures_de_style": ["string"]
  }
}
```

TEXTE À ANALYSER :
{sample_text}
