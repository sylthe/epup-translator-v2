Analyse en détail les relations entre personnages et leur évolution narrative.

Réponds UNIQUEMENT en JSON valide selon ce schéma exact :

```json
{
  "relations_detaillees": [
    {
      "personnages": ["Nom A", "Nom B"],
      "type_relation": "romantique / familial / amical / professionnel / conflictuel",
      "dynamique": "string (description de la dynamique)",
      "evolution": "string (comment la relation évolue au fil du récit)",
      "marqueurs_linguistiques": {
        "registre": "tu / vous",
        "transition_registre": "string ou null",
        "termes_affectifs": ["string"],
        "surnoms": ["string"],
        "patterns_de_langage": ["string"]
      },
      "scenes_cles": ["description des scènes importantes pour la relation"]
    }
  ],
  "dynamiques_groupe": "string (interactions entre plusieurs personnages)"
}
```

TEXTE À ANALYSER :
{sample_text}
