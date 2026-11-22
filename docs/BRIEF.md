# Sartor

Sartor (Latin: tailor) is a privacy-first tool that tailors your real
experience to one job advertisement and renders a finished résumé — every
claim traceable to evidence you supplied, nothing invented.

## Replaces

Hand-editing a Word résumé per application, and pasting a résumé plus a job
ad into a cloud chatbot that quietly embellishes it. It complements
Career Compass (exploration: *which* job?) by doing production
(*this* job, *this* document).

## Main jobs

1. Build a master profile from source material: an existing résumé
   (PDF, DOCX, HTML, MD, TXT), plus extra evidence — publications,
   projects, performance notes, framework documents.
2. Tailor to a target: paste or load a job description; Sartor selects,
   reorders and rewrites only supported material, reports keyword/skill
   coverage and gaps, and flags anything it cannot evidence.
3. Render and hand off: styled MD, HTML, PDF and DOCX from one canonical
   model, plus a pitch script for Narra and a Markdown deck for
   SlideStream.

## Data

- MasterProfile: canonical JSON Resume (basics, work, education, skills,
  projects, publications), human-editable, the single source of truth.
- Source: one ingested file, with extracted text and stable span ids.
- EvidenceLink: output bullet → source span(s) that support it.
- JobTarget: parsed advertisement (must-haves, nice-to-haves, keywords,
  framework skills).
- TailoredResume: a MasterProfile subset + rewrites + coverage report.
- Theme: named style (ats-plain, modern, academic) applied at render.
- ExportBundle: rendered files + `manifest.json` (provenance, model,
  inputs, timestamps).

## Shape

Python package first: `pip install sartor`, a `sartor` CLI, and
`sartor serve` (localhost web UI). Desktop is a Tauri v2 shell running
`sartor serve` as a sidecar — the proven Narra/SlideStream pattern, not a
new Electron app. Cross-platform (macOS, Windows, Linux). Local data in
a plain project folder the user owns. No accounts, no telemetry.

LLM providers — exactly two:

- OpenAI-compatible (`/v1/chat/completions`), key optional. Ollama is
  just this provider at `http://localhost:11434/v1`.
- Anthropic (native Messages API).

The only network egress is to the configured LLM, and (phase 2, opt-in)
to a search provider — search queries are derived terms only, never
résumé text (the Career Compass rule).

## System hooks

CLI. File-based handoffs out: `pitch.md` → Narra (podcast),
`deck.md` → SlideStream (PPTX, narrated video). JSON Resume in/out, so
Career Compass can consume a profile later. No direct app-to-app calls
in v1.

## Reference

Career Compass for privacy posture and provider UX; Narra and
SlideStream for packaging (core + CLI + serve + Tauri); Winnow and
CiteSight for claim-level provenance and verification.

## Look

Documents, not app chrome, carry the design: three résumé themes in v1
(`ats-plain` default — single column, parseable; `modern`; `academic`).
Web UI follows the calm, plain-language style of the Buddy apps.

## Not in version one

- PPTX, Reveal.js, podcast or video rendering (handoff files only).
- SFIA / O*NET / ESCO mapping and web-search grounding (phase 2; SFIA
  data is licence-restricted, so it is user-supplied or looked up,
  never bundled).
- Job-board scraping, auto-apply, LinkedIn import, accounts, sync,
  cover letters (Career Compass already drafts those).
- Inventing metrics, dates or skills. Unsupported claims are flagged
  or dropped — this is a feature, not a limitation.
