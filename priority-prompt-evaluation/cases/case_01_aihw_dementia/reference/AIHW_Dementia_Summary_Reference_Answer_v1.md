# AIHW Dementia in Australia – Summary
## Human-Verified Reference Answer — Version 1

**Status:** Human-verified reference answer — Version 1 (frozen).

**Human sign-off date:** 13 September 2026.

**Verification basis:** Final human sign-off following source-based review against the official AIHW Summary page and an independent cross-model audit.

**Version control:** This file is the frozen Reference Answer v1 for Prompt v1 evaluation. Any future substantive correction should be recorded in a new version rather than silently changing v1.

**Attribution:** Based on Australian Institute of Health and Welfare (AIHW) material.

**Official source:** https://www.aihw.gov.au/reports/dementia/dementia-in-aus/contents/summary

**Source/version note:** Retrieved on 12 September 2026. The report header displays **“Last updated: 30 Jul 2026”**. The page/footer separately displays **“Last updated 21/07/2026 v252.0”**. These are retained as separate metadata signals rather than treated as interchangeable. Matching the previously observed dates does not establish that the content is unchanged without an earlier retained snapshot. Retrieval/access dates can vary between evaluation runs and should not be treated as a substantive factual disagreement. This assessment uses the currently accessible AIHW Summary page.

---

# Output 1 — Structured reference result

## A. Article metadata

| Field | Reference result |
|---|---|
| `title` | Dementia in Australia — Summary |
| `source` | Australian Institute of Health and Welfare (AIHW) |
| `url` | https://www.aihw.gov.au/reports/dementia/dementia-in-aus/contents/summary |
| `publication_date` | `null` — a separate original publication date is not explicitly displayed on the selected page. The report citation uses 2026. |
| `last_updated_date` | **2026-07-30** — report-level “Last updated” date. Separate page/footer version marker: **2026-07-21, v252.0**. |
| `reference_period` | Selected findings: 2025 prevalence estimate; 2026–2066 projections; 2024 mortality and disease burden; 2023–24 hospitalisations, medications and expenditure; 2021–22 permanent residential aged care; May, July and September 2025 treatment/regulatory events. |
| `comparison_period` | Prevalence: Figure 1 spans 2010–2066, with projections from 2026. Mortality: 2009–2024. Burden rankings: 2011, 2015, 2018 and 2024. Hospitalisations, medication use, residential aged care and expenditure: no temporal comparator used in the selected findings. |
| `retrieval_date` | 2026-09-12 |

Dates and periods are taken from the report header, page/footer version marker and the individual sections described below. The recorded retrieval date reflects this reference-building run; later evaluation runs may display a different access date without implying a source-content change.

## B. Source-grounded findings

The findings below contain source evidence only. Medibank interpretation appears separately in Section C.

### F1 — Estimated prevalence and projected population growth

| Field | Reference result |
|---|---|
| `finding` | AIHW estimates approximately 439,000 Australians had dementia in 2025, projects approximately 459,000 in 2026, and projects nearly 1.1 million by 2066. |
| `affected_population` | Australians living with dementia; all persons, with women and men separately reported. |
| `geography` | Australia |
| `measure` | Estimated/projected number of people living with dementia; sex distribution. |
| `value` | Figure 1: 438,565 in 2025; 459,231 in 2026; 1,064,344 in 2066. In 2025: 274,190 women, 164,375 men; narrative shares 63% women, 37% men. |
| `unit` | People; % of estimated people with dementia. |
| `comparator_or_baseline` | 2025 estimate provides the current-population context for the subsequent projections; Figure 1 includes annual estimates from 2010. |
| `magnitude_or_trend` | The narrative describes an increase to 2.5-fold by 2066. This is a reported rounded projection, not a calculated change adopted here or an observed increase. |
| `supporting_evidence` | The narrative supplies rounded totals; the accessible Figure 1 table supplies the more precise values above. |
| `source_location` | “How many people have dementia?”; Figure 1 table and source note. |
| `source_caveat` | Exact prevalence is unknown; there is no single authoritative prevalence data source. Estimates combine published prevalence rates with ABS population estimates. The 2025 population input is preliminary; from 2026, ABS Medium series population projections are used. |

**Source:** AIHW Summary — prevalence narrative and Figure 1.

### F2 — Mortality level and historical change

