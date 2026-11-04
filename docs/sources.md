# Source terms and limits (T0)

Read 2026-11-04 from the official pages listed. Anything not confirmed is marked **UNVERIFIED**.

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
- Commercial use: if content is sold, buyers must be told before sale that the content was obtained from the Bank's site. (Not relevant while outputs are free.)
- Exceptions: no bank note images; logo and wordmark not reproducible without written permission; third-party content not covered. **Do not use the Bank's logo in charts.**
- Must not circumvent request limits. No numeric Valet limit is published. Guidance: cache data that updates daily, start slowly, back off on failure.
- Exchange rates are not intended as a benchmark for executing trades (relevant if exchange rates are added later).

Draft attribution line for the policy rate:
> Source: Bank of Canada, Valet API, series <series id>, accessed <date>. Figures are reproduced as published; any derived values are calculated by this project.

UNVERIFIED:
- Whether the Bank's terms treat the Valet data under these same terms or additional ones (Valet page points to the terms page only).
- The exact policy-rate Valet series name. Confirm from the Valet series list when building T4.

## Consequences for the build
- T3: default throttle 1 request per second; honour 409 and 5xx with backoff; no jobs in the StatCan 00:00 to 08:30 ET window.
- T4: record the chosen series id from the live series list once, then save it as a fixture.
- T7: read the StatCan Open Licence page before writing the final acknowledgement.
- Chart and narrative text must say "indicate if changes were made" when values are derived (e.g. YoY %).
