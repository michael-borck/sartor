# Examples

`jane-doe/` is the seed project from docs/STORIES.md. It drives the
CLI integration tests and gives every story shared material:

- `resume.md`, `publications.txt` — Jane's sources.
- `resume.pdf`, `resume.docx` — the same resume content, for ingest
  parity checks across formats (S-003).
- `profile.json` — a complete JSON Resume for Jane (ingests as a
  profile candidate; S-004 builds one like it).
- `ad-acme.txt` — one job target: 12 must-haves, 4 nice-to-haves.
  Three must-haves (Kubernetes, Go, security clearance) are gaps Jane
  cannot evidence, on purpose (S-008).
- `sartor.yaml` — the default local config. Tests use a FakeProvider;
  no server is needed.

Try it: `cd examples/jane-doe && sartor ingest resume.pdf publications.txt`
(writes into `sources/`, which is generated output).