| Field | Reference result |
|---|---|
| `finding` | Dementia was Australia’s leading cause of death in 2024. Both the number of deaths and the age-standardised death rate were higher than in 2009. |
| `affected_population` | People whose underlying cause of death was dementia; deaths registered in the specified years. |
| `geography` | Australia |
| `measure` | Death count; share of all deaths; age-standardised mortality rate. |
| `value` | More than 18,300 deaths, 9.8% of all deaths, in 2024; age-standardised rate 44 per 100,000. |
| `unit` | Deaths; % of all deaths; deaths per 100,000 population. |
| `comparator_or_baseline` | 2009: 8,500 deaths; age-standardised rate 33 per 100,000. |
| `magnitude_or_trend` | Counts and age-standardised rates increased between 2009 and 2024. The source’s trend sentence rounds the 2024 count to 18,300. |
| `supporting_evidence` | Dementia ranked first among causes of death for women and second for men, after coronary heart disease. |
| `source_location` | “Deaths and disease burden” → “Dementia is the leading cause of death in Australia”; Figure 2 notes. |
| `source_caveat` | Underlying causes only, excluding associated causes. Years refer to registration. The 2023–2024 data are preliminary and subject to revision. Rates use the 2001 Australian Standard Population. Greater awareness and coding improvements may contribute to the recorded increase. |

**Source:** AIHW Summary — mortality and Figure 2 notes.

### F3 — Disease burden

| Field | Reference result |
|---|---|
| `finding` | Dementia was Australia’s second leading cause of disease burden in 2024, and the leading cause for women and for Australians aged 80 and over. |
| `affected_population` | Australians overall; women; Australians aged 80 and over. |
| `geography` | Australia |
| `measure` | Total disease burden; fatal/non-fatal shares; ranking among causes. |
| `value` | Almost 262,000 estimated DALYs; 59% attributable to premature death and 41% to living with dementia. |
| `unit` | Disability-adjusted life years; % of dementia burden; rank. |
| `comparator_or_baseline` | Ranked fifth in 2011, third in 2015 and 2018, and second in 2024, behind coronary heart disease. |
| `magnitude_or_trend` | Dementia rose in rank from fifth in 2011 to third in 2015 and 2018 and second in 2024. This does not itself quantify growth in DALYs. |
| `supporting_evidence` | AIHW defines one DALY as one year of healthy life lost, combining premature mortality and living with disease. |
| `source_location` | “Dementia is a leading cause of burden of disease”; Figure 3 and notes. |
| `source_caveat` | Burden-of-disease figures are estimates/modelled results rather than directly observed counts. Residual disease categories are excluded from the rankings. Rounding can prevent male and female estimates from summing exactly to all-person estimates. Changes in ranking do not themselves quantify growth in DALYs. |

**Source:** AIHW Summary — disease burden and Figure 3.

### F4 — Hospitalisations principally due to dementia

| Field | Reference result |
|---|---|
| `finding` | In 2023–24, approximately 27,800 hospitalisations had dementia as the main reason for admission; average hospital stay was 15.1 days. |
| `affected_population` | Hospitalisations with dementia recorded as the principal diagnosis. |
| `geography` | Australia |
| `measure` | Hospitalisation count; share of all hospitalisations; average length of stay. |
| `value` | About 27,800; 1 in every 455 hospitalisations; 15.1 days. |
| `unit` | Hospitalisations; proportion of hospitalisations; days per stay. |
| `comparator_or_baseline` | More than 12.6 million Australian hospitalisations in 2023–24. No previous-period or other-condition length-of-stay comparator is stated here. |
| `magnitude_or_trend` | `null` — no temporal utilisation trend or comparative excess length of stay is established. |
| `supporting_evidence` | The hospitalisation section reports these measures together and explicitly defines the principal-diagnosis scope. |
| `source_location` | “Hospitalisations”; paragraphs preceding Figure 4. |
| `source_caveat` | Excludes hospitalisations where dementia appears only as an additional diagnosis or supplementary chronic condition code. |

**Source:** AIHW Summary — Hospitalisations.

### F5 — Medication use and antipsychotic dispensing

