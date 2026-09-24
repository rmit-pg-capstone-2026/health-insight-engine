# Prompt v1 Evaluation Rubric v1

**Project:** RMIT–Medibank AI-Powered Clinical, Pharmaceutical and Medical Insights  
**Workstream:** LLM Relevance Scoring & Prioritisation  
**Status:** Post-audit final candidate — ready for human freeze/sign-off  
**Version:** v1  
**Date:** 14 September 2026

---

## 1. Purpose and Scope

This rubric is used to evaluate candidate LLM prompts for the Medibank relevance and prioritisation stage.

It is designed for:

- repeated controlled executions on the frozen AIHW Dementia development case; and
- later evaluation on additional ABS/AIHW cases.

It separates:

1. **Hard Gates** — non-negotiable acceptance requirements; and
2. **Scored Quality Dimensions** — dimensions where an output can be more or less effective even when it remains acceptable.

The rubric is intentionally practical for an RMIT industry-project proof of concept. It does not require an exact reproduction of the frozen human reference answer or a fixed number of findings.

### Authoritative basis

This rubric is derived from:

- `Prompt_v1_Acceptance_Criteria_v0.md`
- `Medibank_LLM_Relevance_Priority_Schema_v1_corrected.json`
- `AIHW_Dementia_Summary_Reference_Answer_v1.md`
- the frozen AIHW Dementia source snapshot
- genuine failure modes identified in the controlled Candidate A / Candidate B Run-1 evaluation

The frozen human reference is an evaluation anchor, not an exhaustive list of all valid findings. Additional findings may be valid when faithfully supported by the supplied source evidence.

---

## 2. Evaluation Order

Evaluate each raw candidate output in this order:

1. **Check the Hard Gates.**
2. **Record any Hard Gate `FAIL` or `REVIEW`.**
3. **Score the seven Quality Dimensions from 0–3.**
4. **Calculate the weighted quality score out of 100.**
5. For repeated executions, assess **Repeated-Run Consistency** separately.
6. Use hard-gate reliability, quality score, consistency and later held-out-case performance together when selecting/finalising Prompt v1.

Do not repair or rewrite a raw candidate output before evaluation.

---

# 3. Hard Gates

Hard Gates represent the frozen non-negotiable acceptance requirements.

Use these outcomes:

- **PASS** — the requirement is satisfied.
- **REVIEW** — a minor, borderline or ambiguous issue exists, but it does not clearly meet the material failure condition.
- **FAIL** — the output clearly violates the material failure condition.

A `REVIEW` does not automatically invalidate the run. The issue should instead be documented and reflected in the relevant scored quality dimension where appropriate.

A `FAIL` is a substantive acceptance failure. Quality scores may still be calculated for diagnosis, but a high quality score must not compensate for a Hard Gate failure in candidate selection.

**Unsupported-assertion rule:** Confirmed unsupported source-grounded factual assertions, unsupported Medibank-specific factual assertions, guessed missing information and fabricated quantitative calculations receive `FAIL` under the corresponding gate. `REVIEW` remains available for ambiguous wording or non-material qualification omissions that do not assert unsupported information.

## HG-1 — Structure and Allowed Labels

**Related Acceptance Criteria:** AC-01, AC-02

### What is checked

- raw output parses as valid JSON without repair;
- output conforms to the corrected JSON schema;
- required fields and types are present;
- prohibited extra properties are not added where `additionalProperties: false`;
- only the allowed relevance and priority labels are used.

### PASS

The raw output parses successfully, validates against the corrected schema, and uses only:

**Relevance**
- `Relevant`
- `Uncertain`
- `Not relevant`

**Priority**
- `High Priority`
- `Medium Priority`
- `Watchlist`
- `Informational`

### FAIL

Any of the following occurs:

- JSON cannot be parsed as returned;
- schema validation fails;
- required fields are missing;
- field types/structures are invalid;
- prohibited extra properties are introduced;
- a renamed, combined, numeric or invented relevance/priority category is returned.

---

## HG-2 — Evidence Integrity and Quantitative Non-Fabrication

**Related Acceptance Criteria:** AC-03, AC-11

### What is checked

