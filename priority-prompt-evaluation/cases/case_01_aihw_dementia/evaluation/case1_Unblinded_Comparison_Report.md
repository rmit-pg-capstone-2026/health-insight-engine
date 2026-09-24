# Final Unblinded Comparison Report

## RMIT–Medibank AI-Powered Clinical, Pharmaceutical and Medical Insights

**Evaluation case:** AIHW Dementia Summary  
**Purpose:** Unblind and compare Candidate A vs Candidate B after formal blinded scoring of six controlled executions  
**Status:** Final development-case comparison  
**Important limitation:** This report does **not** declare the final Prompt v1 winner. The Dementia case is one development case only.

---

## 1. Private Mapping Used for Unblinding

| Anonymous output | Candidate run |
|---|---|
| Output_01 | A2 |
| Output_02 | B2 |
| Output_03 | B1 |
| Output_04 | A3 |
| Output_05 | B3 |
| Output_06 | A1 |

The blinded scoring report was completed before this mapping was revealed.

---

## 2. Run-Level Results

| Candidate run | Blinded output | Weighted score | Hard Gate result summary |
|---|---|---:|---|
| A1 | Output_06 | 93.33 / 100 | 5 PASS, 1 REVIEW, 0 FAIL |
| A2 | Output_01 | 93.33 / 100 | 5 PASS, 1 REVIEW, 0 FAIL |
| A3 | Output_04 | 96.67 / 100 | 5 PASS, 1 REVIEW, 0 FAIL |
| B1 | Output_03 | 93.33 / 100 | 5 PASS, 1 REVIEW, 0 FAIL |
| B2 | Output_02 | 93.33 / 100 | 5 PASS, 1 REVIEW, 0 FAIL |
| B3 | Output_05 | 93.33 / 100 | 5 PASS, 1 REVIEW, 0 FAIL |

All six outputs:
- passed JSON parsing;
- passed corrected-schema validation;
- had no Hard Gate FAIL;
- produced the same overall judgement: **Relevant** and **Medium Priority**.

---

## 3. Candidate-Level Comparison

| Metric | Candidate A | Candidate B |
|---|---:|---:|
| Run 1 | 93.33 | 93.33 |
| Run 2 | 93.33 | 93.33 |
| Run 3 | 96.67 | 93.33 |
| **Mean score** | **94.44** | **93.33** |
| Minimum | 93.33 | 93.33 |
| Maximum | 96.67 | 93.33 |
| **Score range** | **3.34** | **0.00** |
| Hard Gate FAILs | 0 across 3 runs | 0 across 3 runs |
| Repeated-run stability | **Strong** | **Strong** |

### Interpretation

Candidate A achieved a slightly higher mean score, by approximately **1.11 points**.

Candidate B showed stronger numerical consistency, with all three runs receiving exactly the same score.

The difference is small and should not be interpreted as evidence that Candidate A is decisively better overall.

---

## 4. Quality-Dimension Comparison

| Quality dimension | Candidate A average | Candidate B average | Interpretation |
|---|---:|---:|---|
| QD-1 — Important Finding Selection and Completeness | 3.00 | 3.00 | Tie |
| QD-2 — Evidence Grounding and Traceability Quality | 3.00 | 3.00 | Tie |
| QD-3 — Relevance Reasoning | 3.00 | 3.00 | Tie |
| QD-4 — Priority Reasoning and Calibration | 3.00 | 3.00 | Tie |
| QD-5 — Uncertainty, Caveat and Unavailable-Evidence Handling | 2.00 | 2.00 | Tie; shared weakness |
| QD-6 — Follow-up and Monitoring Usefulness | 3.00 | 3.00 | Tie |
| QD-7 — Clarity, Concision and Output Efficiency | 2.33 | 2.00 | Slight advantage to A |

The entire mean-score difference between the candidates came from **QD-7 — Clarity, Concision and Output Efficiency**.

A3 was the only run to receive QD-7 = 3. The other five runs received QD-7 = 2 because of repeated evidence, caveats, information gaps, or other material already stated elsewhere in the output.

---

## 5. Hard Gate Behaviour

Across all six runs:

| Hard Gate | Candidate A | Candidate B |
|---|---|---|
| HG-1 — Structure and Allowed Labels | PASS in all 3 | PASS in all 3 |
| HG-2 — Evidence Integrity and Quantitative Non-Fabrication | PASS in all 3 | PASS in all 3 |
| HG-3 — Medibank Evidence Boundary | PASS in all 3 | PASS in all 3 |
| HG-4 — Material Quantitative, Temporal, Missingness and Caveat Fidelity | REVIEW in all 3 | REVIEW in all 3 |
| HG-5 — Agreed Medibank Assessment Factors | PASS in all 3 | PASS in all 3 |
| HG-6 — Source Traceability | PASS in all 3 | PASS in all 3 |

There were **no Hard Gate FAILs** for either candidate.

---

## 6. Shared Recurring Weakness

The same issue appeared in all six outputs:

> The approximately 262,000 DALY burden figure was reported correctly, but the output did not explicitly preserve the fact that the burden result was estimated/modelled.

This produced:
- HG-4 = REVIEW for all six outputs; and
- QD-5 = 2 rather than 3 for all six outputs.

This is therefore best treated as a **shared recurring qualification-preservation weakness**, rather than random run-to-run noise.

---

## 7. Recurring Strengths

### Candidate A

- Strong evidence grounding and source traceability.
- Stable separation between national evidence and Medibank-specific interpretation.
- Strong relevance and priority reasoning across all three runs.
- Broad and decision-relevant finding coverage.
- Strong follow-up and monitoring questions.
- Best observed concision/efficiency in A3.

### Candidate B

- Strong evidence grounding and source traceability.
- Stable separation between national evidence and Medibank-specific interpretation.
- Strong relevance and priority reasoning across all three runs.
- Strong handling of exact versus rounded quantitative evidence and known data gaps.
- Useful follow-up and monitoring recommendations.
- Excellent numerical consistency across all three runs.

---

## 8. Repeated-Run Stability Assessment

### Candidate A — Strong

Rationale:
- no Hard Gate FAIL across A1–A3;
- same overall relevance and priority judgement in all three runs;
- stable principal evidence and Medibank boundary;
- stable reasoning quality;
- small score range of 3.34 points;
- variation mainly due to improved output efficiency in A3.

### Candidate B — Strong

Rationale:
- no Hard Gate FAIL across B1–B3;
- same overall relevance and priority judgement in all three runs;
- stable principal evidence and Medibank boundary;
- identical weighted quality score in all three runs;
- identical dimension-level scoring across all three runs.

Candidate B was the more numerically consistent candidate on this specific case.

---

## 9. Dementia Development-Case Conclusion

Both Candidate A and Candidate B demonstrated strong and highly similar performance on the frozen AIHW Dementia development case.

All six controlled executions:
- produced valid schema-conformant outputs;
- had no Hard Gate failures;
- produced stable **Relevant / Medium Priority** assessments;
- showed strong evidence grounding;
- showed strong relevance and priority reasoning;
- maintained the required Medibank evidence boundary; and
- produced useful follow-up recommendations.

Candidate A achieved a slightly higher mean quality score (**94.44 vs 93.33**), driven solely by stronger clarity/concision in one run.

Candidate B demonstrated perfect numerical score stability across its three runs.

Both candidates shared the same recurring weakness in not explicitly preserving the estimated/modelled status of the DALY burden measure.

**Therefore, the Dementia case does not provide sufficient evidence to declare a final Prompt v1 winner.**

Additional human-labelled ABS/AIHW cases are required to test:
- generalisation;
- discrimination between the candidate prompts;
- performance on different evidence structures;
- performance on uncertain or borderline cases; and
- performance where optional quantitative metrics are supplied.

---

## 10. Recommended Next Step

Proceed to **Gold Standard v0 — additional cases**.

Suggested sequence:

1. Keep the completed AIHW Dementia case as the first gold-standard case.
2. Add at least one additional AIHW publication.
3. Add at least one ABS publication.
4. Create human relevance, priority and important-finding reference judgements.
5. Reconcile differences between team members.
6. Ask Amy to verify only uncertain or borderline cases where stakeholder judgement is especially valuable.
7. Execute Candidate A and Candidate B on the additional cases.
8. Compare performance against the human-labelled references.
9. Use the expanded evidence base to decide whether one candidate should become Prompt v1 or whether a revision is required.

---

## 11. Concise Meeting Summary

| | Candidate A | Candidate B |
|---|---:|---:|
| Controlled runs | 3 | 3 |
| Mean rubric score | **94.44 / 100** | **93.33 / 100** |
| Score range | 3.34 | **0.00** |
| Hard Gate failures | **0** | **0** |
| Stability | **Strong** | **Strong** |
| Relevance result | Relevant × 3 | Relevant × 3 |
| Priority result | Medium × 3 | Medium × 3 |
| Main difference | Slightly better concision in A3 | Perfect numerical consistency |
| Shared issue | DALY estimated/modelled qualification not explicit | Same |

### Suggested Spoken Update

For the relevance and prioritisation work, the first controlled evaluation is now complete using the frozen AIHW Dementia case. Two independently designed candidate prompts were each executed three times under the same model, source snapshot and settings. A frozen evaluation rubric was used, and the six outputs were anonymised before formal scoring.

Both candidates performed strongly. Neither had any Hard Gate failures, and both produced the same Relevant and Medium Priority judgement across all three runs. Candidate A averaged 94.44 out of 100, while Candidate B averaged 93.33. Candidate A showed a small advantage in concision in one run, while Candidate B was completely stable across all three runs.

Both candidates also showed the same recurring weakness: they did not explicitly preserve that the DALY burden result was estimated/modelled.

The Dementia case therefore supports both candidates as strong and stable, but it is not enough to select a final Prompt v1. The next step is to expand the human-labelled gold standard using additional ABS and AIHW cases and test which candidate generalises better.