| Field | Reference result |
|---|---|
| `finding` | In 2023–24, nearly 737,000 dementia-specific prescriptions were dispensed under PBS/RPBS to about 77,500 **Australians with dementia aged 30 and over**. Antipsychotics were also dispensed to 20% of this recipient group. |
| `affected_population` | Australians with dementia aged 30 and over receiving dementia-specific medications under PBS/RPBS; specified age subgroups for antipsychotic comparisons. |
| `geography` | Australia |
| `measure` | Prescription count; recipient count; proportion also dispensed antipsychotics. |
| `value` | Nearly 737,000 prescriptions; about 77,500 people; 20% overall; 24% among recipients aged 30–64, versus 20% among those aged 85 and over. |
| `unit` | Prescriptions; people; % of the specified medication-recipient group. |
| `comparator_or_baseline` | Antipsychotic dispensing: ages 30–64 compared with ages 85 and over, in the same year. |
| `magnitude_or_trend` | Higher antipsychotic dispensing proportion in the younger group; no temporal change established. |
| `supporting_evidence` | AIHW reports dispensing figures and identifies inappropriate antipsychotic prescribing as a concern. |
| `source_location` | “Dementia-specific medications”; dispensing and antipsychotic paragraphs. |
| `source_caveat` | The antipsychotic denominator is people dispensed dementia-specific medications, not everyone with dementia. The source’s general prescribing concern does not establish that these particular prescriptions were inappropriate. |

**Source:** AIHW Summary — Dementia-specific medications.

### F6 — Treatment developments with stated private access

| Field | Reference result |
|---|---|
| `finding` | The Summary reports that donanemab was approved by the TGA in May 2025; the PBAC did not recommend PBS listing for donanemab in July 2025; and lecanemab was approved by the TGA in September 2025. Suitable patients can access both medicines privately, with restrictions because of serious-side-effect risk. |
| `affected_population` | Donanemab: Australians with mild cognitive impairment due to Alzheimer’s disease or early symptomatic Alzheimer’s disease. Lecanemab: people with early Alzheimer’s disease. |
| `geography` | Australia |
| `measure` | Approval, reimbursement recommendation and access status as reported by AIHW. |
| `value` | `null` — categorical developments, not a single numerical measure. |
| `unit` | `null` |
| `comparator_or_baseline` | `null` — no quantified previous-treatment comparator supplied. |
| `magnitude_or_trend` | `null` — categorical regulatory events, not a magnitude or trend. |
| `supporting_evidence` | AIHW reports the May 2025 TGA approval of donanemab, the July 2025 PBAC non-recommendation for PBS listing due to modest clinical impact and high treatment burden, the September 2025 TGA approval of lecanemab, and private access to both medicines for suitable patients. |
| `source_location` | “Dementia-specific medications”; final treatment-development paragraphs. |
| `source_caveat` | Private access is restricted because of serious-side-effect risk. The Summary provides no quantified treatment benefit, uptake, price, insurance coverage or lecanemab PBS listing status. These are AIHW-reported events, not an independently verified current regulatory assessment. |

**Source:** AIHW Summary — treatment-development paragraphs.

### F7 — Dementia among permanent residential aged-care residents

| Field | Reference result |
|---|---|
| `finding` | In 2021–22, more than half of people living in permanent residential aged care had dementia. |
| `affected_population` | People living in permanent residential aged care. |
| `geography` | Australia |
| `measure` | Number and proportion of permanent residential aged-care residents with dementia. |
| `value` | About 131,000 people, or 54%. |
| `unit` | People; % of permanent residential aged-care residents. |
| `comparator_or_baseline` | More than 242,000 people living in permanent residential aged care in 2021–22. |
| `magnitude_or_trend` | `null` — a cross-sectional proportion, not a demonstrated increase. |
| `supporting_evidence` | The aged-care section supplies the denominator, dementia count and proportion together. |
| `source_location` | “Aged care services” → “How do people with dementia access aged care services?”; final paragraph. |
| `source_caveat` | The Summary explicitly states that updated 2022–23 data on residents with dementia are unavailable. |

**Source:** AIHW Summary — Aged care services.

### F8 — Health and aged-care expenditure attributable to dementia

| Field | Reference result |
|---|---|
| `finding` | Almost $6 billion of Australian health and aged-care spending in 2023–24 was estimated to be directly attributable to dementia diagnosis, treatment and care. |
| `affected_population` | People with dementia whose diagnosis, treatment and care contribute to the estimated expenditure. |
| `geography` | Australia |
| `measure` | Attributable health and aged-care expenditure and service-area shares. |
| `value` | Total: almost $6 billion. Narrative: residential aged care $2.7 billion / 45%; hospitals $1.4 billion / 24%; community-based aged care $1.2 billion / 20%. Figure 5 table gives hospitals $1.43 billion and community-based aged care $1.18 billion. |
| `unit` | Australian dollars; % of estimated attributable expenditure. |
| `comparator_or_baseline` | Shares compare service areas within the same annual total; no prior-year expenditure comparator supplied. |
| `magnitude_or_trend` | Residential aged care accounts for the largest share. No expenditure growth rate is established. |
| `supporting_evidence` | Narrative and Figure 5 report the spending distribution at different levels of rounding. |
| `source_location` | “Spending on dementia”; Figure 5 table, notes and source attribution. |
| `source_caveat` | Estimated expenditure; residential aged-care expenditure covers permanent residents only. The Summary identifies broader expenditure timeliness gaps. |

