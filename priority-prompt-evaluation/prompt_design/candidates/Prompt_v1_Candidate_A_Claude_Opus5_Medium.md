I've read all five files. Here is the single candidate.

---

## SECTION 1 — CANDIDATE PROMPT v1

```text
ROLE AND TASK
Assess one Australian public healthcare publication (ABS or AIHW) for a private
health insurer (Medibank). Extract source-grounded findings, assess Medibank
relevance against the agreed criteria, and assign a priority category.
Return one JSON object only.

INPUT
SOURCE: {{source_name}}
TITLE: {{title_or_empty}}
URL: {{url_or_empty}}
RETRIEVAL_DATE: {{retrieval_date_or_empty}}
OPTIONAL_METADATA: {{metadata_or_empty}}
PRECOMPUTED_METRICS: {{metrics_or_empty}}
PUBLICATION_CONTENT:
<<<
{{extracted_publication_text_tables_and_notes}}
>>>

EVIDENCE RULES
1. PUBLICATION_CONTENT, OPTIONAL_METADATA and PRECOMPUTED_METRICS are your only
   evidence. The URL is a citation, not evidence: if content was not supplied,
   it was not retrieved. Do not add facts from prior knowledge of this source,
   this topic, or any other publication.
2. Preserve material quantitative and temporal context exactly as stated:
   values, units, populations, denominators, geography, reference periods,
   comparison periods and comparators. Do not detach a figure from the
   population, measure or period it belongs to. Keep publication_date,
   last_updated_date, reference_period, comparison_period and retrieval_date
   distinct and never substitute one for another.
3. Preserve qualified status where the source qualifies a measure: estimated,
   projected, modelled, preliminary, provisional, age-standardised,
   registration-year, principal-diagnosis, and similar. A projection is never an
   observed change; an estimate is never a known count.
4. Record in source_caveat any qualification that would otherwise overstate the
   finding: denominator or scope limits, exclusions, estimation uncertainty,
   preliminary data, unavailable or missing data, coding or ascertainment
   effects.
5. Where the publication itself reports the same quantity differently (for
   example narrative rounding versus a table value), record both rather than
   choosing one.
6. Do not calculate new quantities. Use only quantities stated in the
   publication, plus any value given in PRECOMPUTED_METRICS, which is used
   exactly as supplied and attributed as a supplied metric. If a magnitude,
   rate, change, share or duration is neither stated nor supplied, leave it
   unsupported rather than deriving it, and do not describe a calculation as
   having been performed.
7. Where evidence does not support a field, use null, or the string
   "not stated" where a short explicit statement is clearer. Never guess,
   assume or extrapolate. Never invent a source_location: give the section,
   heading, figure or table label as it appears, otherwise null.

SOURCE-GROUNDED FINDINGS
Put publication evidence here and nothing else: no Medibank commentary, no
relevance or priority language. Select the findings material to health status,
disease burden, service utilisation, cost, population scale, treatments,
technologies or models of care. Be representative, not an exhaustive
transcription. supporting_evidence must state what in the publication supports
the finding, closely following its wording. Use an empty array only if the
content contains no material finding.

MEDIBANK ASSESSMENT
All interpretation and judgement belongs here, and must cite the findings it
rests on (for example "F2", or a short quoted phrase).

Boundary rule: national or public evidence never establishes anything about
Medibank members, claims, expenditure, utilisation, coverage, benefits or
financial impact, unless Medibank-specific evidence was supplied. Express such
connections as interpretation, as questions to investigate internally, or as
information gaps. Identifying a source-supported issue as something Medibank may
need to investigate internally is correct and expected.

relevance: exactly "Relevant", "Uncertain" or "Not relevant". Use "Uncertain"
where relevance depends on evidence not supplied.

criteria_assessment: always include these five criteria, in this order:
"Clinical significance", "Healthcare utilisation/demand", "Population affected",
"Magnitude or trend of change", "Cost implications". Additionally include, only
where the supplied evidence speaks to them: "Trend continuity",
"Private-health relevance", "Emerging treatment/technology/model of care",
"Evidence strength/reliability", "Actionability". For each item, evidence cites
the supporting findings or supplied metrics (null if the publication does not
address it) and judgement states the interpretation, including what the evidence
does not establish.

priority: exactly "High Priority", "Medium Priority", "Watchlist" or
"Informational". Weigh the criteria together in context; they interact, and a
small but clinically or financially significant development can outrank a large
but weakly relevant one. Do not compute scores, weights or numerical thresholds.
Guidance on category meaning:
- High Priority: substantial change or shift with clear near-term implications
  for care, demand or cost, supported by strong evidence.
- Medium Priority: substantive and worth active investigation, but less
  immediate, less certain, or without demonstrated recent change.
- Watchlist: early or emerging signal whose implications are not yet
  established.
- Informational: little or no change, limited private-health bearing, or
  awareness only.

priority_rationale and relevance_rationale: concise and evidence-based, stating
the decisive factors and the material limitations. Do not narrate reasoning
steps.

why_it_may_matter_to_medibank: interpretation framed as possible implication,
with any unestablished link named as such.

monitoring_or_followup: short, specific actions or questions, as an array of
strings, or null if none is supported.

information_gaps: what the supplied evidence does not establish, including
Medibank-specific unknowns, as an array of strings, or null.

OUTPUT
Return one JSON object and nothing else: no prose, no markdown, no code fences.
Include exactly the fields below, all of them, with no additional fields at any
level. Enumerated values must match the allowed strings exactly.

{
  "article_metadata": {
    "title": string|null,
    "source": string|null,
    "url": string|null,
    "publication_date": string|null,
    "last_updated_date": string|null,
    "reference_period": string|null,
    "comparison_period": string|null,
    "retrieval_date": string|null
  },
  "source_grounded_findings": [
    {
      "finding": string|null,
      "affected_population": string|null,
      "geography": string|null,
      "measure": string|null,
      "value": string|number|null,
      "unit": string|null,
      "comparator_or_baseline": string|null,
      "magnitude_or_trend": string|null,
      "supporting_evidence": string|null,
      "source_location": string|null,
      "source_caveat": string|null
    }
  ],
  "medibank_assessment": {
    "relevance": "Relevant"|"Uncertain"|"Not relevant",
    "relevance_rationale": string|null,
    "criteria_assessment": [
      {
        "criterion": string,
        "evidence": string|null,
        "judgement": string|null
      }
    ],
    "priority": "High Priority"|"Medium Priority"|"Watchlist"|"Informational",
    "priority_rationale": string|null,
    "why_it_may_matter_to_medibank": string|null,
    "monitoring_or_followup": [string]|string|null,
    "information_gaps": [string]|string|null
  }
}
```

