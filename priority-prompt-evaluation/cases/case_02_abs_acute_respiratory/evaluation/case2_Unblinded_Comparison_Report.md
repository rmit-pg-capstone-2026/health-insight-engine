I used `private_mapping.json` only to unblind Output_01–Output_06, and all scores, Hard Gate results, relevance labels, priority labels, strengths, weaknesses, and error descriptions below come unchanged from the frozen blinded evaluation. No rescoring or reinterpretation of individual runs was performed.  

## A. Unblinded mapping table

| Blinded Output | Original Run                    | Candidate   |    Score | Hard Gate status                 | Relevance | Priority        |
| -------------- | ------------------------------- | ----------- | -------: | -------------------------------- | --------- | --------------- |
| Output_01      | Case2_B2_GPT6_Astra_Medium.md   | Candidate B | **86.7** | **HG-4 REVIEW; all others PASS** | Relevant  | Medium Priority |
| Output_02      | Case2_A1_Claude_Opus5_Medium.md | Candidate A | **93.3** | **All PASS**                     | Relevant  | Informational   |
| Output_03      | Case2_A2_Claude_Opus5_Medium.md | Candidate A | **88.3** | **All PASS**                     | Relevant  | Informational   |
| Output_04      | Case2_B3_GPT6_Astra_Medium.md   | Candidate B | **86.7** | **HG-4 REVIEW; all others PASS** | Relevant  | Medium Priority |
| Output_05      | Case2_B1_GPT6_Astra_Medium.md   | Candidate B | **86.7** | **HG-4 REVIEW; all others PASS** | Relevant  | Medium Priority |
| Output_06      | Case2_A3_Claude_Opus5_Medium.md | Candidate A | **60.0** | **HG-4 FAIL; all others PASS**   | Relevant  | Informational   |

The mapping above follows the private mapping exactly.  The scores and labels are exactly those recorded in the blinded evaluation. 

---

## B. Candidate A aggregate

### Deterministic results

| Measure                     | Candidate A |
| --------------------------- | ----------: |
| A1 score                    |    **93.3** |
| A2 score                    |    **88.3** |
| A3 score                    |    **60.0** |
| Mean weighted score         |   **80.53** |
| Minimum                     |    **60.0** |
| Maximum                     |    **93.3** |
| Score range                 |    **33.3** |
| Population SD of run scores |   **14.66** |

### Quality Dimension means

| Quality Dimension                                          | A1 | A2 | A3 |     Mean |
| ---------------------------------------------------------- | -: | -: | -: | -------: |
| QD-1 Important Finding Selection and Completeness          |  3 |  2 |  1 | **2.00** |
| QD-2 Evidence Grounding and Traceability                   |  3 |  3 |  2 | **2.67** |
| QD-3 Relevance Reasoning                                   |  3 |  3 |  3 | **3.00** |
| QD-4 Priority Reasoning and Calibration                    |  2 |  2 |  1 | **1.67** |
| QD-5 Uncertainty, Caveat and Unavailable-Evidence Handling |  3 |  3 |  2 | **2.67** |
| QD-6 Follow-up and Monitoring Usefulness                   |  3 |  3 |  2 | **2.67** |
| QD-7 Clarity, Concision and Output Efficiency              |  3 |  3 |  2 | **2.67** |

### Hard Gates and labels

At the **run level**, Candidate A produced **2 PASS, 0 REVIEW, 1 FAIL**. Across the 18 individual Hard Gate judgments, this corresponds to **17 PASS, 0 REVIEW, 1 FAIL**.

| Distribution | Result                 |
| ------------ | ---------------------- |
| Relevance    | **Relevant: 3/3**      |
| Priority     | **Informational: 3/3** |

The single failed gate was A3/Output_06's HG-4 failure for the materially incorrect `comparison_period`; the frozen evaluation explicitly states that its selected findings were still source-supported and that HG-2 passed. 

### Qualitative interpretation

Candidate A's strongest recurring feature is **relevance reasoning**: QD-3 was 3/3 in every run, HG-3 passed in every run, and all three executions maintained the distinction between national ABS mortality evidence and unknown Medibank-specific effects.

A1 and A2 were comparatively strong and clean executions, scoring 93.3 and 88.3 with all Hard Gates passing. The instability arises almost entirely from A3, where evidence-selection completeness fell to QD-1 = 1, priority calibration to QD-4 = 1, and HG-4 failed. The frozen evaluator specifically identified missing 2025 influenza comparator evidence, missing crossover evidence and missing quantified registration-lag evidence in A3.

