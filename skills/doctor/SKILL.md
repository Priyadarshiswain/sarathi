---
name: doctor
description: Check or set up the Sarathi environment — Python, git, config validity, project roots, output path. Reports exactly what is broken with its exact fix, and offers guided first-time setup when no config exists or an existing one is stale. Use when the user asks to diagnose, fix, set up, or migrate Sarathi.
allowed-tools: Bash, Read, Write, AskUserQuestion
---

# Sarathi doctor

You are running Sarathi's self-diagnosis and, when needed, guided setup. The
script is the only authority on what is broken and on the branch decision —
never invent, soften, reorder, or recompute what it reports.

## 0. Resolve which Python invoker to run the script with

Config lives at `$CLAUDE_CONFIG_DIR/sarathi/config.json` if `$CLAUDE_CONFIG_DIR`
is set, otherwise `~/.claude/sarathi/config.json`. This is a separate,
independent resolution mechanism from `${CLAUDE_PLUGIN_ROOT}` (where the
plugin's own code, including `sarathi.py`, lives) — never conflate the two.

- **If that config.json exists, is parseable JSON, and has an `invoker` key**:
  use its value — an absolute path — directly for every `sarathi.py`
  invocation in this run. Do **not** re-run the bootstrap heuristic below;
  a stored invoker is never re-guessed.
  - **Stale-invoker recovery:** before trusting it, confirm it actually runs
    (e.g. `<stored invoker> --version`). If it fails to execute at all (the
    path no longer exists — for example a Python upgrade moved it), do not
    silently substitute a different Python and continue. Treat this as a
    config problem: say so explicitly — "stored invoker no longer exists at
    `<path>`" — and go straight to the **init** flow (§4) to re-prove and
    re-store the invoker, preserving every other config value unchanged
    (§4, criterion 21). This is the one case where you jump to init without
    first seeing `branch: "init"` from the script, precisely because the
    stored invoker being broken means you cannot even run the script to ask
    it.
- **Otherwise** (no config yet, or config unreadable) — this is **pre-config
  bootstrap only**, used exactly once before any config exists to read an
  invoker from: try `python3` on PATH, then `python`. If neither runs, report
  that Python 3.8+ is required and stop. Once `init` has proven and stored an
  `invoker` (§4d), every later `doctor`/`report` run uses that stored path
  and never falls back to this heuristic again.

## 1. Run the diagnosis

```bash
<invoker> "${CLAUDE_PLUGIN_ROOT}/sarathi.py" doctor --json
```

Parse the JSON. It carries a top-level `branch` field —
`"proceed" | "init" | "stop"` — computed entirely by the script from the
per-check statuses. Read it; never re-derive or second-guess it.

## 2. Report by branch

Show every check with its `status` (`ok` / `failed` / `empty`) and the
script's own `detail`. Do not omit `empty` rows and do not dress a `failed`
check as a mere warning — "couldn't look" is never "nothing found."

### `branch: "proceed"`

All green. Say so, and suggest `/sarathi:report` as the next step.

### `branch: "stop"`

Some check *other than* `config` failed — an environment problem (bad Python
version, missing git, an unreadable project root, etc.). Environment
problems always outrank a config problem: init cannot fix a missing `git` or
an unreadable root, and attempting it would mask the real fix. Print every
failed check's `name` and `detail` **verbatim** — no paraphrase, no
softening — and offer nothing else. Do not attempt init.

### `branch: "init"`

Only the `config` check failed — whether because config.json doesn't exist,
is unparseable, or its schema is stale or malformed. Proceed to guided setup.

## 3. Guided setup entry (`init`)

Offer to run guided setup. If the user agrees, continue to §4. Report the
`config` check's own `detail` first, verbatim, so the user sees exactly why
setup is being offered (rule 2 — never soften even on the way into a helpful
flow).

## 4. Init: prove every answer before writing config.json

Rule 3 governs this whole section: every proof below reuses `sarathi.py`'s
own functions and doctor checks (imported and invoked via `python -c`, never
reimplemented). You write **exactly one file**, config.json, and only after
every proof below passes.

### 4a. Fresh setup or migration?

Try to Read `$CLAUDE_CONFIG_DIR/sarathi/config.json` (or
`~/.claude/sarathi/config.json`) directly.

- **If it exists and parses as JSON with `project_roots` and `output_path`
  present** (regardless of `schema_version` — this covers the stale-v1 case
  and the stale-invoker recovery case from §0): this is a **migration**.
  Preserve `project_roots` and `output_path` **unchanged, byte-for-byte** —
  never re-propose or re-ask for them. Continue only to whatever is missing:
  `voice` (always ask — v1 configs never had it, and stale-invoker recovery
  should keep the existing voice if it's already valid, only re-asking if it
  is absent or invalid) and `invoker` (always re-prove, per §4d).
- **Otherwise** (no config file, or one unparseable/missing those two keys
  entirely): this is a **fresh init**. Continue to §4b for both roots and
  voice.

### 4b. The one question: voice

Ask exactly one `AskUserQuestion` — Sarathi's design rule 4: questions exist
only for what data can't answer, and no scan can observe how someone wants
to be spoken to (not inferred from writing style; both the user's own memory
model and Sarathi's design-of-record independently rule out
author-profiling as unreliable and unwelcome). This is init's *only*
question — everything else in this section is proposed for confirmation,
never asked open-ended.

Ask: "How should `/sarathi:report` be written?" with exactly two options:
`plain` and `gen_z`.

Skip this question only in the migration case where the existing config
already has a valid `voice` value — reuse it unchanged.

### 4c. Project roots and output path (fresh init only)

Skip entirely when migrating (§4a already preserved these).

Proposed, not open-ended:
- **Project roots** — the **parent** directories whose children are
  projects (e.g. `~/Projects`), never a hand-listed set of individual
  projects. Check whether `~/Projects` exists on disk (e.g. `test -d
  ~/Projects` via Bash) and offer it as the recommended default if so.
  Confirm with the user rather than asking an open "what do you want"
  question.
- **Output path** — recommend `<config-dir>/sarathi/facts.json` (the same
  `<config-dir>` resolved in §0). Confirm similarly.

Expand `~` to the absolute home path yourself before storing — config always
stores absolute paths.

### 4d. Prove the invoker (criterion 12)

Try candidates in order: `python3`, `python`, `py`. For each:

```bash
<candidate> -c "import sys; sys.path.insert(0, '${CLAUDE_PLUGIN_ROOT}'); import sarathi; print(sarathi.python_version_ok(sys.version_info))"
```

This reuses `sarathi.py`'s own `python_version_ok()` — the same floor
`doctor`'s `python_version` check enforces (`THRESHOLDS["MIN_PYTHON_VERSION"]`)
— rather than hardcoding a version number in this skill. The first candidate
that both runs and prints `True` wins. Resolve it to its absolute path:

```bash
<candidate> -c "import sys; print(sys.executable)"
```

Store that **absolute path** — never the bare command word — as `invoker`.
If no candidate proves out, report which were tried and why each failed
(missing binary, version below the floor), and stop — do not write
config.json.

### 4e. Prove the slug round-trip (criterion 13, three-way semantics)

Pick one project actually discovered under the candidate/preserved
`project_roots` (list a root's immediate subdirectories via Bash `ls`, or
reuse `sarathi.py`'s own discovery):

```bash
<invoker> -c "import sys; sys.path.insert(0, '${CLAUDE_PLUGIN_ROOT}'); import sarathi; print(sarathi.slug_roundtrip_status('<config-dir>', ['<discovered child path 1>', '<discovered child path 2>', ...]))"
```

This reuses `sarathi.py`'s own `slug_roundtrip_status()` — the exact same
function `doctor`'s `session_slug_roundtrip` check calls internally — never
reimplement slug matching by hand. **Reviewer ruling, 2026-08-01, three-way
semantics:**

- `status: "ok"` (a matching session folder found) — proof passes.
- `status: "empty"` (no session folders exist for *any* discovered
  project) — this is **not a failure**. Record it as "nothing to prove
  against" and continue. A brand-new Claude Code user legitimately has zero
  session folders and must still be able to complete init.
- `status: "failed"` (the `projects/` directory itself is unreadable) — this
  **is** a real proof failure; do not write config.json (see §4f-fail).

### 4f. Prove output-path writability (criterion 14)

```bash
<invoker> -c "import sys; sys.path.insert(0, '${CLAUDE_PLUGIN_ROOT}'); import sarathi; print(sarathi.path_is_writable('<candidate output_path>'))"
```

This reuses `sarathi.py`'s own `path_is_writable()` — the same writability
probe `doctor`'s `output_writable` check performs (containing directory, or
its nearest existing ancestor, must be writable) — before writing anything
there.

### Any proof failing (criterion 15)

An `empty` slug proof (§4e) is not a failure and never blocks init. If the
invoker proof (§4d) or the writability proof (§4f) fails, or the slug proof
reports `failed`: do **not** write config.json. Report which proof failed
and why, in the underlying check's own words (rule 2 — never soften), and
either retry with a different candidate (a different Python, a different
output path) or stop. Never write an unproven answer.

### 4g. Write config.json (only once every proof above has passed)

Write exactly one file, `<config-dir>/sarathi/config.json`, with exactly
these keys:

```json
{
  "schema_version": 2,
  "project_roots": ["<absolute parent dir>", "..."],
  "output_path": "<absolute output path>",
  "voice": "<plain|gen_z>",
  "invoker": "<absolute resolved invoker path>"
}
```

On a migration, `project_roots` and `output_path` here are the values
preserved unchanged from §4a — not re-derived.

### 4h. Confirm, don't declare

Immediately re-run:

```bash
<invoker> "${CLAUDE_PLUGIN_ROOT}/sarathi.py" doctor --json
```

Confirm `branch` is now `"proceed"`. Report the fresh results and suggest
`/sarathi:report` as the next step. Do not chain directly into `report`
itself — that stays a separate skill invocation. Never declare setup done
on your own say-so; only the script's own re-run confirms it.