- source-grounded factual claims are supported by the supplied publication evidence or supplied quantitative inputs;
- statistics, events and trends are traceable to supplied evidence;
- unavailable quantitative calculations are not invented;
- supplied/pre-computed metrics, when present, are used faithfully.

### PASS

Source-grounded factual claims are supported by the supplied evidence, and unavailable calculations are left unsupported rather than fabricated.

### REVIEW

A local wording or interpretation issue exists, but the underlying evidence remains correctly represented and no unsupported factual assertion or fabricated calculation is made.

### FAIL

The output presents as source-grounded fact a factual claim, statistic, trend or event that is unsupported by the supplied evidence, or invents a percentage, rate, magnitude, denominator or other calculation that was neither supplied nor validly supported by the input evidence.

---

## HG-3 — Medibank Evidence Boundary

**Related Acceptance Criteria:** AC-04, AC-05

### What is checked

- national/public-source evidence is not converted into unsupported Medibank-specific facts;
- source evidence remains separate from Medibank interpretation and judgement;
- Medibank implications are framed as interpretation, investigation questions or information gaps unless Medibank-specific evidence is supplied.

### PASS

The output clearly distinguishes source evidence from Medibank interpretation and does not claim that public-source evidence proves Medibank member prevalence, claims, utilisation, cost, coverage or operational impact.

### REVIEW

The distinction is generally preserved but a local phrase is somewhat stronger or less clearly qualified than ideal, without materially asserting an unsupported Medibank fact.

### FAIL

The output presents national/public-source evidence as proving a Medibank-specific factual claim about prevalence, claims, utilisation, costs, coverage or operational impacts without supporting evidence, or materially blends source fact and Medibank judgement so their origin cannot be distinguished.

---

## HG-4 — Material Quantitative, Temporal, Missingness and Caveat Fidelity

**Related Acceptance Criteria:** AC-06, AC-07, AC-08, AC-09

### What is checked

- values, units, populations/denominators, geography and relevant dates/periods;
- comparators and baselines;
- observed values versus estimates, projections, modelled results and other qualified measures;
- missing or unsupported information;
- material source caveats and scope limitations.

### PASS

Material context and qualifications are represented accurately enough to avoid misleading interpretation, and unsupported information remains `null`, `not stated`, or otherwise explicitly unavailable.

### REVIEW

A non-material qualification or caveat is omitted or expressed less precisely, but the output remains substantively correct and is not materially misleading.

Examples may include a local failure to explicitly repeat that a correctly reported burden-of-disease figure is modelled/estimated when the numerical value and interpretation otherwise remain correct.

### FAIL

Any of the following occurs:

- unsupported missing information is filled using assumption, invented detail or unsupported extrapolation;
- a material figure, date, period, denominator, unit or comparator is wrong, conflated, detached from context or invented;
- a projection is materially treated as an observed future change;
- an estimate/modelled result is materially converted into an unqualified observed fact;
- omission or contradiction of an important source caveat materially overstates the finding.

---

## HG-5 — Agreed Medibank Assessment Factors

**Related Acceptance Criterion:** AC-10

### What is checked

Relevance and priority judgement use the agreed Medibank framework rather than an unrelated prioritisation framework.

Core factors:

1. clinical significance;
2. utilisation / demand;
3. population affected;
4. magnitude of change;
5. cost implications.

Supported supplementary factors may include:

- trend continuity;
- private-health relevance;
- new/emerging treatment, technology or model of care;
- evidence strength/reliability;
- actionability / ability to investigate further.

### PASS

The judgement demonstrably uses the agreed factors and applies them contextually.

### REVIEW

The agreed factors are used, but one or more are handled superficially or not integrated well enough into the overall judgement.

### FAIL

The agreed framework is materially ignored or replaced by unrelated criteria.

---

## HG-6 — Source Traceability

**Related Acceptance Criterion:** AC-12

### What is checked

- each material finding can be traced to supplied evidence;
- `supporting_evidence` is meaningful;
- `source_location`, when supplied, is accurate;
- unavailable location details are not invented.

### PASS

Material findings are traceable to the supplied evidence and source locations are not fabricated.

### REVIEW

Traceability exists but a local source path/location is vague or less precise than ideal.