Priority behaviour was nevertheless perfectly consistent at the label level: **all three A runs returned Informational**. The evaluation comments on A1 and A2 indicate that this label may underweight some elevated signals, while A3's priority reasoning was weakened by its narrower evidence selection. 

---

## C. Candidate B aggregate

### Deterministic results

| Measure                     | Candidate B |
| --------------------------- | ----------: |
| B1 score                    |    **86.7** |
| B2 score                    |    **86.7** |
| B3 score                    |    **86.7** |
| Mean weighted score         |   **86.70** |
| Minimum                     |    **86.7** |
| Maximum                     |    **86.7** |
| Score range                 |     **0.0** |
| Population SD of run scores |    **0.00** |

### Quality Dimension means

| Quality Dimension                                          | B1 | B2 | B3 |     Mean |
| ---------------------------------------------------------- | -: | -: | -: | -------: |
| QD-1 Important Finding Selection and Completeness          |  3 |  3 |  3 | **3.00** |
| QD-2 Evidence Grounding and Traceability                   |  3 |  3 |  3 | **3.00** |
| QD-3 Relevance Reasoning                                   |  3 |  3 |  3 | **3.00** |
| QD-4 Priority Reasoning and Calibration                    |  2 |  2 |  2 | **2.00** |
| QD-5 Uncertainty, Caveat and Unavailable-Evidence Handling |  2 |  2 |  2 | **2.00** |
| QD-6 Follow-up and Monitoring Usefulness                   |  3 |  3 |  3 | **3.00** |
| QD-7 Clarity, Concision and Output Efficiency              |  2 |  2 |  2 | **2.00** |

### Hard Gates and labels

At the **run level**, Candidate B produced **0 PASS, 3 REVIEW, 0 FAIL**. Across the 18 individual Hard Gate judgments, this corresponds to **15 PASS, 3 REVIEW, 0 FAIL**.

| Distribution | Result                   |
| ------------ | ------------------------ |
| Relevance    | **Relevant: 3/3**        |
| Priority     | **Medium Priority: 3/3** |

Every REVIEW was the same type of issue: HG-4 required review because the run included the all-deaths proportion evidence without surfacing the source's unresolved **30 June versus 31 July registration-cutoff inconsistency**. The frozen evaluator explicitly treated this as a local qualification omission rather than a confirmed material factual error. 

### Qualitative interpretation

Candidate B showed unusually high score-level stability: not only were all three totals exactly 86.7, but the entire seven-dimension score profile was identical in all three runs.

Its recurring strengths were broad finding selection, evidence grounding, relevance reasoning and follow-up usefulness. QD-1, QD-2, QD-3 and QD-6 were all 3.0 in every run.

Its most clearly recurring weakness was also completely stable: all three runs received QD-5 = 2 and HG-4 REVIEW for the same unresolved cutoff caveat. QD-7 was also consistently 2. Priority behaviour was fully stable at **Medium Priority**, although the frozen evaluator repeatedly noted that this was somewhat stronger than the reference benchmark or that the reasoning itself read more like monitoring/investigation than a clearly stronger priority signal. 

---

## D. Side-by-side comparison

| Comparison area                      | Candidate A                                                                                              | Candidate B                                                                                                                 | Basis                                                                                                            |
| ------------------------------------ | -------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| **Overall quality**                  | Mean **80.53**                                                                                           | Mean **86.70**                                                                                                              | **Deterministic:** B's mean is **6.17 points higher**                                                            |
| **Run-to-run consistency**           | 93.3 / 88.3 / 60.0; range **33.3**; SD **14.66**                                                         | 86.7 / 86.7 / 86.7; range **0.0**; SD **0.00**                                                                              | **Deterministic:** substantially different score stability                                                       |
| **Hard Gate reliability**            | **2 PASS, 0 REVIEW, 1 FAIL**                                                                             | **0 PASS, 3 REVIEW, 0 FAIL**                                                                                                | **Deterministic:** A has more completely clean runs but one FAIL; B has no FAIL but recurring REVIEW             |
| **Factual/evidence reliability**     | HG-2 PASS in all 3; QD-2 mean **2.67**; A3 has material temporal metadata error under HG-4               | HG-2 PASS in all 3; QD-2 mean **3.00**; no confirmed material factual error                                                 | Deterministic scores plus frozen evaluator findings                                                              |
| **Relevance consistency**            | Relevant **3/3**; QD-3 **3.00**                                                                          | Relevant **3/3**; QD-3 **3.00**                                                                                             | **Deterministic:** identical consistency                                                                         |
| **Priority calibration consistency** | Informational **3/3**; QD-4 mean **1.67**                                                                | Medium Priority **3/3**; QD-4 mean **2.00**                                                                                 | **Deterministic:** each candidate is internally 100% label-consistent, but the candidates systematically diverge |
| **Recurring strengths**              | Strong relevance boundary; explicit uncertainty/unknown Medibank effects; strong A1/A2 evidence handling | Broad evidence selection; high traceability; strong relevance reasoning; useful follow-up                                   | **Qualitative interpretation** of frozen evaluator comments                                                      |
| **Recurring weaknesses**             | Conservative Informational calibration; evidence-selection robustness drops materially in A3             | Repeated all-deaths cutoff caveat omission; Medium calibration repeatedly stronger than benchmark; QD-5/QD-7 consistently 2 | **Qualitative interpretation** of frozen evaluator comments                                                      |

