# Source terms and limits (T0)

Read 2026-11-04 from the official pages listed. Anything not confirmed is marked **UNVERIFIED**.

The Bank of Canada terms page and Valet how-to page were read again on 2026-11-23. That reading was done by an automated page fetch, and the quotes recorded below have not been re-checked against the pages by a person.

## Statistics Canada, Web Data Service (WDS)
Page: https://www.statcan.gc.ca/en/developers/wds/user-guide

Confirmed:
- Server limits: "50 requests per second with a individual IP address limit of 25 requests per second."
- Per-request data-point limits exist ("there will be limits to the number of data points per request") but **no number is given** on the pages read.
- Availability: between midnight and 8:30 a.m. Eastern, some methods return no data; tables locked during updates may return HTTP 409. **Refresh jobs must not run in that window and must treat 409 as retry-later.**
- A coordinate has at most 10 dimensions (structural, not a request cap).

UNVERIFIED:
- Max vectors/coordinates per request (a third-party R package says split batches over 300; not confirmed).
- Licence and attribution text. The user guide excerpt read has none. Read the StatCan Open Licence page directly before finalising `sources.md` wording (T7).
- About 35k characters of the user guide were not read.

Decision for the code: default throttle is far below the limit (1 request per second), prefer full-table CSV (one download per table), and schedule StatCan checks after 8:30 a.m. ET.

## Bank of Canada
Terms: https://www.bankofcanada.ca/terms/  Valet how-to: https://www.bankofcanada.ca/valet-api-how-to/

Confirmed:
- Free use, copy, distribution and transmission of website content, subject to conditions.
- Attribution: "You must attribute the Bank of Canada as the source of the content, and indicate if changes were made."
- Non-endorsement: use must not suggest the Bank endorses us or our use of the content.
- Due diligence: "You must exercise due diligence in ensuring the accuracy of any content you reproduce."
- Commercial use: the terms do not prohibit it. If content is provided through paid services or put in documents for sale, buyers must be told before sale that the content came from the Bank's site and is free there (section 1.3). Not relevant while outputs are free. **Open question for the author:** whether posting to a paid Substack tier counts as a paid service. The terms do not say.
- Exceptions: no bank note images; logo and wordmark not reproducible without written permission; third-party content not covered. **Do not use the Bank's logo in charts.**
- Must not circumvent request limits. No numeric Valet limit is published. Guidance: cache data that updates daily, start slowly, back off on failure.
- Exchange rates are not intended as a benchmark for executing trades (relevant if exchange rates are added later).
- No named licence: the terms page does not mention the Open Government Licence or any other named licence. The permission is the one in the terms themselves.
- No exact credit wording is required. Attribution may be given "in any reasonable manner".
- Nothing specific about charts or calculated values. The only related duties are "indicate if changes were made" and the accuracy duty above.
- Third-party content (section 2.3) is not licensed to us "unless it expressly indicates that You may do so". The policy rate is the Bank's own series. Check this again for any series the Bank sources from a vendor, such as exchange rates.
- No last-updated date is shown, and the Bank may change the terms "at any time without prior notice". Re-read them before any new publication cycle, and keep the read date above current.

Attribution line for the policy rate (as stored in `catalog.py` and drawn on the chart). On 2026-11-23 this was judged to meet the terms: it names the Bank as the source, says values are reproduced as published and that derived values are calculated by this project, and says nothing that suggests the Bank endorses us.
> Source: Bank of Canada, Valet API, series V39079. Figures are reproduced as published; any derived values are calculated by this project.

An "accessed <date>" part, which an earlier draft had, is not required by the terms and is not in the stored text. The data release date is drawn separately on the chart.

UNVERIFIED:
- Whether the Valet API has terms beyond the terms page above. See the Valet section below. The Valet how-to page points to the terms page only, but the Valet endpoint documentation could not be read.

Resolved:
- Policy-rate series: `V39079`, labelled "Target for the overnight rate (business daily)" in the live Valet response (`seriesDetail`), unit "Percent".
- Fixture `tests/fixtures/boc_policy_rate.json` (3 observations, 2026-11-09 to 2026-11-11) matches the live Valet response: identical `seriesDetail` and `terms` blocks, same observation shape and values. Checked against one live fetch on 2026-11-13 (4,568 observations, 2009-04-21 to 2026-11-11). Valet publishes no release date, so the latest observation date is stored as the release date.

## Bank of Canada Valet API
Pages: how-to https://www.bankofcanada.ca/valet-api-how-to/  Endpoint documentation https://www.bankofcanada.ca/valet/docs  Governing terms: https://www.bankofcanada.ca/terms/

Confirmed (how-to page, read 2026-11-23):
- Terms: "When using the Valet API, be sure to read and follow our terms of use and disclaimers." It links to the terms page above, so the Bank of Canada terms in the previous section apply. The how-to page states no separate licence, attribution rule or redistribution rule of its own.
- Access: no registration, no access key and no cost.
- Request shape: every route begins with `https://www.bankofcanada.ca/valet/` (or the French-language `https://www.banqueducanada.ca/valet/`). Every call must include at least one of `seriesName`, `groupName` or `format`. Formats are JSON, CSV and XML.
- Limits: **no numeric limit is published** on the page read. The terms page names the Valet API as an example of a service whose request limits must not be circumvented. The how-to guidance is "Start slow during peak times", "Retry with care: If a request fails, wait before trying again", and "Use caching when possible", for example for data that updates once a day.
- Timing: "there may be a brief processing delay before data appears in the Valet API." The how-to page gives no release schedule per series. This is why the app stores the latest observation date as the release date (see the Bank of Canada section).

UNVERIFIED:
- The endpoint documentation page (`/valet/docs`) could not be read: it is built in the browser, and the automated fetch returned only the words "Valet API". It may state request limits or terms that the how-to page does not. **A person should read it in a browser, and the result should be recorded here.**
- The observations endpoint format. The how-to page does not describe it. The code relies on the saved sample response, which matched a live response on 2026-11-13 (see "Resolved" above).
- The how-to page shows no last-updated date.

Decision for the code: keep the default throttle, back off on failure, and cache daily data instead of re-fetching it. T3 already records the throttle and back-off (see "Consequences for the build"). Whether the code caches daily Valet data has not been checked.

## Consequences for the build
- Valet: before the first scheduled live refresh, read `/valet/docs` in a browser and record any limits above.
- T3: default throttle 1 request per second; honour 409 and 5xx with backoff; no jobs in the StatCan 00:00 to 08:30 ET window.
- T4: record the chosen series id from the live series list once, then save it as a fixture.
- T7: read the StatCan Open Licence page before writing the final acknowledgement.
- Chart and narrative text must say "indicate if changes were made" when values are derived (e.g. YoY %).