### FAIL

A material finding cannot be traced to supplied evidence, or a source location/evidence path is fabricated.

---

# 4. Scored Quality Dimensions

## 4.1 Scoring Scale

Use the same integer scale for every dimension:

- **0 — Materially deficient**
- **1 — Weak**
- **2 — Acceptable**
- **3 — Strong**

Weighted score:

`dimension weight × (dimension score / 3)`

Total weighted quality score = **100%**.

Hard Gate outcomes are reported separately and are not converted into points.

**Defect-attribution rule:** Assign each defect to its primary quality dimension. Reflect it in another dimension only where a distinct consequence is documented. Use QD-2 primarily for claim–evidence linkage and factual context, and QD-5 primarily for qualifications, caveats and missingness. Record all applicable Hard Gate outcomes separately.

---

## QD-1 — Important Finding Selection and Completeness

**Weight:** 15%  
**Related Acceptance Criteria:** AC-03, AC-10  
**Deferred basis:** completeness and relative importance of multiple valid findings

### Purpose

Assess whether the output selects enough decision-relevant evidence to support a useful relevance/priority judgement without requiring exhaustive transcription.

### 0 — Materially deficient

Misses several major decision-relevant signals or focuses mainly on peripheral material such that relevance/priority could be distorted.

### 1 — Weak

Captures some important findings but omits one or more significant clinical, utilisation, population, change, cost or emerging-treatment signals that would materially improve the assessment.

### 2 — Acceptable

Captures the major evidence needed for a sound relevance and priority assessment. Any omitted valid findings do not materially distort the judgement.

### 3 — Strong

Captures the important decision-relevant signals across the applicable assessment dimensions while avoiding unnecessary duplication and low-value transcription.

### Important rule

Do **not** reward an output simply for containing more findings. There is no required finding count, and the frozen reference answer is representative rather than exhaustive.

---

## QD-2 — Evidence Grounding and Traceability Quality

**Weight:** 20%  
**Related Acceptance Criteria:** AC-03, AC-06, AC-12

### Purpose

Assess the precision and auditability of the relationship between findings, quantitative context and their supporting evidence.

**Applicability rule:** Assess source locations, denominators and comparators where available and applicable. Do not reduce the score solely because unavailable details are explicitly represented as unavailable, provided the finding remains traceable.

### 0 — Materially deficient

Evidence is vague, materially detached from claims, difficult to trace, or frequently missing.

### 1 — Weak

Most claims appear grounded, but multiple findings lack sufficiently precise context, supporting evidence, denominator/comparator information or source location.

### 2 — Acceptable

Major findings are supported and readily traceable, with generally accurate evidence, context and source locations.

### 3 — Strong

Finding-level evidence is precise, context-rich and easy to audit. Material values, periods, populations, comparators and source paths are represented accurately and clearly.

---

## QD-3 — Relevance Reasoning

**Weight:** 15%  
**Related Acceptance Criteria:** AC-04, AC-05, AC-10

### Purpose

Assess how effectively the output integrates the agreed Medibank factors into the relevance judgement while respecting the national-versus-Medibank evidence boundary.

### 0 — Materially deficient

Relevance is unsupported, based on unrelated criteria, or materially converts national findings into direct Medibank impacts.

### 1 — Weak

Relevant factors are mentioned but reasoning is mostly a list, generic, incomplete or insufficiently connected to the final relevance label.

### 2 — Acceptable

The reasoning connects the principal applicable factors to the relevance label and acknowledges important evidence gaps and Medibank limitations.

### 3 — Strong

The reasoning provides a balanced synthesis of why the development is or is not relevant to Medibank, integrates the major applicable factors, and clearly distinguishes source evidence from what requires internal Medibank investigation.

---

## QD-4 — Priority Reasoning and Calibration

**Weight:** 20%  
**Related Acceptance Criteria:** AC-06, AC-07, AC-10  
**Deferred basis:** priority reasoning and borderline-category judgement

### Purpose

Assess whether the priority category is proportionate to the evidence and the agreed Medibank factors.

### 0 — Materially deficient

The priority is unsupported, materially inconsistent with the evidence, or driven by an inappropriate assumption such as treating large long-term burden as automatic evidence of immediate High Priority.

