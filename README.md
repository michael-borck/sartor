# Sartor

> *sartor (Latin): a tailor.*

Privacy-first résumé tailoring. Give Sartor your real experience and one
job advertisement; it selects, reorders and rewrites only what your
evidence supports, then renders a finished résumé in Markdown, HTML, PDF
and DOCX. Rendered bundles also include a pitch script for
[Narra](https://github.com/michael-borck/narra), a deck for
[SlideStream](https://github.com/michael-borck/slide-stream), and a
`manifest.json`.

Every claim in the output traces back to a source you supplied.
Unsupported claims are flagged, never quietly invented. No account, no
telemetry; bring your own model (any OpenAI-compatible endpoint —
including local Ollama — or Anthropic).

**Status:** 0.2.0 — M1 core loop (CLI: ingest → profile → target →
tailor → verify → report → render) plus M2: `modern`/`academic`
themes, pitch/deck handoffs, bundle manifest, and the local web UI
(`sartor serve`). Product definition in
[docs/BRIEF.md](docs/BRIEF.md), design in [docs/SPEC.md](docs/SPEC.md),
stories in [docs/STORIES.md](docs/STORIES.md).

```bash
pip install "sartor[all]"   # document ingest/render + schema validation + PDF
sartor init my-profile        # project folder + editable sartor.yaml
sartor doctor                 # check the configured provider   (S-002)
sartor ingest resume.pdf publications.md                        (S-003)
sartor profile build          # draft profile.json, then edit it (S-004)
sartor target add acme --file ad.txt                            (S-005)
sartor tailor acme && sartor verify acme && sartor render acme  (S-006…S-009)
sartor render acme --theme modern   # or academic; else theme: in sartor.yaml
sartor serve                        # web UI at http://127.0.0.1:5384/ (needs sartor[serve])
```

Development: `uv sync && uv run pytest && uv run ruff check .`
(On the exFAT Projects volume, point the env at the internal disk:
`UV_PROJECT_ENVIRONMENT="$HOME/Library/Application Support/uv/envs/sartor" uv sync`.)

MIT © Michael Borck.
MIT © Michael Borck.
