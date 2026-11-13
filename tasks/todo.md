# Task ledger: slice 1

One commit per task. Tick when done. Failing test first. Fixtures only, no live network in tests.

## Phase 0: Gates
- [x] **T0 Source terms research** (XS, docs only)
  - Acceptance: `docs/sources.md` records StatCan WDS request limits and the Bank of Canada terms of use with URLs and read date; attribution text drafted.
  - Verify: manual read of the notes; any item still unconfirmed is marked unverified.
  - Files: `docs/sources.md`

## Phase 1: Foundation + first source
- [x] **T1 Scaffold and tooling** (S) *Ask first: lists dependencies for sign-off*
  - Acceptance: `pyproject.toml` with approved deps and pins; package skeleton; `pytest`, `ruff`, `mypy` run clean on an empty smoke test; `.gitignore` covers `data/`.
  - Verify: `uv sync && uv run pytest && uv run ruff check . && uv run mypy src`
  - Files: `pyproject.toml`, `src/canadian_macro/__init__.py`, `tests/test_smoke.py`, `.gitignore`
- [x] **T2 Catalog and schema** (M) *Ask first: schema*
  - Acceptance: dataset registry in code for CPI and BoC rate (id, source, identifier, units, scale, licence, attribution; no `dataset` table); SQLite CORE schema (`core_data_fetch_log`, `core_data_raw_extracts`, `core_narrative`) created idempotently; helper that idempotently creates a safe per-series `raw_data_*` table; `value_num` and `is_current` columns per SPEC data model. Populating them is T5/T10.
  - Verify: `uv run pytest tests/store tests/test_catalog.py`
  - Files: `catalog.py`, `store/schema.py`, `store/db.py`, 2 test files (`tests/test_catalog.py`, `tests/store/test_db.py`)
  - Depends: T1
- [x] **T3 Fetch client** (M)
  - Acceptance: throttled, cached on disk, retry with backoff; cache hit makes no network call; failures raise clear errors. Tested with a mock transport.
  - Verify: `uv run pytest tests/test_fetch_client.py`
  - Files: `sources/client.py`, `tests/test_fetch_client.py`
  - Depends: T1
- [x] **T4 BoC Valet parser** (S)
  - Acceptance: fixture of the policy-rate response parses to `Observation`s; adds the `Status` enum (`ok`, `missing`, `suppressed`, `estimated`, `revised`, per SPEC); null, absent and empty/whitespace-only string values become `value=None` with status `missing`; a non-empty non-decimal value or a malformed shape (non-dict payload, missing/invalid `observations`, unparseable date, absent series key) raises `ParseError`. One test per case.
  - Verify: `uv run pytest tests/sources/test_boc.py`
  - Files: `sources/boc.py`, `sources/types.py` (shared `Observation`, `Status`, `ParseError`), `tests/sources/test_boc.py`, `tests/fixtures/boc_policy_rate.json`
  - Depends: T2, T3
- [ ] **T5 Store + `refresh` for BoC** (M)
  - Acceptance: `refresh --source boc` saves the raw file unchanged, records a fetch (hash, time, release date), writes `core_data_raw_extracts` (with `value_num`) and builds the per-series `raw_data_*` tables, keeping `is_current` correct; re-running with identical data adds no duplicates.
  - Verify: `uv run pytest tests/store tests/test_cli_refresh.py`
  - Files: `store/ingest.py`, `__main__.py`, 2 test files
  - Depends: T4
- [ ] **Checkpoint A:** tests pass; BoC rate stored from fixtures; raw file byte-identical; review with human.

## Phase 2: Charts and export skeleton
- [ ] **T6 Line chart builder** (M)
  - Acceptance: PNG + SVG output; title, units, source, licence line, release date visible; no endorsement wording; alt text non-empty; colour-independent encoding.
  - Verify: `uv run pytest tests/charts`; open the files and check by eye.
  - Files: `charts/line.py`, `charts/alt_text.py`, tests
  - Depends: T5
- [ ] **T7 Export package without narrative** (M)
  - Acceptance: writes `outputs/<id>/<date>/` with chart files, alt text, data CSV, `sources.md`, manifest (fetch id, release date).
  - Verify: `uv run pytest tests/export`
  - Files: `export/package.py`, `export/sources_md.py`, tests
  - Depends: T6
- [ ] **Checkpoint B:** BoC chart package exports from fixtures; review with human.

## Phase 3: StatCan CPI
- [ ] **T8 StatCan CSV parser** (M)
  - Acceptance: fixture parse handles scale factor, status flags, suppressed/missing values (NULL, never imputed), units; selects the agreed CPI series.
  - Verify: `uv run pytest tests/sources/test_statcan.py`
  - Files: `sources/statcan.py`, test, fixture
  - Depends: T2
