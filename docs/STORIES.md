# Sartor — Stories

Built from [BRIEF.md](BRIEF.md) and [SPEC.md](SPEC.md). Terms are defined
once in [GLOSSARY.md](GLOSSARY.md); stories use only those names.

Check tags: `[unit]` unit test, `[self]` CLI integration test in a temp
project (fake provider, no network), `[snap]` golden-file snapshot of a
rendered output, `[manual]` a person must try it. M1 is CLI-only, so
`Screens:` names golden outputs instead of window snapshots.

## Decided (2026-11-22)

- PDF via **WeasyPrint** from the HTML output (one template, no divergence).
- Verifier **keeps-and-flags** by default; `--strict` drops unsupported bullets.
- Profile **edited by hand** as JSON/YAML in M1; review UI waits for `serve`.
- Wording is **"resume"** (US spelling, no accents in CLI output); a
  theme-level `locale` setting may localise document headings later.

## M1 Core loop: ingest → distil → tailor → verify → render

The one thing Sartor is for, end to end, from the terminal. A person can
apply for a real job with M1 alone.

### S-001 Create a project with `sartor init`
As an applicant, I run `sartor init my-profile` and get a project folder
I own, with config I can edit.
Screens: none (CLI)
Acceptance:
- [self] `init` creates the folder with `sartor.yaml` (provider unset),
  `sources/`, `exports/`, and no `profile.json` yet.
- [self] Re-running `init` on an existing project fails with
  "Already a Sartor project: <path>" and exit code 2; nothing is overwritten.
- [unit] Config resolves in order: `./sartor.yaml`, then `~/.sartor.yaml`;
  keys are read only from `${ENV_VAR}` references.
- [unit] A config naming any provider other than `openai-compatible` or
  `anthropic` is rejected, naming the two allowed values.
Status: done
UX:
- Flow: `sartor init DIR` -> files written -> prints next step ("Add sources: sartor ingest FILE…"). Ctrl-C leaves nothing half-written.
- Surface: terminal command (no interactive prompts in M1).
- States: empty dir name -> "Give the project a folder: sartor init DIR"; done -> 3-line summary of what was created.
- Words: "project" for the folder, never "workspace" or "vault".
- Access: plain text output; meaning never carried by colour alone.

### S-002 Check the provider with `sartor doctor`
As an applicant, I run `sartor doctor` before any generation and learn
whether my model is reachable and what it is called.
Screens: none (CLI)
Depends: S-001
Acceptance:
- [self] Against a fake OpenAI-compatible server, `doctor` prints
  provider, base URL, model list, and "ok", exit code 0.
- [self] `openai-compatible` at `http://localhost:11434/v1` works with
  no API key configured (the Ollama case).
- [self] Unreachable host, bad key, and missing model each produce a
  distinct one-line error naming the fix, exit code 1.
- [unit] `anthropic` with no key reports the missing env var by name,
  without printing any key value.
Status: done
UX:
- Flow: `sartor doctor` -> one line per check -> final "ok" or first failure. No way back needed; it changes nothing.
- Surface: terminal command.
- States: loading >0.5s shows "Checking <provider> at <base_url>…"; error inline as the failing check's line.
- Words: errors say what happened and the fix ("Cannot reach http://localhost:11434/v1 — is Ollama running?").
- Access: exit code carries pass/fail for scripts; text repeats it.

### S-003 Ingest sources with `sartor ingest`
As an applicant, I run `sartor ingest resume.pdf publications.md` and my
material becomes sources with stable spans I can point evidence at.
Screens: snapshots/ingest/sources.json
Depends: S-001
Acceptance:
- [self] PDF, DOCX, HTML, MD, TXT each ingest to `sources/<name>.json`
  with extracted text split into spans `src://<file>#s<N>`.
- [unit] Span ids are stable: re-ingesting an unchanged file produces
  byte-identical `sources/<name>.json`.
- [self] A JSON Resume file ingests losslessly and is marked usable as
  a profile directly (see S-004).
- [self] An unreadable or unsupported file names the file and the
  supported extensions, exit code 1; other files in the same run still ingest.
- [unit] Originals are never modified; extracted text lives in the project.
Status: done
UX:
- Flow: `sartor ingest FILE…` -> one line per file ("resume.pdf: 42 spans") -> summary. Re-running is the way back; it is idempotent.
- Surface: terminal command.
- States: empty `sources/` is fine; nothing-to-ingest prints "No files given: sartor ingest FILE…".
- Words: "source" and "span" only; never "chunk" or "document" for these.
- Access: counts and file names in text, not colour or icons alone.

### S-004 Distil the profile with `sartor profile build`
As an applicant, I run `sartor profile build` and get a draft
`profile.json` (JSON Resume) that I then correct by hand; it is the
truth for every later run.
Screens: snapshots/profile/profile.json
Depends: S-002, S-003
Acceptance:
- [self] With the fake provider, `profile build` writes valid JSON
  Resume (basics, work, education, skills, projects, publications).