**Source:** AIHW Summary — Spending on dementia and Figure 5.

## C. Medibank assessment — interpretation and judgement

### Relevance

**decision:** relevant

**rationale:** The mortality and burden findings establish clinical significance. Hospitalisations and medication dispensing provide concrete service-use signals, while the prevalence projections support longer-term investigation of care needs. The reported private access to emerging treatments creates a more direct private-health connection. These findings justify investigation under the supplied Medibank criteria; they do not establish equivalent patterns among Medibank members.

### Criteria assessment

Evidence references below point to the source-grounded findings above.

| Criterion | Evidence | Judgement |
|---|---|---|
| Clinical significance | F2–F3: mortality and disease burden. F5–F6: medication-use concerns and treatment restrictions. | Strong relevance to patient outcomes and care. Dispensing alone does not establish inappropriate treatment. |
| Utilisation/demand | F4–F5: hospitalisation and prescription volumes. F7: residential care population. F1: projected population growth. | Demonstrates existing national service use and supports investigating future demand. Does not demonstrate rising admissions, longer stays over time or Medibank demand growth. |
| Population affected | F1: population estimates and sex distribution; F7: residential-care population. | Substantial national scale supports relevance. Medibank’s corresponding population is unknown. |
| Magnitude of change | F1: projected increase; F2: historical mortality change; F3: changing burden ranking. | Meaningful signals, but projections, registered mortality and rankings measure different things. None supplies a direct estimate of additional Medibank utilisation. |
| Cost implications | F8: attributable national spending and its distribution. | Supports examining relevant expenditure categories. Does not establish Medibank costs, cost growth or financial exposure. |
| Trend continuity | F1: annual estimated/projected series; F2: historical mortality series. | Supports a continuing national issue. Projection continuity must not be described as observed future growth; coding changes also qualify mortality interpretation. |
| Private-health relevance | F6: explicitly reported private treatment access. F4: national hospital use without a private-sector split. | Private access is directly relevant to further investigation. Private access does not establish private insurance reimbursement or Medibank coverage. |
| Emerging treatment/technology/model of care | F6: specified 2025 treatment developments. | Supported for treatments. No evaluated new model of care or quantified service impact is established in the selected evidence. |
| Evidence strength | AIHW’s original Summary, tables and methodological notes; stated prevalence uncertainty and incomplete data coverage. | Suitable for a traceable national reference, with finding-specific qualifications. Official publication does not remove estimation uncertainty or coverage limitations. |
| Actionability | F4–F6 identify specific hospital-use, medication and treatment-access questions. | Actionable as a basis for scoped investigation and monitoring. Insufficient for recommending a coverage, treatment or operational change. |

The Summary also warns that available dementia data may disproportionately represent moderate and severe dementia, with gaps in primary care, community service use and timely expenditure information. This limits conclusions about complete demand and costs.

### Priority

**category:** Medium Priority

**rationale:** The article warrants active investigation because it combines substantial clinical burden, concrete service-use evidence and treatment developments with stated private access. However, much of the evidence describes existing national burden or long-term projections. It does not establish a recent increase in hospital utilisation or expenditure, quantify treatment uptake, or demonstrate Medibank exposure. The treatment events are from 2025 and are not established as newly occurring in this update. Together, these factors support a substantive investigation item, while the Summary alone does not establish sufficient immediacy or organisation-specific impact for High Priority.

### Additional fields

#### `why_it_may_matter_to_medibank`

The findings provide specific questions for Medibank about dementia-related hospital use, member care needs and emerging treatment access. Any connection to Medibank’s population, benefits or expenditure remains a hypothesis requiring internal evidence.

#### `monitoring_or_followup`

1. Check whether suitable internal data can identify members with dementia and distinguish principal-diagnosis hospitalisations from admissions where dementia is an additional diagnosis.
2. Where data permit, examine hospitalisation counts, unique patients, length of stay and expenditure over comparable periods, accounting for membership size and age composition.
3. Investigate the reported treatment developments, including eligibility, uptake, service requirements and any relevant coverage arrangements, before drawing operational conclusions.
4. Monitor subsequent AIHW updates for hospital-use trends, revised prevalence estimates and expenditure changes. Preserve the distinction between revised estimates and actual changes.

#### `information_gaps`

