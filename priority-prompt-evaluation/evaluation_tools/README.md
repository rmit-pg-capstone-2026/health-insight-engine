# Evaluation Tools

This folder contains deterministic tooling used to prepare blinded prompt-evaluation packages.

## `harness.py`

`harness.py` is the original Medibank Evaluation Harness v0.1 used for the controlled A/B evaluation workflow. It performs deterministic checks and packaging only; it does **not** score outputs with an LLM.

It performs:

- required-file checks;
- SHA-256 hashing of raw outputs;
- JSON extraction and parsing checks;
- JSON Schema validation using Draft 2020-12;
- seeded randomisation of six candidate runs;
- byte-for-byte anonymous copies named `Output_01.md` to `Output_06.md`;
- creation of a private candidate-to-output mapping;
- generation of a validation report; and
- creation of a blinded scoring package that excludes candidate identity and the private mapping.

### Historical scope

The checked-in v0.1 script is preserved unchanged as an experimental artefact. Its required filenames are configured for **Case 2 — ABS Acute Respiratory**, including `Case2_A1_...` through `Case2_B3_...`. It should therefore be read as the historical harness used for that case rather than as a fully generic production framework.

If the team later wants a reusable harness for additional cases, create a new version that reads case configuration from a file instead of changing this historical copy in place.

### Dependency

```bash
pip install -r requirements.txt
```

### Historical invocation pattern

```bash
python harness.py <case_directory> --seed <integer>
```

The case directory is expected to contain `frozen/`, `raw_outputs/`, and a generated `generated/` directory. Keep `private_mapping.json` away from blinded evaluators until scoring is complete.
