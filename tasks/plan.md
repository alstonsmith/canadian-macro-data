# Implementation Plan: Canadian public data explorer, slice 1

Source: `SPEC.md` (approved). Task ledger: `tasks/todo.md`. Scope: StatCan CPI 18-10-0004-01 + Bank of Canada policy rate, end to end. Later phases extend this plan in place.

## Overview
Build one thin vertical pipeline first (fetch -> store -> chart -> narrative -> number check -> approve -> export), starting with the Bank of Canada series because it is the simplest source. Then add StatCan CPI, the revision handling, the local-model narrative, the review UI and the scheduler. Each task leaves the repo working, with fixtures-only tests.

## Architecture decisions
- **Pure parsers, I/O at the edges.** `sources/*` parse into `Observation` objects with no storage, so they are testable from saved fixtures.
- **Fetch client with a shared cache and throttle** used by every source, so rate-limit behaviour is built once.
- **Revisions are append-only.** Each fetch inserts rows tied to a fetch id; the "current" value is a query, not an overwrite.
- **Number checker is a standalone module** with no dependency on the model. It is tested adversarially before the model is wired in.
- **Export gate is enforced in code, not in the UI.** The export function refuses unapproved or check-failed narratives.
- **Ollama behind a small client interface,** so tests use a fake and the model name is config.
- **Derived figures (YoY %) are computed by the app** and stored as labelled derivations, so the checker can match them.

## Dependency graph
```
scaffold -> catalog + schema -> fetch client -> BoC parser -> store -> chart -> export (no narrative)
                                         \-> StatCan parser -> store (+ revisions) -> YoY derivation
number checker -> narrative (Ollama) -> approval gate -> export (full) -> web UI -> scheduler -> README
```

## Task list
See `tasks/todo.md` for the ledger with acceptance criteria. Summary:

### Phase 0: Gates (before code)
- T0 Resolve source terms: confirm StatCan WDS limits and Bank of Canada terms of use (read-only research, notes in `docs/`).

### Phase 1: Foundation + first source
- T1 Scaffold project, tooling and CI-free test setup (needs dependency sign-off)
- T2 Dataset catalog and SQLite schema
- T3 HTTP fetch client: throttle, cache, backoff
- T4 BoC Valet parser and fetch for the policy rate
- T5 Store raw files and observations (BoC end to end via CLI `refresh`)
- Checkpoint A

### Phase 2: Charts and export skeleton
- T6 Line chart builder: PNG + SVG, attribution, release date, alt text
- T7 Publish package export without narrative (sources.md, CSV, manifest)
- Checkpoint B

### Phase 3: StatCan CPI
- T8 StatCan full-table CSV parser (scale factors, status flags, suppressed values)
- T9 StatCan fetch via WDS/CSV with release-schedule check
- T10 Revision handling: append-only, latest-vs-prior
- T11 YoY derivation stored as labelled series
- Checkpoint C

### Phase 4: Narrative and checks
- T12 Number extractor and matcher
- T13 Adversarial number-check tests and injection cases
- T14 Prompt builder and Ollama client (fake in tests)
- T15 Narrative pipeline: generate, check, store result, AI disclosure
- T16 Approval gate and checklist in the export path
- Checkpoint D

### Phase 5: UI, scheduler, docs
- T17 Web UI: dataset list, chart preview, narrative with check results
- T18 Web UI: checklist, approve/reject, export trigger
- T19 Scheduler: daily check with catch-up
- T20 README, licence, `.gitignore`, fill in CLAUDE.md commands and conventions
- Checkpoint E: success criteria 1-9 from SPEC

## Risks and mitigations
| Risk | Impact | Mitigation |
|---|---|---|
| StatCan WDS limits unknown | Med | T0 before any live fetch; conservative throttle default |
| BoC terms unread | Med | T0; attribution text finalised only after reading |
| Local model ignores numbers or invents them | High | Blocking number checker; human gate; checker tested before model wiring |
| Prompt injection via stored metadata | Med | Pass data as quoted data; adversarial tests in T13 |
| Number matching too strict or too loose | Med | Explicit rounding rules decided in T12; test both directions |
| Scheduler only runs while Mac is on | Low | Catch-up on startup; documented |
| 16GB model quality uncertain | Med | Model is config; manual smoke test in T14 |
| New dependencies need sign-off | Low | T1 lists them and pauses for approval |

## Parallelization
After T5, T6 and T8-T9 are independent. T12-T13 (checker) can run before or alongside Phase 3. Everything else is sequential.

## Open questions (from SPEC, to settle at the named task)
- Rounding and derivation rules for the checker (T12)
- CPI series selection: all-items Canada only, or add a core measure (T8)
- Where the scheduler runs (default: inside the web app, T19)
- Whether outputs are committed on approval or by hand (default: by hand, T18)
