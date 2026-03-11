# epub-translator

A Python CLI application that translates English `.epub` novels to French using Claude AI (claude-sonnet-4-20250514).

## Overview

This application implements a professional translator workflow:
1. **Extract** — parse the ePub and isolate text nodes
2. **Analyse** — build a comprehensive literary analysis (6 API calls)
3. **Translate** — translate chapter by chapter using the analysis as context
4. **Reconstruct** — reinject translations and rebuild the ePub

> Work in progress — see branches for feature development.
