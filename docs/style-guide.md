# PyPNM Documentation Style Guide

Guidelines for keeping the docs readable on GitHub and www.pypnm.io.

## Headings

- Use sentence case (`## System configuration menu`, not `## System Configuration Menu`).
- Prefer short titles that describe the task or reference (for example, “Configure SNMP defaults”).
- Keep heading hierarchy shallow; avoid skipping levels.

## Voice And Tone

- Default to second-person imperative for task guides (“Run `config-menu` to…”).
- Use a concise reference tone when documenting APIs or schemas.
- Highlight critical context with GitHub-flavored admonitions (`> **Note:** …`) until MkDocs callouts return.

## Linking And Navigation

- Start each page with a one-sentence summary and, when useful, a short list of “When to use / Prerequisites / Next steps”.
- Link to related guides under a “See also” or “Next steps” block instead of duplicating full tables of contents.
- Prefer relative links (for example, `../system/menu.md`) so GitHub and the website share the same paths.

## Lists And Code

- Use unordered lists for concepts and ordered lists for procedures.
- Include fenced code blocks with language hints (` ```bash `) and keep samples copy-paste ready.
- Add brief comments only when code is non-obvious.

## Terminology

- Stick to PyPNM-specific names (for example, “PNM file retrieval setup helper”).
- Expand acronyms on first use within a page, even if they appear elsewhere in the docs.

Following these conventions keeps the prose consistent whether someone reads it on GitHub or through the future www.pypnm.io landing page.
