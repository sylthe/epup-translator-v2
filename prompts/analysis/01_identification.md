Analyse le texte suivant et fournis les informations d'identification et de structure du roman.

Réponds UNIQUEMENT en JSON valide selon ce schéma exact :

```json
{
  "identification": {
    "titre_original": "string",
    "auteur": "string",
    "annee_publication": "int ou null",
    "genre": "string",
    "sous_genre": "string",
    "public_cible": "string",
    "nb_chapitres": "int",
    "nb_mots_estime": "int"
  },
  "structure_texte": {
    "chapitres_titres": "bool",
    "presence_lettres": "bool",
    "presence_sms": "bool",
    "presence_journaux_intimes": "bool",
    "presence_extraits_livres": "bool",
    "formats_speciaux": ["description de chaque format spécial détecté"],
    "notes_adaptation_typographique": "string"
  }
}
```

TEXTE À ANALYSER :
{sample_text}
