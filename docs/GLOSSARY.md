# Sartor — Glossary

Every noun and verb in CLI output, docs, and errors uses these names.

| Term | Means | Not |
| --- | --- | --- |
| project | The folder a person owns: config, sources, profile, targets, exports | workspace, vault, account |
| source | One ingested file (resume, publication list, transcript…), stored as extracted text | document, upload, input |
| span | One numbered chunk of a source's text; id `src://<file>#s<N>` | chunk, segment, snippet |
| profile | `profile.json`, the person's JSON Resume; the single source of truth | master CV, base resume |
| target | One parsed job advertisement under `targets/<name>.json` | JD, posting, job spec |
| must-have | A requirement the ad states as required | essential criteria, hard requirement |
| nice-to-have | A requirement the ad states as preferred | desirable, bonus |
| tailored resume | The model in `exports/<target>/tailored.json`: profile subset, rephrased for one target | output, result, generated CV |
| bullet | One highlight line in a work/project entry | point, achievement line |
| evidence | The span id(s) a bullet rests on | citation, proof, reference |
| supported | Verdict: the bullet's dates, titles, numbers, skills all appear in its evidence | verified, true, pass |
| weak | Verdict: evidence exists but only partly covers the bullet | partial, maybe |
| unsupported | Verdict: no evidence, or a fact appears in no cited span | fake, hallucinated, fail |
| flagged | An unsupported bullet kept in the model, marked for the person to decide | warned, quarantined |
| strict | Mode where unsupported bullets are dropped instead of flagged (`--strict`) | safe mode, paranoid |
| coverage | Per-requirement report: evidenced, weak, or gap | match score, fit |
| gap | A requirement with no supporting bullet; fixed by adding evidence or accepting it | weakness, missing skill |
| theme | Named document style; M1 ships only `ats-plain` | template, skin |
| bundle | The rendered files for one target in `exports/<target>/` | export package, output set |
| provider | The LLM backend: `openai-compatible` or `anthropic` (Ollama is the former at localhost) | vendor, engine, AI brain |
| framework | A user-supplied skill vocabulary (SFIA, O*NET, ESCO, AQF, custom) stored in `frameworks/<name>.json` | bundled data, taxonomy pack |
| framework skill | One coded entry in a framework: code, name, optional level/description/keywords | competency (unless the framework says so) |
| mapping | Per-code profile/target statuses and alignment for one target + framework | score, match grade |
| alignment | matched / target gap / profile only / neither, per framework code | fit |
| grounding | Opt-in web search whose results are cited context for a target | evidence, research proof |
| derived query | A search query built only from target fields (title, organisation, keywords) | resume query |

Verbs, one per action: `init`, `ingest`, `build`/`check` (profile),
`add` (target/framework), `tailor`, `verify`, `report`, `render`, `doctor`, `serve`, `map`, `research`.
Rewriting a bullet is "rephrase"; Sartor never "enhances" or "improves"
a claim.