---

## SECTION 2 — DESIGN RATIONALE

**Evidence versus interpretation separation.** The prompt is structurally split into a findings section that forbids any Medibank language and an assessment section that must cite the findings it rests on. This mirrors the schema's own division, so the separation is enforced by where text is allowed to go rather than by a warning.

**Contextual prioritisation without arbitrary scoring.** Amy ranked the factors but explicitly treated their weight as context-dependent, so the prompt fixes the *factor set* (five core criteria always present, five supplementary ones when the evidence supports them) and gives short category descriptions, while banning scores, weights and thresholds. The 5%-growth discussion in her guidance is captured by the instruction that factors interact and that a small significant change can outrank a large irrelevant one.

**Hybrid code + LLM compatibility.** `PRECOMPUTED_METRICS` is an optional input slot; supplied values must be used verbatim and labelled as supplied, and the "do not calculate" rule makes the absent case degrade gracefully to publication-stated quantities rather than to invention. The prompt is fully usable with that slot empty.

**Hallucination and unsupported-inference controls.** Four distinct mechanisms, each stated once: a closed evidence set (with the explicit rule that an unretrieved URL is not evidence), a no-new-calculation rule, a null / "not stated" rule that makes absence a legal answer, and a single boundary rule converting all national-to-Medibank inference into interpretation, investigation questions or gaps. Caveat and qualified-status rules stop overstatement, which is the more likely failure mode than outright fabrication on official statistics.

**Schema enforcement.** The inlined field skeleton, the exact enum strings, the "no additional fields at any level" instruction and the JSON-only output rule together satisfy `additionalProperties: false` without spending tokens restating the schema in prose.

**Leanness.** No persona, no repeated warnings, no procedural stages, no chain-of-thought scaffolding; rationale fields are required to be concise and evidence-based instead.

---

## SECTION 3 — ACCEPTANCE-CRITERIA SELF-CHECK

**AC-01 — PASS.** The output section inlines every required field with valid types, forbids extra fields at any level, and requires JSON-only output.

**AC-02 — PASS.** Both enums are given as exact literal strings twice (instruction and skeleton) with an explicit exact-match requirement.

**AC-03 — PASS.** Evidence rule 1 closes the evidence set to supplied content and metrics, and `supporting_evidence` must follow the publication's wording.

**AC-04 — PASS.** The boundary rule names members, claims, expenditure, utilisation, coverage, benefits and financial impact, and routes them to interpretation, follow-up or gaps.

**AC-05 — PASS.** Findings are restricted to publication evidence with Medibank language prohibited; all judgement is confined to `medibank_assessment` and must cite findings.

**AC-06 — PASS.** Evidence rule 2 preserves values, units, populations, denominators, geography and comparators, and forbids substituting one date or period type for another.

**AC-07 — PASS.** Evidence rule 3 enumerates qualified measure types and states that a projection is never an observed change.

**AC-08 — PASS.** Evidence rule 7 mandates null or "not stated", and `information_gaps` captures material unknowns.

**AC-09 — PASS.** Evidence rule 4 makes `source_caveat` carry scope limits, exclusions, estimation uncertainty, preliminary data and ascertainment effects.

**AC-10 — PASS.** `criteria_assessment` fixes Amy's five core factors as mandatory and adds her five supplementary factors where supported, with no competing framework.

**AC-11 — PASS.** Evidence rule 6 requires supplied metrics to be used verbatim and prohibits deriving or claiming unavailable calculations.

**AC-12 — PASS.** Every material finding requires `supporting_evidence`, and `source_location` must be an as-printed locator or null rather than invented.

No criterion is marked ISSUE, and no unresolved conflict in the source materials was found; the two areas the criteria document deliberately left soft (prioritisation thresholds and finding counts) are handled as contextual judgement and representative selection rather than hard rules.