One important distinction is that **Hard Gate reliability does not reduce to a single simple ordering**. Candidate A had two completely clean PASS runs but also the only FAIL. Candidate B never failed a Hard Gate, but every run reproduced the same REVIEW-worthy qualification omission. That is a different reliability profile rather than the same type of failure at a different frequency.

For priority, both candidates are internally stable but systematically separated: **A = Informational in all three runs; B = Medium Priority in all three runs**. The frozen reference benchmark was **Watchlist**, and the blinded evaluation explicitly says the different labels were not automatically treated as errors because there was no universal fixed threshold. 

---

## E. Run-to-run stability analysis

### Deterministic stability

Candidate A follows:

**A1 93.3 → A2 88.3 → A3 60.0**

The first two runs differ by only 5.0 points, but A3 is 28.3 points below A2 and 33.3 points below A1. The quality-dimension pattern explains the drop. QD-3 remains fixed at 3 across all three runs, but A3 declines relative to A1/A2 in QD-1, QD-2, QD-4, QD-5, QD-6 and QD-7. QD-1 falls from 3 → 2 → 1 across A1–A3.

Candidate B follows:

**B1 86.7 → B2 86.7 → B3 86.7**

The weighted score, every QD score, overall Hard Gate status, relevance label and priority label are identical across all three executions. This is therefore perfect stability on the frozen quantitative measures. The individual evidence selections were not literally identical—the evaluator notes some different omissions among B1, B2 and B3—but those differences did not change any frozen dimension score or label.

### Interpretation

Candidate A demonstrates that its relevance decision was robust even when the breadth and temporal handling of evidence deteriorated: `Relevant` remained unchanged and QD-3 stayed at 3, while overall quality fell substantially in A3.

Candidate B demonstrates much stronger **score-profile reproducibility**, but it also reproduced the same caveat-handling problem three times. Its stability therefore includes both strengths and a recurring weakness.

The priority results reveal a separate kind of stability: there is **perfect within-candidate consistency but strong between-candidate divergence**. That suggests the candidate prompt formulation materially affects where identical evidence is placed on the priority scale, even though both consistently agree on relevance. This is an interpretation of the frozen pattern, not a rescoring. 

---

## F. Concise conclusions supported only by the frozen blinded evaluation

**Deterministically**, Candidate A scored **93.3, 88.3 and 60.0**, for a mean of **80.53** and a **33.3-point range**. Candidate B scored **86.7 in all three runs**, for a mean of **86.70** and a **0.0-point range**. Candidate A produced two completely passing runs and one HG-4 failure; Candidate B produced three HG-4 review runs and no failures. Both candidates returned `Relevant` in all three executions. Candidate A returned `Informational` three times, while Candidate B returned `Medium Priority` three times.

**Qualitatively**, Candidate A's main advantage in the frozen runs is that A1 and A2 were clean all-PASS executions with strong caveat handling, but its A3 run shows substantial downside instability in evidence completeness, temporal fidelity and priority calibration. Candidate B is much more reproducible across runs and consistently strong on finding selection, evidence grounding, relevance and follow-up, but it also reproduces the same HG-4 caveat omission every time. Priority calibration remains the clearest systematic difference between the two candidate prompt families: A consistently calibrates toward `Informational`, while B consistently calibrates toward `Medium Priority`; neither produced the frozen reference's `Watchlist`. 

These results characterize the two candidates under the frozen Case 2 evaluation only; they do not add any criterion or candidate recommendation beyond that evaluation.