### 1 — Weak

The category is plausible but weakly justified, or important factors such as immediacy, magnitude, utilisation, cost, private-health relevance or information gaps are poorly balanced.

### 2 — Acceptable

The category is reasonably supported by the evidence and agreed factors, with important limitations and uncertainty considered.

### 3 — Strong

The category is carefully calibrated across the applicable factors, distinguishes current signals from longer-term burden/projections, and explains why the selected category is appropriate without relying on invented universal thresholds.

### Important rule

Do not impose a fixed numerical threshold for High/Medium/Watchlist/Informational. The project materials deliberately require contextual judgement.

---

## QD-5 — Uncertainty, Caveat and Unavailable-Evidence Handling

**Weight:** 10%  
**Related Acceptance Criteria:** AC-07, AC-08, AC-09, AC-11

### Purpose

Assess how well the output preserves uncertainty and the status of qualified or unavailable evidence.

### 0 — Materially deficient

Important missing information is guessed, or qualifications are removed in a way that materially changes meaning.

### 1 — Weak

The broad conclusion remains correct, but several useful qualifications, denominator limits, estimate/projection distinctions or information gaps are omitted or inconsistently handled.

### 2 — Acceptable

The main uncertainties, caveats and gaps are represented, and unsupported information remains unavailable rather than being invented.

### 3 — Strong

The output systematically and proportionately distinguishes observed, estimated, projected, modelled, preliminary and unavailable information and preserves the caveats needed for reliable interpretation.

---

## QD-6 — Follow-up and Monitoring Usefulness

**Weight:** 10%  
**Related Acceptance Criteria:** AC-04, AC-10

### Purpose

Assess whether suggested monitoring or investigation follows logically from the evidence and is useful for Medibank without becoming an unsupported operational conclusion.

**Applicability rule:** Where the evidence warrants no monitoring or follow-up, an explicitly justified absence may meet the Acceptable or Strong anchor according to the clarity and evidential support of that judgement. An unexplained `null` does not automatically earn either score.

### 0 — Materially deficient

Suggestions are disconnected from the evidence, misleading, or assert unsupported Medibank actions/facts.

### 1 — Weak

Suggestions are generic, repetitive or only loosely connected to the evidence and information gaps.

### 2 — Acceptable

Provides practical monitoring or internal-investigation questions linked to the findings.

### 3 — Strong

Follow-ups are specific, evidence-linked and directed toward resolving the most decision-relevant Medibank information gaps.

---

## QD-7 — Clarity, Concision and Output Efficiency

**Weight:** 10%  
**Related basis:** AC-01 plus deferred level-of-detail/concision criterion

### Purpose

Assess whether the output communicates enough evidence and reasoning without unnecessary repetition or verbosity.

### 0 — Materially deficient

The output is confusing, highly repetitive or bloated enough to obscure the decision.

### 1 — Weak

The output is understandable but noticeably repetitive, overlong, poorly prioritised or inefficient in its structured fields.

### 2 — Acceptable

The output is clear and reasonably concise while retaining the evidence and explanation required for a reliable assessment.

### 3 — Strong

The output is economical, well-prioritised and directly usable, with little duplication and no material evidence sacrificed for brevity.

### Important rule

Shortness alone is not better. Concision must not be rewarded when it removes material findings, caveats or reasoning.

---

# 5. Quality Score Summary

| Dimension | Weight |
|---|---:|
| QD-1 Important Finding Selection and Completeness | 15% |
| QD-2 Evidence Grounding and Traceability Quality | 20% |
| QD-3 Relevance Reasoning | 15% |
| QD-4 Priority Reasoning and Calibration | 20% |
| QD-5 Uncertainty, Caveat and Unavailable-Evidence Handling | 10% |
| QD-6 Follow-up and Monitoring Usefulness | 10% |
| QD-7 Clarity, Concision and Output Efficiency | 10% |
| **Total** | **100%** |

The weighted score supports comparison but does not override Hard Gate failures.

---

# 6. Repeated-Run Consistency Method

## 6.1 Approved Development-Case Design

For the frozen AIHW Dementia case:

