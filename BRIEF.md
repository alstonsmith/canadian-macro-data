# Project brief: Canadian public data explorer (working title)

> Paste this into `/spec`. Items marked **[DECIDE]** are open; answer them during the spec interview. Items marked **[ASSUMED]** are my starting guesses. Full source research is in `DATA_SOURCES.md`.

## Vision

A local app that pulls publicly available Canadian government data (economic, demographic, and similar), stores it locally, and turns it into charts and short written narratives that explain what the data shows.

## Audience

Public or published. The output will be read by people outside the project, so the bar is higher on sourcing, licence compliance, accessibility and accuracy. **[DECIDE]** What "published" means here: only exported charts and written pieces (static files, images, a report), or a hosted website? The vision above is a local app, and hosting is currently out of scope.

- Alston response: "published" means Alston manually pushing information somewhere, e.g. to an external blog of a Substack. This means the data, visuals and narrative should be stored locally and packaged in a way that can be later posted. In fact, this entire project should be set up in such a way that the core mechanical building (the data collection, processing, analyzing, output generation) is tracked through GitHub and is made available for others to download and run themselves, with the actual output itself stored in the same repo but under a different folder structure starting at root.

## Data scope

**In scope (picked from `DATA_SOURCES.md`):** consumer prices, labour force, GDP by industry, population estimates, 2021 Census Profile, Bank of Canada rates and exchange rates, CMHC housing data, IRCC immigration data, Canada Energy Regulator energy data, Department of Finance fiscal data.

**Out of scope for now:** health data (Health Infobase), climate and weather data.

**[ASSUMED] Build order.** Ten datasets is too much for one pass, so build in phases, and start each phase with one end-to-end slice:

1. **First slice:** Consumer Price Index (StatCan 18-10-0004-01) plus one Bank of Canada series. Two access methods and two licences, no maps or large files.
2. **Next:** labour force (14-10-0287-01), GDP by industry (36-10-0434-01), population estimates (17-10-0009-01). These reuse the StatCan code path.
3. **Later:** Census Profile, IRCC, Canada Energy Regulator, Department of Finance, and CMHC. CMHC comes last: no official API was found, and its licence needs review before any automation.

## Data sourcing

- Prefer official APIs and bulk downloads over scraping pages: StatCan Web Data Service and full-table CSV, the Open Government portal API, and the Bank of Canada Valet API.
- StatCan request limits are unconfirmed, so throttle and cache from the start.
- Fetch politely: rate-limit requests, cache raw responses, back off on failures.
- **Refresh: scheduled.** Automatic pulls on a schedule, with the StatCan release-schedule JSON available to avoid pointless requests. **[DECIDE]** How often, and where it runs (a scheduler on my own computer only works while that computer is on).
- Keep raw downloads unchanged and separate from cleaned data.
- Record source, identifier, release date, licence and units for every dataset.
- Attribute correctly: Open Government Licence – Canada statement, StatCan acknowledgement, CMHC source line, Bank of Canada terms. Details are in `DATA_SOURCES.md`.

## Outputs

- **Visualizations:** **[DECIDE]** chart types and where they appear (a web page, notebook, or exported images).
- **Narratives:** LLM-written, with automated number checks. Every number in the text must come from stored data and be verified against it before anything is shown or published; text that fails the check is rejected, not shown. Stored data is passed to the model as untrusted input, and the model's output is treated as untrusted too. **[DECIDE]** Which model and provider, and whether published text is labelled as AI-generated. (I recommend labelling it, since the audience is public.)
- Energy projections are model scenarios, not forecasts of fact, and narratives must say so.

## Must-haves

- Every chart and narrative states its source, licence attribution and data release date. The wording must not imply that any government source endorses this project.
- Every number in a narrative matches the stored data, and this is covered by tests.
- Units, scale factors, revisions (GDP is revised often) and suppressed or missing values are handled explicitly, not silently.
- Charts are readable and accessible (contrast, labels, keyboard access if interactive).

## Must-nots

- No invented, estimated or unsourced figures.
- No scraping of pages that disallow it, and no ignoring a source's terms.
- No automating CMHC access until its licence has been reviewed.
- No secrets (API keys, tokens) committed to the repository, including the key for the narrative model.
- Nothing is published automatically without passing the number checks.

## Stack

Python backend with a simple web UI. **[DECIDE]** The specific libraries, how data is stored locally, and how charts are rendered.

## Out of scope for now

User accounts, real-time data, predictive models. Hosting or deployment is out of scope unless "published" is decided to mean a hosted site. **[ASSUMED]**

## Open questions to settle in the spec

1. What "published" means: exported files, or a hosted site?
2. Chart types and output format.
3. Which narrative model and provider, and whether published text is labelled as AI-generated.
4. Refresh frequency, and where the scheduler runs.
5. How I will judge that the narratives are good enough, beyond the automated number checks.
6. Storage for fetched data (file-based or a small database).

## Working method

Use the agent-skills flow: `/spec`, then `/plan`, then `/build`, one task at a time at first. Tests use saved sample responses, not the live network.