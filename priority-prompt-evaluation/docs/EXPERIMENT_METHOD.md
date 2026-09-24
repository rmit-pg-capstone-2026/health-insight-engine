# Prompt v1 evaluation method

## Purpose

Develop and evaluate a relevance/prioritisation prompt for the RMIT–Medibank healthcare intelligence project using controlled, reproducible evidence rather than selecting a prompt from a single attractive output.

## Workflow

1. Capture a public ABS/AIHW source and freeze the evidence used for testing.
2. Build a human-verified reference answer for the frozen source.
3. Freeze acceptance criteria and an output schema before formal comparison.
4. Create two independently designed prompt candidates:
   - Candidate A — Claude Opus 5, Medium reasoning.
   - Candidate B — GPT-6 Astra, Medium reasoning.
5. Execute each candidate three times under controlled conditions using the same executor model/settings used for the experiment (GPT-5.6 Sol, Medium reasoning).
6. Rename/randomise the six outputs to blinded `Output_01`–`Output_06` files.
7. Score the blinded outputs against the frozen evaluation rubric and hard gates.
8. Unblind only after scoring is complete.
9. Repeat on a second source with a different evidence structure.
10. Compare repeated-run stability, evidence grounding, caveat preservation, relevance reasoning and priority calibration across cases.

## Why the models have different roles

The prompt-design model, execution model and evaluation/audit model are intentionally treated as separate roles. The A/B comparison is about the behaviour induced by the candidate prompts under a common execution setup, not about the reputation of the model that drafted each prompt.

## Current status

The first two cases identified meaningful differences between the candidates, especially around run-to-run stability, caveat preservation and priority calibration. The cross-case synthesis did **not** freeze a final Prompt v1 winner; it recommended another held-out case before final candidate selection.

## Relationship to the production pipeline

This repository area is research/evaluation evidence. The current integrated prioritisation implementation belongs in the project's implementation branch/module. Source-capture tooling here exists to make the experiments reproducible and should not be confused with the teammate-owned production source-extraction component.