- Medibank member prevalence, demographics and dementia severity: not stated.
- Medibank utilisation, claims, expenditure and trends: not stated.
- Private/public hospital breakdown and privately insured share of the reported population: not stated in the selected findings.
- Total hospital use where dementia is an additional diagnosis: not quantified in this Summary’s hospitalisation finding.
- Treatment uptake, quantified benefits and harms, prices, and insurance reimbursement: not stated.
- Evidence of increasing hospitalisation rates or expenditure over comparable years: not supplied for the selected measures.
- Complete prevalence ascertainment and comprehensive primary/community care data: explicit source limitations.
- Exact changes relative to the previously observed version: unknown without a retained earlier snapshot.

---

## Benchmark scope note

The selected findings above are intended to capture the principal Medibank-relevant evidence from the AIHW Summary page and are **not an exhaustive transcription of every valid finding on the page**. A later model should not be marked incorrect solely for identifying an additional AIHW-supported finding, provided that finding is accurate, relevant to the task, traceable to the source and appropriately qualified. Conversely, omission of a non-essential additional finding is not automatically an error. Additional findings should not receive credit if they are unsupported, outside the selected source, materially misqualified, or converted into unsupported Medibank-specific claims.

---

# Output 2 — Reference-check table

“Verified from source” means checked against the accessible AIHW page. Human sign-off applies to this frozen reference answer; the underlying AIHW datasets were not independently re-analysed.

| Check | Reference expectation | Evidence/source location | Verification status |
|---|---|---|---|
| Article/update date | Report-level header: 30 July 2026. Separate page/footer version marker: 21 July 2026, v252.0. Preserve both as distinct metadata signals. | Report header; Summary footer | Verified from source |
| Original publication date | `null`; do not substitute an update date. | No separate original publication date displayed | Not stated |
| Reference period(s) | Keep 2025 prevalence, 2026–2066 projections, 2024 mortality/burden, 2023–24 service-use/spending, and 2021–22 residential-care data separate. | F1–F8 and their source locations | Verified from source |
| Important population figures | 2025 estimated total 438,565; 274,190 women, 164,375 men. Preserve narrative rounding separately. | “How many people have dementia?”; Figure 1 | Verified from source |
| Major prevalence/projection finding | 459,231 in 2026 and 1,064,344 in 2066 are projections. Narrative reports 2.5-fold growth. | Figure 1, narrative and source note | Verified from source |
| Mortality | More than 18,300 deaths; 9.8% in 2024. Age-standardised rate 33 → 44 per 100,000, 2009–2024; underlying-cause and registration-year scope. | Mortality subsection; Figure 2 notes | Verified from source |
| Disease burden | Almost 262,000 estimated DALYs, 59% fatal / 41% non-fatal, second-ranked in 2024. Burden figures are estimates/modelled results; rank changes are not DALY growth estimates. | Burden subsection; Figure 3 | Verified from source |
| Hospital utilisation | About 27,800 hospitalisations, 15.1-day average stay, 2023–24; principal diagnosis only. | “Hospitalisations” | Verified from source |
| Medication use | Nearly 737,000 prescriptions / about 77,500 **Australians with dementia aged 30+**; antipsychotic percentages apply to that recipient group. | “Dementia-specific medications” | Verified from source |
| Emerging treatments | Preserve the 2025 event dates and restricted private access; do not infer coverage or quantified benefit. | Final treatment-development paragraphs | Verified from source |
| Residential aged care | About 131,000 / 54%, denominator over 242,000, 2021–22. | “Aged care services” | Verified from source |
| Expenditure | Almost $6 billion, 2023–24; retain narrative/table rounding differences; national attributable spending. | “Spending on dementia”; Figure 5 | Verified from source |
| Relevance judgement | Relevant as a national clinical, utilisation and treatment signal requiring internal investigation. | Section C, applying supplied criteria to F1–F8 | Interpretation only |
| Priority judgement | Medium Priority, reflecting substantive relevance but unestablished immediacy and Medibank impact. | Section C priority rationale | Interpretation only |
| Unsupported Medibank claims check | Member prevalence, claims, costs, coverage and operational impacts remain unknown; no national finding is labelled a Medibank finding. | Section C information gaps; source contains no corresponding Medibank evidence | Not stated |
| Benchmark completeness | The selected findings are representative rather than exhaustive; additional accurate and relevant Summary-page findings may still be valid. | Benchmark scope note | Evaluation rule |
| Human verification | Human-verified Reference Answer v1; final sign-off approved 13 September 2026. | Document status and verification record | Human-verified / frozen v1 |