- [unit] The output validates against the JSON Resume schema bundled
  in the package; invalid model output is reported, not written.
- [self] Every profile entry carries its source span ids, so S-007 can
  check claims without re-reading sources.
- [self] If `profile.json` exists, `build` refuses to overwrite it
  ("profile.json exists; move it aside or pass --force"), exit code 2.
- [self] `sartor profile check` validates a hand-edited profile and
  points at the first invalid field by path (`work[2].startDate`).
- [manual] A person can open the draft, fix a date, and `profile check` passes.
Status: todo
UX:
- Flow: `sartor profile build` -> progress per source -> "Wrote profile.json — review it, then: sartor profile check". Way back: the file is plain JSON; delete and rebuild.
- Surface: terminal command; editing happens in the person's own editor.
- States: no sources -> "No sources yet: sartor ingest FILE…"; model returns invalid JSON -> raw reply saved to `profile.draft.txt` for inspection, profile untouched.
- Words: "profile" for the file, "build" and "check" for the actions; never "generate" or "sync".
- Access: schema errors as `path: problem` lines, greppable.

### S-005 Parse a job ad with `sartor target add`
As an applicant, I save a job advertisement as a file (or paste it via
stdin) and Sartor extracts what the job asks for.
Screens: snapshots/target/target.json
Depends: S-002
Acceptance:
- [self] `sartor target add acme < ad.txt` (or `--file ad.txt`) writes
  `targets/acme.json`: title, organisation, must-haves, nice-to-haves,
  keywords, seniority, explicit selection criteria.
- [unit] Every extracted requirement keeps the verbatim ad sentence it
  came from, so the person can audit the parse.
- [self] Non-ad text (e.g. an empty file) fails with "No requirements
  found in <file>", exit code 1, and writes nothing.
- [unit] The raw ad text is stored beside the parse (`targets/acme.txt`).
Status: todo
UX:
- Flow: `sartor target add NAME --file ad.txt` -> counts ("12 must-haves, 4 nice-to-haves") -> next step ("Tailor: sartor tailor NAME"). Re-adding the same name overwrites only with --force.
- Surface: terminal command; stdin supported for pasting.
- States: duplicate name -> names the existing target and the --force fix.
- Words: "target" for a parsed ad, "must-have" / "nice-to-have" as written; never "JD" or "posting" in output.
- Access: requirements listed as text before any model summary.

### S-006 Tailor against a target with `sartor tailor`
As an applicant, I run `sartor tailor acme` and get a tailored resume
model that selects and rewrites only what my profile supports.
Screens: snapshots/tailor/tailored.json
Depends: S-004, S-005
Acceptance:
- [self] `tailor acme` writes `exports/acme/tailored.json`: a profile
  subset, ordered for the target, with rewritten bullets.
- [unit] Every bullet in `tailored.json` carries at least one evidence
  span id that exists in the profile or sources.
- [unit] No skill, employer, date, or number appears in the output that
  is absent from the profile (checked before S-007 even runs).
- [self] Entries irrelevant to the target are omitted, and the omission
  is listed in the run summary with counts per section.
- [self] Running `tailor` with no profile or unknown target name fails
  naming the missing piece and the command that creates it.
Status: todo
UX:
- Flow: `sartor tailor NAME` -> progress per section -> summary (kept/dropped counts) -> "Verify: sartor verify NAME". Re-running overwrites only that target's export folder.
- Surface: terminal command.
- States: profile fails `profile check` -> tailor stops and says so before any model call.
- Words: "tailor" (verb), "tailored resume" (the model); rewriting is "rephrase", never "enhance" or "improve".
- Access: kept/dropped counts in text; the full model is a readable JSON file.

### S-007 Verify every claim with `sartor verify`
As an applicant, I run `sartor verify acme` and learn, bullet by bullet,
what my evidence supports — before anyone else reads the resume.
Screens: snapshots/verify/report.txt
Depends: S-006
Acceptance:
- [unit] Deterministic checks run with no model: every bullet has
  evidence; dates, titles, and numbers in bullets appear in their cited
  spans; no unsupported skill names.
- [self] Each bullet is reported as `supported`, `weak`, or
  `unsupported`, with its span ids, in `exports/acme/verify.json` and
  as terminal text.
- [self] Default keeps-and-flags: unsupported bullets stay in
  `tailored.json` marked `"flagged": true`. With `--strict` they are
  removed, and the summary lists how many were dropped.
- [self] Exit code is 1 when any bullet is `unsupported` (flagged or
  dropped), 0 only when every bullet is `supported` or `weak`.
- [self] `--llm` adds an entailment pass (bullet follows from its spans);
  without it, verify makes no network call.
