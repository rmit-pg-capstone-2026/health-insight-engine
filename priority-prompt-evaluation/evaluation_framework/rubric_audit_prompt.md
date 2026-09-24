PROJECT STATE

This rubric was produced after a controlled Run-1 evaluation of two candidate
LLM relevance/prioritisation prompts for the RMIT–Medibank project.

The candidate outputs are intentionally NOT supplied for this task.

This task is only an independent pre-freeze audit of the rubric.

Use only the attached frozen project artifacts as authoritative input.
Do not broaden the task, browse externally, or redesign the evaluation process.

You are performing an independent pre-freeze audit of an evaluation rubric for
the RMIT–Medibank AI-Powered Clinical, Pharmaceutical and Medical Insights
project.

==================================================
AUTHORITATIVE INPUTS
==================================================

Use ONLY the five attached files:

1. Prompt_v1_Evaluation_Rubric_v1.md
2. Prompt_v1_Acceptance_Criteria_v0.md
3. Medibank_LLM_Relevance_Priority_Schema_v1_corrected.json
4. AIHW_Dementia_Summary_Reference_Answer_v1.md
5. AIHW_Dementia_Summary_Test_Input_v1.md

The five attached files are the complete authoritative input for this audit.

If another file with the same or a similar filename exists elsewhere,
ignore it.

Do not browse the web.
Do not use outside healthcare knowledge.
Do not use information from previous chats.
Do not introduce requirements that are not supported by the supplied files.

==================================================
TASK
==================================================

Act as an independent evaluation-methodology auditor.

Review:

Prompt_v1_Evaluation_Rubric_v1.md

before it is frozen and used to score future candidate runs.

This is an AUDIT task, not a rubric-redesign task.

Do not:
- evaluate Candidate A or Candidate B;
- infer which candidate would benefit from any rubric change;
- create a replacement rubric from scratch;
- introduce external evaluation requirements;
- change project scope;
- optimise the rubric toward the Dementia reference answer specifically.

==================================================
CHECKS
==================================================

Audit the rubric for the following:

1. COVERAGE
Does it adequately cover the requirements in
Prompt_v1_Acceptance_Criteria_v0.md and the corrected JSON schema?

Identify any Acceptance Criterion that is:
- missing;
- only partially represented;
- represented incorrectly.

2. UNSUPPORTED REQUIREMENTS
Does the rubric introduce any hard gate, scored requirement, penalty, or
evaluation expectation that is not supported by the authoritative files?

3. HARD-GATE DESIGN
Are the six Hard Gates:
- logically distinct enough;
- appropriately classified as non-negotiable;
- using reasonable PASS / REVIEW / FAIL boundaries?

Flag anything that should instead be a scored-quality issue rather than a
Hard Gate.

4. SCORED DIMENSIONS
Review the seven scored quality dimensions for:
- overlap;
- ambiguity;
- missing important quality dimensions;
- scoring anchors that would be difficult to apply consistently;
- accidental double-penalisation of the same defect.

5. WEIGHTS
Assess whether the proposed weights are internally reasonable for the
project.

Do NOT propose alternative weights merely because another weighting scheme
is possible.

Only recommend a change if the current weighting creates a material
evaluation problem.

6. COMPLETENESS AND REFERENCE USE
Check that the rubric correctly reflects that:
- the human reference answer is an evaluation anchor rather than an
  exhaustive required finding set;
- more findings do not automatically mean a better output;
- valid source-supported findings not present in the human reference should
  not automatically be penalised.

7. REPEATED-RUN CONSISTENCY
Check whether the proposed three-run consistency method is practical and
internally coherent.

Identify any ambiguity that would make A1-A3 versus B1-B3 difficult to
compare consistently.

8. GENERALISATION
Check whether the rubric is sufficiently general for later ABS/AIHW cases
and is not overfitted to the Dementia development case.

==================================================
OUTPUT
==================================================

Return a concise Markdown audit containing:

# 1. Overall Audit Verdict

Choose one:

- READY TO FREEZE
- READY TO FREEZE WITH MINOR EDITS
- MATERIAL REVISION REQUIRED

Give a short justification.

# 2. Requirement Coverage Audit

List any missing, partial, duplicated, or incorrectly represented
Acceptance Criteria.

If none, say so explicitly.

# 3. Unsupported or Overfitted Requirements

List any rubric requirement that is unsupported or overly specific to the
Dementia case.

If none, say so explicitly.

# 4. Hard-Gate Audit

Identify only substantive issues.

# 5. Scored-Dimension and Weight Audit

Identify only substantive issues.

# 6. Consistency-Method Audit

Identify only substantive issues.

# 7. Required Edits Before Freeze

Provide a numbered list containing ONLY changes you believe are genuinely
necessary before freezing.

For each proposed edit give:
- current issue;
- why it matters;
- exact minimal correction.

Do not rewrite the entire rubric.

If no edit is necessary, state:

"No required edits before freeze."

# 8. Optional Improvements

Include only genuinely optional refinements and clearly distinguish them
from required changes.

==================================================
FINAL CONSTRAINT
==================================================

Be conservative.

Do not recommend changes merely because you prefer a different evaluation
style.

The purpose is to determine whether the existing rubric is sufficiently
sound and faithful to the frozen project requirements to be frozen and used,
not to maximise theoretical methodological sophistication.