- run **three controlled executions per candidate in total**;
- Candidate A: A1, A2, A3;
- Candidate B: B1, B2, B3;
- use the same frozen source snapshot;
- use the same common executor and reasoning setting;
- keep each candidate prompt version unchanged across its three executions;
- use the same execution wrapper;
- keep optional pre-computed quantitative metrics absent for all six Dementia executions;
- run each execution in a fresh chat;
- preserve every raw output unchanged.

This consistency assessment is separate from the 100-point per-run quality score.

## 6.2 What Should Remain Reasonably Stable

Across identical runs, the following should remain reasonably stable:

- Hard Gate status;
- relevance category;
- priority category;
- principal decision-driving findings;
- material numbers, periods, populations/denominators and caveats;
- main relevance rationale;
- main priority rationale;
- Medibank evidence boundary.

## 6.3 Acceptable Variation

The following variation is acceptable when it does not materially change the judgement:

- different wording;
- different ordering;
- different phrasing of rationale;
- inclusion/omission of secondary source-supported findings;
- small differences in level of detail.

## 6.4 Meaningful Consistency Problems

Examples include:

- a Hard Gate passes in one run and fails in another;
- relevance flips materially on identical evidence;
- priority changes are unexplained or are not defensible as borderline judgements on the same evidence;
- material facts, numbers or periods change across identical runs;
- important caveats disappear intermittently;
- unsupported Medibank implications appear in some runs but not others;
- principal evidence selection varies enough to materially change the assessment.

## 6.5 Stability Rating

After all three runs for a candidate, assign one overall development-case stability rating.

### Strong

- no Hard Gate FAIL across the three runs;
- relevance and priority labels are stable;
- principal decision-driving evidence and material caveats remain stable;
- score variation is small enough that the qualitative judgement is unchanged.

### Acceptable

- no Hard Gate `FAIL` across the three runs;
- relevance is stable;
- priority is the same in at least two of three runs; any differing label represents a documented, defensible borderline judgement on the same evidence;
- principal evidence and conclusions remain substantially consistent.

### Weak

One or more of the following occurs:

- Hard Gate failures appear intermittently or repeatedly;
- material relevance flips occur;
- priority changes are unexplained or are not defensible as borderline judgements on the same evidence;
- material facts/caveats change;
- materially different Medibank implications appear on identical evidence.

For comparison, report each candidate's:

- three per-run weighted scores;
- mean weighted score;
- score range;
- Hard Gate outcomes across runs;
- stability rating.

Do not use a complex statistical stability metric for this PoC.

---

# 7. Candidate Comparison Rule After Repeated Dementia Runs

When A1–A3 and B1–B3 are complete:

1. **Hard Gate reliability comes first.**
   - A candidate with repeated or material Hard Gate failures should not be preferred solely because of a higher average quality score.

2. **Compare weighted quality.**
   - Compare mean score and the dimension-level pattern, not only the overall total.

3. **Compare consistency.**
   - Prefer behaviour that remains reliable across identical executions.

4. **Do not select/finalise Prompt v1 from the Dementia case alone.**
   - Use the repeated Dementia case for development and stability evidence.
   - Confirm the leading candidate(s) on additional ABS/AIHW cases before finalisation.

---

# 8. Application to Later ABS/AIHW Cases

For each later test case:

**Metadata rule:** Judge candidate metadata against the supplied frozen case input. A reference-building retrieval/access date may legitimately differ from the frozen case snapshot's retrieval/capture date and should not, by itself, be treated as a factual error.

1. apply all six Hard Gates;
2. score all seven Quality Dimensions;
3. record the relevance and priority labels;
4. compare against the case-specific source evidence and human reference;
5. document material errors and judgement differences.

At least one later case should supply frozen pre-computed quantitative metrics so AC-11 can be tested for faithful metric use, not only for non-fabrication when metrics are absent.

No exact number of source-grounded findings is required.

If Candidate A and Candidate B are very close after the Dementia repetitions, both may be tested on the additional cases before selection.

---

# 9. Deferred / Separate Evaluation Items

The following are supported project concerns but are **not part of the 100-point individual-output score in this rubric**.

## 9.1 Cross-source conflict handling