Status: todo
UX:
- Flow: `sartor verify NAME [--strict] [--llm]` -> per-bullet lines -> counts by verdict -> "Render: sartor render NAME". Non-destructive without --strict.
- Surface: terminal command.
- States: nothing tailored yet -> "Nothing to verify: sartor tailor NAME first".
- Words: verdicts are exactly "supported", "weak", "unsupported"; never scores or percentages for verdicts.
- Access: verdict is a word on every line, never colour alone; exit code mirrors the worst verdict.

### S-008 Report coverage and gaps with `sartor report`
As an applicant, I run `sartor report acme` and see which requirements
my resume evidences, which are gaps, and which ad keywords are missing.
Screens: snapshots/report/report.md
Depends: S-007
Acceptance:
- [self] `report acme` writes `exports/acme/report.md` and
  `coverage.json`: per requirement — evidenced (with bullet), weak, or gap.
- [snap] The ATS keyword table lists each target keyword with
  present/absent in the tailored resume.
- [unit] Gaps are phrased only as "add evidence or accept the gap";
  no wording suggests inventing experience (checked against a banned-phrase list).
- [self] Report numbers match `verify.json` counts for the same run.
Status: todo
UX:
- Flow: `sartor report NAME` -> writes files -> prints the three counts and the report path. Re-runnable after re-tailoring.
- Surface: terminal command; report is a Markdown file the person keeps.
- States: verify not run -> says so and runs the deterministic part first, telling the person it did.
- Words: "coverage" and "gap"; never "score" as a headline number.
- Access: Markdown tables read correctly as plain text.

### S-009 Render the export bundle with `sartor render`
As an applicant, I run `sartor render acme` and get finished files I can
submit: `resume.md`, `resume.html`, `resume.pdf`, `resume.docx`,
`resume.json` — all from the one tailored model, theme `ats-plain`.
Screens: snapshots/render/ats-plain/resume.md, resume.html
Depends: S-006 (verify/report outputs are included when present)
Acceptance:
- [snap] `resume.md` and `resume.html` match golden files for the seed
  profile: single column, real headings, no tables or text boxes (ATS-parseable).
- [self] `resume.pdf` is produced from the same HTML via WeasyPrint;
  text extracted from the PDF contains every bullet in `resume.md`.
- [self] `resume.docx` opens via python-docx round-trip with the same
  headings and bullets, in the same order.
- [unit] Flagged bullets (S-007, non-strict) render in `resume.md` with
  an HTML comment marker, and are plain text elsewhere; `--strict`
  exports contain none.
- [self] `resume.json` is the tailored model re-exported as valid
  JSON Resume (evidence fields under `meta.sartor`, schema still valid).
- [manual] A person opens the PDF and DOCX and can submit either as-is.
Status: todo
UX:
- Flow: `sartor render NAME` -> one line per file written -> "Bundle: exports/acme/". Re-rendering is safe and overwrites only rendered files.
- Surface: terminal command; documents carry the design, not the terminal.
- States: WeasyPrint missing -> renders MD/HTML/DOCX/JSON, then one error line naming the install fix; exit code 1.
- Words: "render" and "bundle"; theme named exactly `ats-plain`.
- Access: HTML uses semantic headings and list markup; PDF text is selectable, never an image.

## Seed data

`examples/jane-doe/` ships in the repo and drives every `[self]` and
`[snap]` check above:

- Sources: `resume.md`, `publications.txt`, one small PDF and DOCX with
  the same content (ingest parity), plus a complete `profile.json`.
- One target: `ad-acme.txt` with 12 must-haves, 4 nice-to-haves, and
  3 requirements Jane cannot evidence (gaps on purpose).
- One planted trap: the fake provider's tailor reply invents a metric
  ("cut costs by 30%") absent from all sources; S-007 must catch it.
- Fake provider: recorded replies keyed by prompt hash, so tests need
  no network and no real key. Every seed attribute (skills, dates,
  metrics) is settable by hand-editing `profile.json` (S-004).

## Later

- M2: `sartor serve` web UI; `modern` and `academic` themes; handoffs
  `pitch.md` (Narra) and `deck.md` (SlideStream); `manifest.json`.
- M3: SFIA / O*NET / ESCO mapping (user-supplied data only); opt-in
  web-search grounding with derived queries only.
- M4: Tauri desktop shell over `serve`; signed installers.
- Job-ad URL fetching; selection-criteria response documents.

## Dropped

- PPTX, Reveal.js, podcast, and video rendering — handoff files only.
- Cover letters — Career Compass already drafts those.
- Job-board scraping, auto-apply, LinkedIn import.
- Accounts, sync, telemetry, hosted anything.
- Bundling SFIA data — licence-restricted; user supplies it.
- A second document model beside JSON Resume.
