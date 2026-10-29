# Discovery ground truth (13 to 27 October 2026)

Read by hand from the agencies' public listing pages on 28 October 2026, as a person would, rather than through the finders' search API or release-calendar parser. The finders' output is in `results/discovery.json`.

Sources read:
- AIHW: <https://www.aihw.gov.au/reports-data/latest-reports>
- ABS: the Health topic pages (<https://www.abs.gov.au/statistics/health> and its six sub-topic pages) and the release calendar (<https://www.abs.gov.au/release-calendar/latest-releases>)

Window: 13 to 27 October 2026 (the pipeline's 14-day discovery window on the run date).

## AIHW (12 listed)

| Date | Title | Finders | Outcome |
|---|---|---|---|
| 27 Oct | Pharmaceutical Benefits Scheme prescriptions: monthly data | returned | collected |
| 23 Oct | Aboriginal and Torres Strait Islander Health Performance Framework: October 2026 updates | not returned | belongs to a separate AIHW website |
| 22 Oct | General practice care for people with a mental health condition | returned | collected |
| 22 Oct | E-scooter and e-bike injuries and deaths in Australia | returned | collected |
| 21 Oct | Suicide & self-harm monitoring | returned | skipped (hub page) |
| 21 Oct | Hearing health outreach services (Northern Territory) | returned | collected |
| 20 Oct | Family, domestic and sexual violence | returned | skipped (hub page) |
| 16 Oct | GEN Aged Care Data: Residential Aged Care Quality Indicators, April to June 2026 | not returned | belongs to a separate AIHW website |
| 14 Oct | Health expenditure Australia 2024-25 | returned | collected |
| 14 Oct | Health system spending on disease and injury in Australia 2024-25 | returned | collected |
| 14 Oct | Growth decomposition of health system spending on disease and injury | returned | collected |
| 14 Oct | Health expenditure | returned | collected |

## ABS (3 listed)

| Date | Title | Finders | Outcome |
|---|---|---|---|
| 27 Oct | Causes of Death, Australia, 2025 | returned | collected |
| 27 Oct | Deaths from external causes, 2025 | returned | collected |
| 27 Oct | Intentional self-harm (suicide) deaths, 2025 | returned | collected |

No ABS health article fell in the window (the latest, "Children's physical activity, screen time and sleep", is dated 30 June 2026). An ABS item on the measurement of health care in the national accounts (23 October) is filed under the economy, not Health, and is outside the finders' scope by design.

## Counts

- Listed health publications: 15 (12 AIHW + 3 ABS).
- Returned by the finders: 13, so recall is 13 of 15 (86.7%).
- Collected as documents: 11. The two hub landing pages are skipped by the `skip_hub_pages` setting.
- Precision: all 11 collected documents are genuine health publications in the window.
- Not returned: two AIHW "web release" entries that point to separate AIHW websites (the Health Performance Framework and the Aged Care Data site).
