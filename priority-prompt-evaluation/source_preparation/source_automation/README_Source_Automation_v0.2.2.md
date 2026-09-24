# Medibank Source Automation v0.2.2

This bundle standardises source capture and freezing for the RMIT–Medibank
LLM relevance/prioritisation evaluation pipeline.

It is designed to sit beside the existing validated `harness.py`.
It does **not** modify the evaluation harness.

## Why v0.2.2 exists

The v0.1.1 regression test against the authoritative AIHW Dementia Case-1
snapshot showed that ordinary HTML-to-Markdown capture preserved the main
narrative and normal HTML tables well, but could miss evidence exposed through
interactive AIHW figures/charts.

v0.2.2 keeps the existing ABS-friendly capture path and adds a targeted
interactive-content layer.

## Main changes in v0.2.2

- Keeps the existing raw HTML/PDF snapshot and normal Markdown conversion.
- Detects iframes, rich visualisation containers, figure headings and
  downloadable table/CSV controls before page-service elements are removed.
- When interactive content requires it, renders the live URL with Playwright
  Chromium and captures:
  - accessible visualisation text;
  - exposed control/state labels;
  - rendered HTML tables;
  - downloadable table/CSV link candidates;
  - rendered figure sections.
- Does **not** estimate numbers from chart geometry, line positions or bar
  heights.
- Adds interactive capture status to `source_metadata.json`.
- Blocks freezing when required interactive evidence is not fully captured,
  unless the remaining gap has been manually verified and explicitly
  acknowledged.
- Separates AIHW "last updated" metadata from publication/release date rather
  than copying one date into both fields.
- Preserves an AIHW visible version date/version where the page exposes one.

The frozen Test_Input still has the controlled structure:

```text
# Frozen Source Test Input

## Snapshot metadata
...

## Source content
...
```

Capture notes, hashes and verification warnings remain outside the final
experimental input.

## Installation

### Python compatibility

The requirements file is version-pinned for the browser dependency:

- Python 3.9: Playwright 1.54.0 + greenlet 3.1.1
- Python 3.10+: Playwright 1.62.0

This avoids Python 3.9 falling back to a local C/C++ build of `greenlet` on
Windows. Microsoft C++ Build Tools are **not required** for the normal install.

Before installing dependencies, upgrade the packaging tools:

```powershell
py -m pip install --upgrade pip setuptools wheel
```

Install Python dependencies:

```powershell
py -m pip install -r requirements_source_capture.txt
```

Install the Chromium runtime used only when interactive rendering is needed:

```powershell
py -m playwright install chromium
```

## Case 2 / ABS workflow

The Case 2 ABS workflow remains the same.

### 1. Create the case

```powershell
py new_case.py abs_acute_respiratory_2026_07
```

### 2. Capture the official ABS page

```powershell
py capture_source.py cases\abs_acute_respiratory_2026_07 --url "https://www.abs.gov.au/statistics/health/causes-death/deaths-due-acute-respiratory-infections-australia/jul-2026"
```

If the page contains no rich interactive evidence requiring browser rendering,
the flow remains the lightweight requests + BeautifulSoup + Markdown path.

### 3. Verify the draft

Open:

```text
cases\abs_acute_respiratory_2026_07\source\Test_Input_draft.md
```

Compare it with the preserved raw source.

### 4. Freeze

```powershell
py freeze_source.py cases\abs_acute_respiratory_2026_07 --approve
```

This creates:

```text
frozen/
├── raw_source_snapshot_v1.html
├── abs_acute_respiratory_2026_07_Test_Input_v1.md
└── source_manifest_v1.json
```

Use the frozen `*_Test_Input_v1.md` for the same downstream pipeline used for
the Dementia case.

## Future AIHW workflow

Create and capture the case in the same way:

```powershell
py new_case.py aihw_example_case
py capture_source.py cases\aihw_example_case --url "PASTE_OFFICIAL_AIHW_URL"
```

The capture script will report one of these interactive states:

- `NOT_REQUIRED` — ordinary capture was sufficient.
- `COMPLETE` — required interactive evidence was rendered and exposed in a
  machine-readable/accessibility form.
- `PARTIAL` / `UNRESOLVED` / `ERROR` / `DEPENDENCY_MISSING` — human review is
  required before freezing.

If interactive evidence is fully captured and the draft is verified:

```powershell
py freeze_source.py cases\aihw_example_case --approve
```

If the script reports an unresolved interactive gap, normal freezing is
blocked. First review the live rendered page and supplement/verify the draft.
Only if the remaining gap is understood and intentionally accepted should you
use the explicit override:

```powershell
py freeze_source.py cases\aihw_example_case --approve --approve-interactive-gaps
```

The override is written into `source_manifest_v1.json` for auditability.

## Case 1 / Dementia

Do **not** regenerate the already-authoritative Case 1 input from the live AIHW
page for controlled evaluation.

Import the exact original experimental Test_Input byte-for-byte:

```powershell
py freeze_source.py cases\dementia_v1 --legacy-input "C:\path\AIHW_Dementia_Summary_Test_Input_v1.md" --approve
```

This remains unchanged from v0.1.1.

## Important limitations

Browser rendering improves capture fidelity, but it does not guarantee that
every third-party visualisation exposes all underlying values. If an AIHW chart
only draws graphical marks and exposes no table/accessibility data, the tool
must leave that evidence unresolved rather than infer values.

The human verification step therefore remains part of the controlled source
freezing workflow.

## Versioning rule

Do not silently overwrite a frozen input already used in a controlled
experiment. If an existing `v1` has been used experimentally, keep it immutable
and create an explicit `v2` only when the source/input genuinely changes.
