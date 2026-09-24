# Source preparation tooling

This directory contains **research/evaluation support tooling owned by the prompt-evaluation workstream**.

Its purpose is to capture and freeze reproducible public-source inputs for controlled prompt experiments. It is **not** the team's production ABS/AIHW extraction or ingestion module. Another project workstream owns the actual source-extraction pipeline used by the integrated system.

The included `source_automation` bundle is version `v0.2.2`. It preserves raw source evidence, creates frozen test inputs, records hashes/version metadata, and handles interactive-source gaps conservatively so prompt evaluations can be repeated against stable evidence.
