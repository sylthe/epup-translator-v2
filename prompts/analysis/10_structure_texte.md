Analyse la structure formelle et typographique du texte.

Réponds UNIQUEMENT en JSON valide selon ce schéma exact :

```json
{
  "structure_formelle": {
    "organisation_chapitres": {
      "avec_titres": "bool",
      "avec_numeros": "bool",
      "avec_pov_indique": "bool",
      "avec_epigraphes": "bool"
    },
    "elements_paratextuels": {
      "dedicace": "bool",
      "avant_propos": "bool",
      "epilogue": "bool",
      "notes_auteur": "bool"
    },
    "formats_speciaux": {
      "sms_messages": {
        "present": "bool",
        "style_actuel": "string ou null",
        "recommandation_fr": "string ou null"
      },
      "emails": {
        "present": "bool",
        "recommandation_fr": "string ou null"
      },
      "journaux_intimes": {
        "present": "bool",
        "recommandation_fr": "string ou null"
      },
      "lettres": {
        "present": "bool",
        "formule_ouverture_en": "string ou null",
        "formule_ouverture_fr": "string ou null"
      },
      "listes": "bool",
      "flash_backs": "bool"
    },
    "typographie": {
      "italiques_pour": ["string"],
      "majuscules_pour": ["string"],
      "tirets_dialogues": "bool",
      "guillemets_style": "double / simple / tirets"
    }
  }
}
```

TEXTE À ANALYSER :
{sample_text}
