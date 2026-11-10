---
name: results-json-crash-tolerance
description: "Deep dive: load_report salvages a results.json truncated by a mid-run crash"
metadata:
  type: reference
  audience: agents
  maturity: stable
---
# Results Json Crash Tolerance

## A crashed lane leaves a truncated results.json

behave's JSON formatter writes each completed feature in `eof()` but appends the
closing `]` of the top-level array only in `close()`. A lane that crashes mid-run
therefore leaves a `results.json` that is valid JSON for the features captured so
far but is missing the footer. The possible shapes:

- `[` plus N complete feature objects and no closing `]` (crash between the last
  feature's `eof()` write and `close()`).
- N complete objects plus a truncated final object (crash mid-write of the last
  feature).
- A trailing comma with no following object (`[...,]` → `[,...,`).
- An empty or 0-byte file (nothing was written).

An unguarded `json.loads()` on any of these raises `JSONDecodeError`, which fails
the summarise step for the wrong reason — a crash / "No results generated" — instead
of reporting the real pass/fail state. (The "No results generated" in
projectbluefin/testsuite#604 comes from a separate `json.load` in
`projectbluefin/lab`'s `run-container-tests.yaml`, which this loader does not
cover.)

## `load_report()` salvages the complete objects

`load_report()` in `scripts/e2e_summary.py` is the crash-tolerant entry point:

```python
def load_report(text: str) -> tuple[list[dict[str, Any]], bool]:
    try:
        report = json.loads(text)
    except json.JSONDecodeError:
        return _salvage_partial(text), False
    if not isinstance(report, list):
        return [], False
    return report, True
```

It returns `(report, complete)`. On a clean document `report` is exactly what
`json.loads` would return and `complete` is `True`. On a
`JSONDecodeError` it delegates to `_salvage_partial()`, which walks the array with
`JSONDecoder.raw_decode()` and collects every complete feature object while dropping
any truncated tail:

```python
def _salvage_partial(text: str) -> list[dict[str, Any]]:
    decoder = json.JSONDecoder()
    pos = 0
    length = len(text)
    report: list[dict[str, Any]] = []
    while pos < length:
        while pos < length and text[pos].isspace():
            pos += 1
        if pos >= length:
            break
        char = text[pos]
        if char == "[" or char == ",":
            pos += 1
            continue
        try:
            obj, end = decoder.raw_decode(text, pos)
        except json.JSONDecodeError:
            break
        report.append(obj)
        pos = end
    return report
```

`load_report()` never raises: an empty, whitespace-only, or non-array document
yields `([], False)`, and a salvaged document yields the recovered features with
`complete=False`.

## A salvaged report is never green

Salvage drops the feature that was running when the lane died, so the surviving
features can all have passed while the run did not. Every reader therefore treats
`complete=False` as INCOMPLETE: a ✅ headline becomes ⚠️ with an
"INCOMPLETE (results truncated)" note, and a ❌ stays ❌. Separately,
`is_success()` is `False` when no scenario was counted at all, so an empty report
renders ⚠️ rather than ✅.

## Every reader uses `load_report()`

- `.github/actions/gnome-e2e/action.yml` — the `Summarise results` step, which
  prints `E2E INCOMPLETE` and the truncation note when `complete` is `False`.
- `.github/workflows/e2e.yml` — the `Write job summary` step.
- `Justfile` — the `results` recipe (marks a truncated suite ⚠️ `INCOMPLETE`) and
  the `compare-results` recipe (`scenario_statuses(load_report(...)[0])`).
- `scripts/e2e_summary.py` `main()` — the CLI reads
  `load_report(args.results_json.read_text())`.

The behaviour is unit tested in `tests/unit/test_e2e_summary.py` (`test_load_report_*`).
