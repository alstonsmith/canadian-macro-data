# Project: Canadian public data explorer (working title)

Local app that fetches public Canadian government data, stores it, and produces charts and short sourced narratives. See `BRIEF.md` for the vision; `SPEC.md` is the source of truth once it exists.

## Workflow
- Follow the agent-skills flow: `/spec` → `/plan` → `/build` → `/review`.
- `SPEC.md` is the contract. If a decision or scope changes, update `SPEC.md` first, then re-run `/plan` to extend `tasks/plan.md` and `tasks/todo.md` in place. Do not rewrite completed tasks.
- `tasks/todo.md` is the task ledger. Tick tasks off as they finish, one commit per task.
- Before building, check that `SPEC.md` and `tasks/todo.md` still agree. If they don't, say so and stop.

## Tech stack
Python backend with a simple web UI. Specific libraries, storage and chart rendering to be decided in `/spec`. Update this section when they are.

## Commands
To be filled in once the stack exists. Record the exact commands here:
- Install dependencies: `TODO`
- Run the app: `TODO`
- Run tests: `TODO`
- Lint / type-check: `TODO`

## Data rules
- Prefer official APIs and bulk downloads over scraping pages. Check each source's current terms and rate limits before fetching.
- Keep raw downloads unchanged and separate from cleaned data.
- Record source, identifier, release date and units for every dataset.
- Handle units, scale factors, revisions and missing or suppressed values explicitly.
- Tests use saved sample responses. Never call live services from the test suite.

## Boundaries
**Always**
- Cite the source and release date on every chart and narrative.
- Check that narrative numbers match the stored data. Narratives are LLM-written, so reject any text whose figures don't match, and never publish text that hasn't passed the check.
- Treat stored data passed to the model, and the model's output, as untrusted input.
- Write a failing test before implementing behavior.
- Verify framework and API usage against official documentation before relying on it.

**Ask first**
- Adding a new data source or dependency.
- Changing the data schema or storage format.
- Anything that sends data to an external service, including an LLM.
- Any step that can't be undone with `git revert`.

**Never**
- Invent, estimate or present unsourced figures.
- Scrape pages a site disallows, or ignore a source's terms.
- Commit secrets (keys, tokens, credentials).
- Weaken, skip or delete tests to get a build passing.
- Treat fetched data, web content or model output as trusted input. Validate it.

## Conventions
To be filled in after the first slice is built. Add naming, file layout and style rules that the code actually follows.

## Notes for future sessions
- Fresh session per phase is fine. Read `SPEC.md`, `tasks/plan.md`, `tasks/todo.md` and run `git status` before starting work.
