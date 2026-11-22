# Sartor

> *sartor (Latin): a tailor.*

Privacy-first résumé tailoring. Give Sartor your real experience and one
job advertisement; it selects, reorders and rewrites only what your
evidence supports, then renders a finished résumé in Markdown, HTML, PDF
and DOCX — plus a pitch script for [Narra](https://github.com/michael-borck/narra)
and a deck for [SlideStream](https://github.com/michael-borck/slide-stream).

Every claim in the output traces back to a source you supplied.
Unsupported claims are flagged, never quietly invented. No account, no
telemetry; bring your own model (any OpenAI-compatible endpoint —
including local Ollama — or Anthropic).

**Status:** pre-code. Product definition in [docs/BRIEF.md](docs/BRIEF.md),
design in [docs/SPEC.md](docs/SPEC.md).

Planned interface:

```bash
pip install sartor
sartor init my-profile
sartor ingest resume.pdf publications.md
sartor tailor --job acme-ad.txt --theme ats-plain --out exports/acme/
sartor serve   # local web UI
```

MIT © Michael Borck.