- [ ] **T9 StatCan fetch + release-schedule check** (M)
  - Acceptance: downloads the full-table CSV via the client; consults the release-schedule JSON to skip unchanged tables; raw zip stored unchanged. Fixtures only.
  - Verify: `uv run pytest tests/sources/test_statcan_fetch.py`
  - Files: `sources/statcan_fetch.py`, `sources/schedule.py`, test, fixtures
  - Depends: T3, T8, T5
- [ ] **T10 Revision handling** (M)
  - Acceptance: a second fetch with a changed value keeps both; "current" query returns the latest; manifest notes revisions.
  - Verify: `uv run pytest tests/store/test_revisions.py`
  - Files: `store/revisions.py`, `store/ingest.py`, test
  - Depends: T9
- [ ] **T11 YoY derivation** (S)
  - Acceptance: YoY % computed from stored index values, stored with a derivation label and inputs; missing months yield no value.
  - Verify: `uv run pytest tests/test_derive.py`
  - Files: `derive.py`, test
  - Depends: T10
- [ ] **Checkpoint C:** CPI and BoC both refresh, chart and export from fixtures; review with human.

## Phase 4: Narrative and checks
- [ ] **T12 Number extractor and matcher** (M)
  - Acceptance: extracts numbers, percents, and words like "doubled" or "a quarter" from text; matches to stored values or labelled derivations under written rounding rules; any miss returns a failure with the offending text. Rules recorded in `docs/`.
  - Verify: `uv run pytest tests/narrative/test_checker.py`
  - Files: `narrative/checker.py`, test, `docs/number-check-rules.md`
  - Depends: T11
- [ ] **T13 Adversarial checker tests** (S)
  - Acceptance: invented figures, wrong units, off-by-rounding, wrong period, and injected instructions in metadata all fail as expected.
  - Verify: `uv run pytest tests/narrative/test_checker_adversarial.py`
  - Files: test file, fixtures
  - Depends: T12
- [ ] **T14 Prompt builder + Ollama client** (M) *Ask first: sends data to a local service only*
  - Acceptance: stored data goes in as quoted untrusted data; model name from config; a fake client is used in tests; one manual smoke command runs against local Ollama and is not part of `pytest`.
  - Verify: `uv run pytest tests/narrative/test_prompt.py tests/narrative/test_client.py`
  - Files: `narrative/prompt.py`, `narrative/ollama.py`, tests
  - Depends: T1
- [ ] **T15 Narrative pipeline** (M)
  - Acceptance: generate -> check -> store with model name, prompt hash and result; failed text is stored as rejected and never marked publishable; AI disclosure line added; required caveats present.
  - Verify: `uv run pytest tests/narrative/test_pipeline.py`
  - Files: `narrative/pipeline.py`, test
  - Depends: T13, T14
- [ ] **T16 Approval gate in export** (S)
  - Acceptance: export raises on unapproved or check-failed narrative; checklist (4 items) must be recorded; rejections logged; export includes `narrative.md` and the manifest check results.
  - Verify: `uv run pytest tests/export/test_gate.py`
  - Files: `export/package.py`, `narrative/approval.py`, test
  - Depends: T7, T15
- [ ] **Checkpoint D:** full CLI flow works with a fake model; gate cannot be bypassed in tests; review with human.

## Phase 5: UI, scheduler, docs
- [ ] **T17 Web UI: review** (M)
  - Acceptance: localhost-only FastAPI app lists datasets and fetch history, shows chart preview and narrative with failed numbers highlighted.
  - Verify: `uv run pytest tests/web`; run the app and check by eye.
  - Files: `web/app.py`, 2 templates, tests
  - Depends: T16
- [ ] **T18 Web UI: approve and export** (M)
  - Acceptance: checklist form, approve/reject, export button calling the gated export; shows the output path.
  - Verify: `uv run pytest tests/web`; run through the flow once in a browser.
  - Files: `web/app.py`, templates, tests
  - Depends: T17
- [ ] **T19 Scheduler** (M)
  - Acceptance: daily job in the app process; skips unchanged StatCan tables; catches up after downtime; logs each run. Time is injected in tests.
  - Verify: `uv run pytest tests/test_scheduler.py`
  - Files: `scheduler.py`, `web/app.py`, test
  - Depends: T9
- [ ] **T20 Docs and repo hygiene** (S)
  - Acceptance: README (install, Ollama setup, run, limits), MIT `LICENSE`, CLAUDE.md commands and conventions filled in with the real values, SPEC status updated.
  - Verify: follow the README on a clean checkout.
  - Files: `README.md`, `LICENSE`, `CLAUDE.md`
  - Depends: T18, T19
- [ ] **Checkpoint E:** all SPEC success criteria 1-9 verified; ready for `/review`.
