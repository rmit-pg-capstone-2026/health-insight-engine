# Provenance notes

## Case 1

- Source: AIHW, *Dementia in Australia — Summary*.
- Frozen test-input version: `AIHW_Dementia_Summary_Test_Input_v1.md`.
- Human-verified reference: `AIHW_Dementia_Summary_Reference_Answer_v1.md`.
- Six blinded controlled outputs are included.

## Case 2

- Source: ABS, *Deaths due to acute respiratory infections in Australia, July 2026*.
- Frozen input and evaluation files are listed in `MISSING_FILES.md` for restoration.

## Source automation

- Included version: `Medibank Source Automation v0.2.2`.
- The bundle deliberately excludes `__pycache__` / compiled Python files.
- No API key or credential file is included.

## Version-control intent

This archive is intended for a separate research branch such as:

`research/priority-prompt-evaluation`

It should remain distinct from the production source-extraction work owned by another teammate and from the current integrated prioritisation implementation unless the team later chooses to merge selected documentation/evaluation artefacts.
