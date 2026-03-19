"""Builds prompts from Markdown template files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.models import AnalysisResult, TextNode

# ---------------------------------------------------------------------------
# Analysis section groups
# ---------------------------------------------------------------------------

ANALYSIS_SECTIONS: list[dict[str, Any]] = [
    {
        "name": "identification_et_structure",
        "sections": [1, 10],
        "prompt_file": "01_identification.md",
    },
    {
        "name": "cadre_narratif_et_style",
        "sections": [2, 3],
        "prompt_file": "02_cadre_narratif.md",
    },
    {
        "name": "personnages_et_relations",
        "sections": [4, 5, 6],
        "prompt_file": "04_personnages.md",
    },
    {
        "name": "linguistique",
        "sections": [7, 8, 11],
        "prompt_file": "07_glossaire.md",
    },
    {
        "name": "culture_themes_sensibilite",
        "sections": [9, 13, 14],
        "prompt_file": "09_references_culturelles.md",
    },
    {
        "name": "coherence_et_notes",
        "sections": [12, 15],
        "prompt_file": "12_coherence_stylistique.md",
    },
]


class PromptBuilder:
    """
    Loads Markdown prompt templates from disk and renders them.

    Expected layout:
        prompts_dir/
          analysis/01_identification.md ... 15_notes_traduction.md
          translation/system_prompt.md, chapter_prompt.md
    """

    def __init__(self, prompts_dir: str | Path) -> None:
        self._dir = Path(prompts_dir)
        self._cache: dict[str, str] = {}

    def _load(self, relative_path: str) -> str:
        if relative_path not in self._cache:
            full = self._dir / relative_path
            self._cache[relative_path] = full.read_text(encoding="utf-8")
        return self._cache[relative_path]

    @staticmethod
    def _render(template: str, **kwargs: Any) -> str:
        """Replace {key} placeholders without using str.format (avoids JSON brace conflicts)."""
        result = template
        for key, value in kwargs.items():
            result = result.replace("{" + key + "}", str(value))
        return result

    # ------------------------------------------------------------------
    # Analysis prompts
    # ------------------------------------------------------------------

    def build_analysis_prompt(
        self, section_name: str, sample_text: str
    ) -> tuple[str, str]:
        """
        Return (system_prompt, user_prompt) for the given analysis section name.

        section_name must match a 'name' field in ANALYSIS_SECTIONS.
        """
        section = next(
            (s for s in ANALYSIS_SECTIONS if s["name"] == section_name), None
        )
        if section is None:
            raise ValueError(f"Unknown analysis section: {section_name!r}")

        template = self._load(f"analysis/{section['prompt_file']}")
        user_prompt = self._render(template, sample_text=sample_text)
        system_prompt = (
            "Tu es un expert en analyse littéraire et en traductologie. "
            "Tu réponds UNIQUEMENT en JSON valide, sans aucun autre texte."
        )
        return system_prompt, user_prompt

    # ------------------------------------------------------------------
    # Translation prompts
    # ------------------------------------------------------------------

    def build_translation_system_prompt(self, analysis: AnalysisResult) -> str:
        """Return the system prompt with the full analysis JSON embedded."""
        template = self._load("translation/system_prompt.md")
        analysis_json = analysis.model_dump_json(indent=2)
        return self._render(template, analysis_json=analysis_json)

    def build_chapter_prompt(
        self,
        chapter_number: int,
        chapter_title: str,
        text_nodes: list[TextNode],
        *,
        pov_character: str = "inconnu",
        characters_in_chapter: str = "",
        previous_summary: str = "Début du roman.",
        segment_context: str = "",
    ) -> str:
        """Return the user prompt for one translation segment."""
        template = self._load("translation/chapter_prompt.md")

        nodes_payload = [
            {"index": i, "xpath": node.xpath, "html": node.inner_html}
            if node.inner_html is not None
            else {"index": i, "xpath": node.xpath, "text": node.original_text}
            for i, node in enumerate(text_nodes)
        ]
        text_nodes_json = json.dumps(nodes_payload, ensure_ascii=False, indent=2)

        return self._render(
            template,
            chapter_number=str(chapter_number),
            chapter_title=chapter_title,
            pov_character=pov_character,
            characters_in_chapter=characters_in_chapter or "non précisé",
            previous_summary=previous_summary,
            segment_context=segment_context or "Premier segment du chapitre.",
            node_count=str(len(text_nodes)),
            text_nodes_json=text_nodes_json,
        )
