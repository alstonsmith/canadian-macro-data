# Spec: Canadian public data explorer (working title)

Status: DRAFT for review. Source of truth once approved. Vision and research: `BRIEF.md`, `DATA_SOURCES.md`.

## Objective

A local, open-source Python app that fetches public Canadian government data, stores it locally, and produces sourced charts and short narratives. Alston reviews and approves outputs, then posts them by hand (e.g. Substack). Others can clone the repo and run the same pipeline themselves.

**Users**
- Author (Alston): runs the pipeline, reviews drafts, exports publish packages.
- Repo downloader: installs, runs with their own local setup, regenerates data and outputs.
- Readers: see only the exported charts and text, so sourcing, licence attribution and accuracy are held to a public-publication bar.

**Success** = the first slice (below) runs end to end: fetch, store, chart, number-checked narrative, human approval, export. A fresh clone reproduces it.

### Scope
- **Slice 1 (this spec's build target):** StatCan CPI (table 18-10-0004-01) + Bank of Canada policy interest rate.
- **Later phases** (same architecture, each gets a `/plan` extension; not specified in detail here): labour force 14-10-0287-01, GDP by industry 36-10-0434-01, population 17-10-0009-01; then Census Profile, IRCC, CER, Dept. of Finance; CMHC last (no official API; licence review required before any automation).
- **Out of scope:** health and climate data, user accounts, real-time data, predictive models, hosting or deployment, any automatic publishing.

Phase 0 (capability map) skipped: slice 1 is one pipeline. Revisit if later phases diverge from the shared pipeline.

## Assumptions (correct me)
1. Python 3.12+, macOS first; Linux should work.
2. The local machine is an Apple Silicon Mac with 16GB+ RAM (to confirm). The Ollama model name is a config setting, with the default chosen after testing.
3. Chart design follows the `dataviz` skill conventions (accessible colour, labels).
4. Narratives are English only in slice 1.
5. CPI series choice for slice 1: all-items, Canada, plus year-over-year % change computed from stored index values (computation shown in the export, not invented).

## Tech stack
| Concern | Choice |
|---|---|
| Language | Python 3.12+ |
| Web UI | FastAPI + Jinja2 templates + HTMX (local, server-rendered, no JS build) |
| Charts | matplotlib, exporting PNG + SVG |
| Clean storage | SQLite (stdlib `sqlite3`) |
| Raw storage | Files on disk, unchanged, git-ignored |
| HTTP | `httpx` with throttling, on-disk response cache, retry/backoff |
| Scheduler | APScheduler, in-app, daily check |
| Narrative model | Local, via Ollama HTTP API; no data leaves the machine |
| Tests | pytest; saved sample responses only, never live network |
| Lint/types | ruff, mypy |
| Packaging | `pyproject.toml`, `uv` |

All dependencies are subject to "Ask first" sign-off at plan time. Versions are pinned then, after checking each library's official docs.

## Commands (proposed; recorded in CLAUDE.md once the stack exists)
```
Install:   uv sync
Run app:   uv run uvicorn canadian_macro.web.app:app --reload
Refresh:   uv run python -m canadian_macro refresh [--source statcan|boc]
Narrate:   uv run python -m canadian_macro narrate <dataset-id>
Export:    uv run python -m canadian_macro export <dataset-id>
Test:      uv run pytest
Lint:      uv run ruff check . && uv run mypy src
```

## Project structure
```
src/canadian_macro/
  sources/        one module per source (statcan.py, boc.py): fetch + parse, no storage logic
  store/          SQLite schema, raw-file cache, migrations
  catalog.py      dataset registry: id, source, identifier, units, licence, attribution text
  charts/         matplotlib chart builders (PNG + SVG), alt text generation
  narrative/      prompt building, Ollama client, number checker, checklist
  export/         publish-package builder
  scheduler.py    daily refresh job; consults StatCan release schedule
  web/            FastAPI app, Jinja templates, HTMX partials
tests/
  fixtures/       saved sample responses (StatCan, BoC, Ollama)
  ...             mirrors src layout
data/             git-ignored: raw/ (unchanged downloads) and canadian_macro.sqlite
outputs/          committed publish packages: outputs/<dataset-id>/<YYYY-MM-DD>/
docs/             decisions, source notes
SPEC.md  tasks/plan.md  tasks/todo.md  BRIEF.md  DATA_SOURCES.md  CLAUDE.md  LICENSE (MIT, code)
```
Engine (`src/`, `tests/`, `docs/`) and results (`outputs/`) are separate top-level trees in one repo. Downloaders regenerate `data/`.

## Data model (approved 2026-11-12; further schema change needs sign-off per CLAUDE.md)
One SQLite file. SQLite has no schemas, so the two logical schemas are table-name prefixes: `core_` and `raw_data_`.

The dataset registry lives in code (`catalog.py`: id, source, source identifier such as `18-10-0004-01` or a BoC series id, title, units, scale factor, frequency, licence id, attribution text). There is no `dataset` table. `dataset_id` columns are plain text validated against the catalog in code.

**CORE schema**
- `core_data_fetch_log`: dataset id, fetched-at, raw file path, content hash, source release date.
- `core_data_raw_extracts`: dataset id, fetch id, series/coordinate, period, `value` (TEXT, exact decimal string, nullable), `value_num` (REAL, best-effort float parse of `value`, convenience for analysis only, NULL if unparsable; the number checker and exports use `value`, never `value_num`), status flag (e.g. suppressed, estimated, revised), `is_current`.
- `core_narrative`: dataset id, fetch id, text, model name, prompt hash, check result, checklist result, approval state, timestamps.

**RAW_DATA schema**
- One table per series, `raw_data_<dataset>__<series>`, built by parsing `core_data_raw_extracts`. Name is derived from the dataset id and series id, sanitised to `[a-z0-9_]`, with a short hash suffix when sanitising changed the name, so distinct series never share a table. Columns: extract id, fetch id, period, `value`, `value_num`, status, `is_current`.

**Revisions and `is_current`.** Rows are append-only: a revision inserts new rows under the new fetch and earlier values are kept. `is_current = 1` marks the row from the latest fetch (highest fetch id) for each (series, period) and `0` marks superseded rows. Flipping that flag on older rows is the only update ever made to an existing row; values are never overwritten.

Missing or suppressed values are stored as NULL with a status flag. They are never filled in or interpolated.

**Status values.** The status flag is one of a closed set (`Status` enum, stored as its lowercase string value; every row has one):
- `ok`: a normal reported value.
- `missing`: the source reported no value (null, absent, or empty string). Stored as NULL.
- `suppressed`: the source withheld the value (e.g. StatCan confidentiality). Stored as NULL.
- `estimated`: the source flags the value as an estimate.
- `revised`: the source flags the value as revised.

**Empty values are missing, not malformed.** A value that is null, absent from an observation, or an empty or whitespace-only string (`""`, `''`) is `value=None` with status `missing`. A non-empty value that is not a valid decimal (e.g. `"abc"`) is malformed and raises `ParseError`. Malformed means the response structure or a present value can't be trusted; missing means the source reported no value.

## Behaviour requirements

**Fetching**
- Official APIs and downloads only: StatCan WDS / full-table CSV, BoC Valet. No page scraping.
- Throttle, cache raw responses, back off on failure. StatCan limits are unconfirmed, so start conservative and confirm in the WDS user guide before the first live fetch.
- Raw downloads are saved unchanged under `data/raw/`; parsing writes only to SQLite.
- Daily scheduled check uses the StatCan release-schedule JSON to skip tables with no new release. BoC series are checked daily with caching.
- Scheduler only runs while the app/computer is on. On startup it catches up on missed checks. This limit is documented.

**Charts**
- PNG + SVG per chart. Every chart shows title, units, source, licence attribution line, and data release date. Text alternative (alt text + data table CSV) is exported with it.
- Accessible: colour contrast, no colour-only encoding, readable at Substack width.
- No wording implying government endorsement.

**Narratives**
- Generated by the local model from stored data only. Stored data and model output are untrusted.
- **Number check (blocking):** every number in the narrative must be extracted and matched to a stored value or a stated derivation from stored values (e.g. a YoY % computed by the app), within a defined rounding rule. Any unmatched number rejects the narrative. Rejected text is never shown as publishable.
- Fixed AI disclosure line on every narrative: drafted by a local language model, figures machine-checked against the data, reviewed by the author.
- Mandatory caveats the generator must include or the check appends: revisions where applicable; "scenario, not forecast" for energy projections (later phase).
- **Human approval gate:** nothing exports until the author approves via the UI after a checklist: (a) claims are supported by the chart, (b) no causal claims the data cannot show, (c) caveats present, (d) attribution correct. Rejections are logged.

**Web UI (local review and export console)**
- Browse datasets and fetch history, preview charts, view narrative drafts with number-check results highlighted, run the checklist, approve or reject, trigger export. Binds to localhost only.

**Export (publish package)**
`outputs/<dataset-id>/<YYYY-MM-DD>/` contains: chart PNG + SVG, alt text, data CSV of plotted values, `narrative.md` (with AI disclosure), `sources.md` (source, identifier, release date, licence statement, attribution), and a manifest with fetch id, model name, prompt hash and check results.
- Required attribution text per source: OGL-Canada statement where applicable, StatCan acknowledgement under the StatCan Open Licence, Bank of Canada terms (to be read in full; currently unverified).
- Export refuses if the narrative is unapproved or failed the number check.

## Code style
Type-hinted, small pure functions at the parse and check boundaries, no I/O in them. Example:

```python
@dataclass(frozen=True)
class Observation:
    dataset_id: str
    period: date
    value: Decimal | None   # None = missing/suppressed; never imputed
    status: Status          # ok | missing | suppressed | estimated | revised

def parse_valet_series(payload: dict, dataset: Dataset) -> list[Observation]:
    """Pure: raw Valet JSON -> observations. Raises ParseError on unexpected shape."""
```
Conventions: `snake_case`, ruff defaults, `Decimal` for stored values, explicit units on every dataset, errors raised rather than swallowed. To be refined after slice 1 and recorded in CLAUDE.md.

## Testing strategy
- pytest. Tests written before behaviour (CLAUDE.md).
- Unit: parsers (including suppressed/missing values, scale factors, revisions), derivations (YoY), number extractor and matcher, attribution builder.
- Integration: fetch -> store -> chart -> narrative -> check -> export, using saved fixtures and a fake Ollama client. No live services in the suite.
- Number-check adversarial tests: invented figures, off-by-rounding, wrong units, numbers embedded in prose ("a quarter", "doubled"), and prompt-injection text inside stored metadata.
- Chart tests: required attribution and release-date text present; SVG/PNG produced; alt text non-empty.
- Live smoke test: a separate manual command (not part of `pytest`) for confirming real endpoints.

## Boundaries
**Always**
- Cite source, licence statement and release date on every chart and narrative.
- Block narratives that fail the number check. Treat fetched data and model output as untrusted.
- Failing test first. Verify library/API usage against official docs.
- Keep raw data unchanged and separate from cleaned data.

**Ask first**
- New data sources or dependencies; changes to schema or storage format.
- Anything sending data to an external service (including any hosted LLM).
- Steps not reversible by `git revert`.
- Committing data (raw or cleaned) to the repo.

**Never**
- Invent, estimate or present unsourced figures.
- Scrape disallowed pages or ignore source terms; automate CMHC before licence review.
- Commit secrets. Weaken, skip or delete tests to pass a build.
- Publish or export unapproved or check-failed text.

## Success criteria (slice 1)
1. `uv run pytest` passes using fixtures only, with no network access.
2. `refresh` stores CPI and BoC policy rate; raw files kept unchanged; each fetch records source, identifier, release date, licence and units.
3. A re-fetch containing a revised value keeps both versions; the chart uses the latest and the manifest notes the revision.
4. Chart exports as PNG + SVG with source, licence line and release date visible, plus alt text and data CSV.
5. A narrative containing any number not traceable to stored data is rejected in tests, and the UI shows it as failed.
6. Export is impossible without passing the number check and the human approval step.
7. Export includes the AI disclosure and `sources.md`.
8. The scheduler runs a daily check, skips unchanged StatCan tables, and catches up after downtime.
9. A fresh clone follows the README and reproduces the outputs (given Ollama installed locally).

## Open questions
1. StatCan WDS request limits and the Bank of Canada terms of use are unconfirmed. Verify both before the first live fetch.
2. Hardware assumption (16GB+ Apple Silicon) and the default Ollama model are to be confirmed by testing.
3. Exact rounding and derivation rules for the number checker (e.g. 2.9 vs 3%, "about a third").
4. Whether outputs are committed on approval or manually by the author. Default: manual commit.
5. Whether the daily scheduler needs a separate `serve` mode or runs inside the web app process. Default: inside the web app.
6. CPI slice-1 series selection (all-items Canada only, or add a core measure).
