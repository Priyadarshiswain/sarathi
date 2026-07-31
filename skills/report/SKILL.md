---
name: report
description: Run measure and produce a cited interpretation of your projects — moving, losing steam, forgotten — every claim traced back to the fact sheet just written. Use when the user asks for a status report, project review, or "what's going on with my projects."
allowed-tools: Bash, Read
---

# Sarathi report

You produce Sarathi's stage-2 interpretation: a report where every claim
about a specific project is either a citation into the fact sheet `measure`
just wrote, or an explicitly labeled judgment call. This skill never writes
files, never modifies config, and never asks a question — the report is the
entire deliverable, printed in this session.

## 1. Check readiness — run-then-fallback, narrower than `/sarathi:doctor`

Resolve the same config-dir this way: `$CLAUDE_CONFIG_DIR/sarathi/config.json`
if `$CLAUDE_CONFIG_DIR` is set, otherwise `~/.claude/sarathi/config.json` —
independent of `${CLAUDE_PLUGIN_ROOT}`, which only says where the plugin's
own code (including `sarathi.py`) lives.

Run the diagnosis, using the invoker stored in config.json if one is already
present there (read it directly), or the same pre-config bootstrap heuristic
`/sarathi:doctor` uses (`python3`, then `python`) only if no config exists
yet to read one from:

```bash
<invoker> "${CLAUDE_PLUGIN_ROOT}/sarathi.py" doctor --json
```

Parse `branch` from the output.

- **`branch` is anything other than `"proceed"`** (`"init"` or `"stop"`): do
  **not** attempt init, and do **not** attempt `measure`. Guided setup lives
  exclusively in `/sarathi:doctor` — stop here and point the user at it.
  Nothing below this line runs.
- **`branch` is `"proceed"`**: continue to §2. A `"proceed"` verdict
  guarantees the config is a fully-migrated schema-v2 config with a proven,
  stored `invoker` — read that stored absolute path directly from
  config.json's `invoker` key from here on. Never fall back to the
  `python3`-then-`python` bootstrap heuristic for anything past this point.

## 2. Run measure and confirm it actually succeeded

```bash
<invoker stored in config> "${CLAUDE_PLUGIN_ROOT}/sarathi.py" measure
```

Check `measure`'s own exit code before doing anything else. A `"proceed"`
verdict from the `doctor` call moments ago is **not** a guarantee `measure`
will still succeed right now — a root can go unreadable in the time between
the two calls. If `measure` exits non-zero: report that error and stop. Do
not interpret a fact sheet that wasn't actually just written.

## 3. Read the fact sheet

Read the JSON file at the `output_path` recorded in config.json (the one
`measure` just wrote). Everything below is drawn from this one file.

**Read `facts.roots` before you draw any conclusion from `facts.orphans`.**
If a root has `status: "failed"` or `"empty"`, any `facts.orphans` entry
whose slug is prefixed by that root carries an explicit reliability caveat
in the report — it is not stated as a bald fact. A root you couldn't fully
read is a reason an "orphan" might not really be gone, just unreachable
right now.

## 4. Write the report — exactly three sections, always, in this order

1. **Moving** — projects with clear recent activity (commits, file changes,
   or sessions close to `facts.as_of`) and no dormancy signal.
2. **Losing steam** — projects showing a stall signal without being fully
   dormant: e.g. `facts.projects.<key>.flags` containing `"stalled
   mid-flight"` or `"thinking > shipping"`, or activity that's meaningfully
   slower than it used to be.
3. **Forgotten** — projects flagged `"dormant"`, and any `facts.orphans`
   entry (a memory trail with no corresponding project left on disk).

Every section header appears every time, even when it has nothing to put in
it — write "none" explicitly under an empty section. Never omit a header
because a section is empty.

### Every claim about a specific project is cited

Use the format `[facts.projects.<key>.<subsection>]` — e.g.
`[facts.projects.tokenomics.git]` — or the equivalent path for roots or
orphans (`[facts.roots.<root>]`, `[facts.orphans.entries[<i>]]`). The
citation must resolve to a real value in the fact sheet you just read. A
claim about a specific project with no citation is a defect in the report,
not a style choice.

### Every line is labeled

Prefix or tag each line **measured** (a direct read of a fact-sheet field —
e.g. "last commit 2026-07-20 [facts.projects.x.git]") or **derived** (your
own synthesis — e.g. "this reads as stalled, not abandoned, because the
memory file still shows active threads"). An unlabeled line is a defect.

### Voice governs phrasing only

Read `voice` from config.json (`"plain"` or `"gen_z"`) and match the
report's register to it. This changes wording only — it never changes which
facts are reported, which citations are used, or the measured/derived
labeling. The same underlying claims and citations must appear regardless
of voice.

### No questions, anywhere in this run

Do not ask the user anything during this skill — no `AskUserQuestion`, no
open question of any kind. If something is ambiguous, say so as a derived,
labeled observation instead of asking about it.

### Closing line

End the report by *naming* what Sarathi's steer stage (v0.3, not yet
shipped) will eventually ask about — e.g. pointing at the "losing steam"
list as what a future steering question will be about — without actually
asking it. No question mark, no `AskUserQuestion`, nothing that expects a
reply.

## 5. Optional, non-blocking: the animated report artifact

The design-of-record describes an optional animated HTML rendering of this
same report (motion encodes verdict severity, `prefers-reduced-motion`
respected). It is not required by this skill — the markdown/text report
above, printed in this session, is the complete deliverable this skill is
accountable for. If you choose to also produce the artifact, respect
`prefers-reduced-motion`; its absence is never a defect.