Important for later cross-source work. When credible sources conflict, the system should surface the conflict rather than silently choose one. This cannot be meaningfully tested on every single-source article.

## 9.2 Prompt efficiency and cost

Useful when choosing between candidate prompts, but not a substantive correctness requirement of an individual output. Track separately using actual execution cost/token information where available.

## 9.3 Improvement over an unstructured LLM summary

This is a later project-level evaluation question. It should be assessed after the relevance/prioritisation prompt and pipeline are sufficiently mature, not treated as a Hard Gate for Prompt v1 candidate outputs.

---

# 10. Resolved Human-Review Decisions

The following decisions are fixed for this v1 rubric candidate:

1. **Scoring scale:** retain the 0–3 quality scale.
2. **Weights:** retain the proposed 15/20/15/20/10/10/10 weighting.
3. **Hard Gates:** consolidate the draft eight gates into six to reduce overlap.
4. **Materiality rule:** minor/non-material caveat or qualification omissions receive `REVIEW` and affect quality scoring; only materially misleading omissions receive `FAIL`.
5. **Completeness:** no fixed number or exact set of findings is required.
6. **Priority thresholds:** no universal numerical thresholds are introduced.
7. **Concision:** prefer sufficient evidence with less redundancy, but never reward brevity that removes material evidence or caveats.
8. **Consistency:** use three total controlled Dementia executions per candidate.
9. **URL formatting:** a schema-valid Markdown-form URL versus a bare canonical URL is not scored or penalised unless a later authoritative requirement explicitly requires a different format.

---

# 11. Change Log from Run-1 Draft Rubric

| Change | Rationale |
|---|---|
| Consolidated 8 draft Hard Gates into 6 | Reduces overlap while preserving AC-01 to AC-12 coverage |
| Retained the 0–3 scoring scale | Simple and practical for consistent PoC scoring |
| Retained weights of 15/20/15/20/10/10/10 | Balanced emphasis on evidence quality and priority reasoning without unnecessary re-optimisation |
| Added explicit `PASS / REVIEW / FAIL` Hard Gate outcomes | Allows minor/non-material qualification issues to be recorded without treating them as automatic acceptance failures |
| Added materiality rule to HG-4 | Prevents a minor caveat omission from invalidating an otherwise correct output unless interpretation becomes materially misleading |
| Clarified that more findings do not automatically mean better performance | The frozen reference is representative rather than exhaustive |
| Fixed Dementia consistency design at 3 total runs per candidate | Provides a practical stability check within project constraints |
| Added a simple Strong / Acceptable / Weak consistency rating | Avoids unnecessary statistical complexity |
| Explicitly made Markdown-form URL style non-penalised | The corrected schema accepts a string and no frozen requirement mandates a bare canonical URL |
| Separated cross-source conflict handling, prompt cost/efficiency and unstructured-summary comparison | These are supported later evaluation concerns but should not distort individual-output correctness scoring |
| Added a standard candidate-comparison procedure | Makes later A1–A3 versus B1–B3 comparison repeatable and auditable |
| Tightened unsupported-assertion failure boundaries | Aligns HG-2/HG-3/HG-4 with AC-03, AC-04, AC-08 and AC-11 so confirmed unsupported assertions are not excused by materiality |
| Qualified QD-2 by evidence availability | Prevents penalties for source locations, denominators or comparators that the source does not supply |
| Allowed justified absence of follow-up in QD-6 | Avoids incentivising unnecessary recommendations when no follow-up is warranted |
| Added a defect-attribution rule | Reduces accidental double-penalisation across overlapping quality dimensions |
| Clarified stability boundaries | Removes contradictory Hard Gate treatment and undefined category-adjacency language |
| Fixed candidate prompt versions across repeats | Makes the A1–A3 / B1–B3 consistency experiment explicit and reproducible |
| Generalised retrieval-date handling | Ensures case metadata is judged against the frozen case input rather than a reference-building access date |

---

## Freeze / Sign-off

This document is the **final candidate for `Prompt_v1_Evaluation_Rubric_v1.md`**.

Once human sign-off is given, freeze this file unchanged before executing Candidate A Run 2 / Run 3 and Candidate B Run 2 / Run 3.