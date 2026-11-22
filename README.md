# Sartor

> *sartor (Latin): a tailor.*

Privacy-first résumé tailoring. Give Sartor your real experience and one
job advertisement; it selects, reorders and rewrites only what your
evidence supports, then renders a finished résumé in Markdown, HTML, PDF
and DOCX. Pitch-script and deck handoffs for
[Narra](https://github.com/michael-borck/narra) and
[SlideStream](https://github.com/michael-borck/slide-stream) are M2.

Every claim in the output traces back to a source you supplied.
Unsupported claims are flagged, never quietly invented. No account, no
telemetry; bring your own model (any OpenAI-compatible endpoint —
including local Ollama — or Anthropic).

**Status:** M1 core loop implemented (CLI: ingest → profile → target →
tailor → verify → report → render). Web UI, extra themes, and handoffs
are M2. Product definition in
[docs/BRIEF.md](docs/BRIEF.md), design in [docs/SPEC.md](docs/SPEC.md),
M1 stories in [docs/STORIES.md](docs/STORIES.md).

```bash
pip install "sartor[all]"   # document ingest/render + schema validation + PDF
sartor init my-profile        # project folder + editable sartor.yaml
sartor doctor                 # check the configured provider   (S-002)
sartor ingest resume.pdf publications.md                        (S-003)
sartor profile build          # draft profile.json, then edit it (S-004)
sartor target add acme --file ad.txt                            (S-005)
sartor tailor acme && sartor verify acme && sartor render acme  (S-006…S-009)
```

Development: `uv sync && uv run pytest && uv run ruff check .`
(On the exFAT Projects volume, point the env at the internal disk:
`UV_PROJECT_ENVIRONMENT="$HOME/Library/Application Support/uv/envs/sartor" uv sync`.)

MIT © Michael Borck.
