# Priority Prompt Evaluation Research

Research and evaluation artefacts for the RMIT–Medibank relevance/prioritisation prompt workstream.

## Scope

This folder records **how the prioritisation prompt was developed and evaluated**, rather than only storing the final implementation. It contains:

- reproducible source-preparation tooling used for controlled experiments;
- frozen evaluation requirements and output schema;
- two independently designed candidate prompts;
- the complete available Case 1 frozen input, reference answer and six blinded outputs;
- the evaluation rubric and rubric-audit artefacts;
- the deterministic evaluation harness used for JSON/schema validation, integrity checking and blinded anonymisation;
- the completed Case 2 and cross-case evaluation artefacts.

The source-automation code here is **research support tooling**. It is not the project's production source-extraction module; that module is owned by another teammate/workstream.

## Experimental design

Candidate A was designed with Claude Opus 5 (Medium reasoning) and Candidate B with GPT-6 Astra (Medium reasoning). Each candidate was executed repeatedly under the same controlled executor setup, outputs were blinded before rubric-based scoring, and candidate identity was revealed only after scoring. The same method was then applied to a second ABS case to test generalisation and stability.

See `docs/EXPERIMENT_METHOD.md` for the workflow and `docs/RUN_MAPPINGS.md` for the post-scoring unblinding mappings.

## Current experiment status

The two completed cases showed different reliability profiles. The cross-case work did **not** freeze a final Prompt v1 winner; another held-out case was recommended before final candidate selection. This repository therefore preserves the evaluation evidence rather than presenting one historical candidate as a definitively selected final prompt.

## Directory structure

```text
priority-prompt-evaluation/
├── README.md
├── .gitignore
├── docs/
│   ├── EXPERIMENT_METHOD.md
│   ├── RUN_MAPPINGS.md
│   ├── PROVENANCE.md
│   └── MISSING_FILES.md
├── source_preparation/
│   ├── README.md
│   └── source_automation/
│       ├── README_Source_Automation_v0.2.2.md
│       ├── requirements_source_capture.txt
│       └── src/
│           ├── capture_source.py
│           ├── freeze_source.py
│           └── new_case.py
├── prompt_design/
│   └── candidates/
│       ├── Prompt_v1_Candidate_A_Claude_Opus5_Medium.md
│       └── Prompt_v1_Candidate_B_GPT6_Astra_Medium.md
├── evaluation_framework/
│   ├── Prompt_v1_Acceptance_Criteria_v0.md
│   ├── Medibank_LLM_Relevance_Priority_Schema_v1_corrected.json
│   ├── Prompt_v1_Evaluation_Rubric_v1.md
│   ├── Prompt_v1_Evaluation_Rubric_v1_post_audit.md
│   └── rubric_audit_prompt.md
├── evaluation_tools/
│   ├── README.md
│   ├── requirements.txt
│   └── harness.py
├── cases/
│   ├── case_01_aihw_dementia/
│   │   ├── input/
│   │   ├── reference/
│   │   ├── blinded_outputs/
│   │   └── evaluation/
│   └── case_02_abs_acute_respiratory/
│       ├── input/
│       ├── reference/
│       ├── blinded_outputs/
│       └── evaluation/
└── cross_case/
```

## Deterministic evaluation harness

`evaluation_tools/harness.py` preserves the original Evaluation Harness v0.1 used to validate and anonymise controlled candidate runs before human/LLM rubric scoring. It checks required files, hashes raw outputs, validates JSON and the frozen schema, creates seeded anonymous copies, records a private mapping, and builds a blinded package. It does **not** perform the scoring itself.

The v0.1 script is intentionally preserved as a historical artefact and is configured around the Case 2 filenames. See `evaluation_tools/README.md` before reusing it for another case.