# Sartor — Specification (draft)

Status: draft, pre-code. The one-page product definition is
[BRIEF.md](BRIEF.md); this file records the design reasoning, pipeline
and phasing so implementation stories can be cut from it.

## One line

`sartor tailor profile/ --job ad.txt --theme ats-plain --out exports/acme/`
— a tailored résumé in MD, HTML, PDF and DOCX, a coverage report, and
handoff files for podcast and video, without your data leaving the
machine (unless you point it at a cloud LLM).

## Why a new app, not a Career Compass feature

Career Compass answers *which career, what gaps, what next* and is
deliberately session-only: nothing persists, export-don't-save. Tailoring
is the opposite shape: a durable master profile reused across many
applications, and a document-rendering engine (themes, PDF/DOCX fidelity,
ATS checks) that Compass has no reason to grow. Splitting keeps Compass a
teaching tool for students and Sartor a production tool for applicants.
The seam between them is a file: JSON Resume.

## Why Python, not Node

- Document I/O is the core workload: `pypdf`, `python-docx`,
  `python-pptx`, HTML→PDF (`weasyprint`), Markdown and templating are
  all mature in Python; Node equivalents exist but are thinner.
- The shipping pattern is already proven twice in this codebase family:
  Python core + Typer CLI + optional FastAPI `serve` + Tauri v2 sidecar
  desktop (Narra, SlideStream). Desktop therefore costs a copied shell,
  not a second codebase. Electron was considered and rejected: it would
  duplicate Compass's stack to gain nothing for document rendering.
- PyPI name `sartor` verified available 2026-11-22 (also npm and
  `github.com/michael-borck/sartor`). Alternatives, also verified free
  that day: `tailor-cv`, `bespoke-cv`, `vericv`, `refit-cv`.

## Providers (exactly two)

| Provider | Endpoint | Key |
|---|---|---|
| `openai-compatible` | any `/v1/chat/completions` (OpenAI, OpenRouter, Groq, LM Studio, …) | optional |
| `anthropic` | Anthropic Messages API | required |

Ollama is not a third provider: it is `openai-compatible` with
`base_url: http://localhost:11434/v1` and the key ignored. Config lives
in `~/.sartor.yaml` or `./sartor.yaml`, keys by `${ENV_VAR}` reference
only, never stored in the browser (Narra rule). A `sartor doctor`
command tests the connection and lists models before any generation.

## Inputs

- Existing résumé: PDF, DOCX, HTML, MD, TXT, or JSON Resume (lossless).
- Additional evidence: any number of the same formats — publication
  lists, project write-ups, transcripts, reference letters.
- Job target: pasted text, file, or (phase 2) a URL fetched and cleaned.
- Source material: style guides ("address these selection criteria"),
  framework extracts (e.g. user-supplied SFIA skill definitions).

## Pipeline

1. **Ingest** — extract text per file; assign stable span ids
   (`src://resume.pdf#s12`). Everything stays in the project folder.
2. **Distil** — LLM drafts a MasterProfile (JSON Resume) from the
   sources. The user reviews and edits it; this human-owned file is the
   truth for all later runs. Re-ingesting never silently overwrites it.
3. **Parse target** — LLM extracts a JobTarget: must-have skills,
   nice-to-haves, keywords, seniority, explicit criteria.
4. **Tailor** — select and order profile entries against the target;
   rewrite bullets for relevance and keyword match. Rewrites may
   rephrase, never add facts. Each generated bullet must cite the
   EvidenceLink(s) it rests on.
5. **Verify** — deterministic checks first (every bullet has evidence;
   dates, titles and numbers in the output appear in the sources; no
   skill named that no source supports), then an optional LLM
   entailment pass. Failures are reported per bullet: `supported`,
   `weak`, `unsupported → dropped/flagged`. This is the Winnow/CiteSight
   pattern applied to résumés, and it is the product's differentiator.
6. **Report** — coverage: which target requirements are evidenced,
   which are gaps (with "add evidence or accept the gap", never
   "invent something"), ATS keyword table.
7. **Render** — from the one TailoredResume model:
   - `resume.md`, `resume.html` (themed), `resume.pdf`
     (HTML + WeasyPrint, so HTML and PDF never diverge), `resume.docx`
     (python-docx), `resume.json` (JSON Resume).
   - Handoffs: `pitch.md` (first-person narrative script → Narra
     podcast), `deck.md` (one claim per slide → SlideStream PPTX/MP4).
   - `manifest.json`: inputs with hashes, provider/model, theme,
     verification results — a run is auditable and replayable.

## Frameworks and web search (phase 2)

- SFIA, O*NET, ESCO, AQF mapping of both profile and target, so skills
  share a vocabulary ("SFIA PROG level 4"). Career Compass's F6 notes
  apply. SFIA content is licence-restricted: user supplies it, or codes
  are looked up live; nothing is bundled or redistributed.
- Search grounding (company/role context, current terminology) follows
  the Study Buddy → Career Compass chain: DuckDuckGo default,
  Brave/Serper/SearXNG optional, automatic fallback. Only derived
  queries leave the device; résumé text never does.

## Interfaces

- Library: `from sartor import core` (Narra-style), all logic here.
- CLI: `init`, `ingest`, `profile`, `tailor`, `render`, `verify`,
  `doctor`, `serve`.
- Web UI (`serve`): upload → review profile → paste job → review
  tailoring with evidence flags inline → download bundle.
- Desktop: Tauri v2 shell + Python sidecar via `uv` (copied from
  Narra's `desktop/`), installers on `desktop-v*` tags.

## Phasing

- **M1** — core + CLI: ingest, distil, tailor, verify, MD/HTML/PDF/DOCX
  render, two providers, `doctor`. One theme (`ats-plain`).
- **M2** — `serve` web UI, remaining themes, handoff files, manifest.
- **M3** — framework mapping + search grounding (both opt-in).
- **M4** — Tauri desktop, signed installers, PyPI release polish.

## Decided (2026-11-22, before M1 stories)

- PDF engine: **WeasyPrint** from the HTML output.
- MasterProfile editing in CLI-only M1: **hand-edited** JSON/YAML;
  a review UI waits for `serve`.
- Verifier default: **keep-and-flag**; `--strict` drops unsupported bullets.
- Wording: **"resume"** (US spelling); localised document headings may
  become a theme-level `locale` setting later, not a fork.

M1 stories cut from this spec live in [STORIES.md](STORIES.md);
shared names in [GLOSSARY.md](GLOSSARY.md).
