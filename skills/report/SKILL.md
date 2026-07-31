---
name: report
description: Run measure and produce a cited interpretation of your projects — moving, losing steam, forgotten, ruled — every claim traced back to the fact sheet just written, then steer (a small number of closed questions about what data can't resolve) and realign (turn each answer into a dated decision file). Use when the user asks for a status report, project review, or "what's going on with my projects."
allowed-tools: Bash, Read, Write, AskUserQuestion
---

# Sarathi report

You produce Sarathi's stage-2 interpretation (moving / losing steam /
forgotten / ruled, every claim a citation into the fact sheet `measure` just
wrote or an explicitly labeled judgment call), then stage 3 (steer: at most
a handful of closed questions about exactly what data can't resolve) and
stage 4 (realign: each answer becomes a dated decision file). The
interpretation itself never writes files or asks a question — only the
steer/realign steps at the end do, and only about what §5 below scopes them
to.

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

## 4. Write the report — exactly four sections, always, in this order

Before sorting any project/orphan into a section, read its `ruled_flags`
(projects) or `ruled` (orphans): **an item whose current flags are entirely
covered by `ruled_flags` (or an orphan with `ruled: true`) appears only in
the new ruled section below — never also in moving / losing steam /
forgotten.** An item whose most recent decision has since expired
(`"expired": true`) is *not* ruled — evaluate it normally in the first three
sections, exactly as if it had no decision at all; you may optionally add
one **derived** line noting it was previously ruled and has since
reawakened, citing the expired decision entry (exact phrasing is your call,
not a pinned string).

1. **Moving** — projects with clear recent activity (commits, file changes,
   or sessions close to `facts.as_of`) and no dormancy signal.
2. **Losing steam** — projects showing a stall signal without being fully
   dormant: e.g. `facts.projects.<key>.flags` containing `"stalled
   mid-flight"` or `"thinking > shipping"`, or activity that's meaningfully
   slower than it used to be.
3. **Forgotten** — projects flagged `"dormant"`, and any `facts.orphans`
   entry (a memory trail with no corresponding project left on disk).
4. **Ruled** — every project/orphan excluded from the three sections above
   by the unruled-first check. State, per item: the verdict, the decided
   date, and (if present) the decision's `reason`/description text, cited to
   `[facts.projects.<key>.decisions.entries[<i>]]` (or
   `[facts.orphans.entries[<i>].decisions.entries[<j>]]`) and labeled
   **measured**.

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

### No question before the four sections are fully written

Do not ask the user anything until all four sections above are printed in
full. This is what SAR-02 criterion 31 originally forbade outright; v0.3
narrows, not repeals, that rule (see §5) — the only questions that ever
happen in this skill are the scoped steer questions after this point, never
an open-ended one, and never before the interpretation is complete.

## 5. Steer — at most `STEER_MAX_QUESTIONS` closed questions, scoped only to `facts.steer_candidates`

This is the step SAR-02 criterion 31's closing line named without asking —
now it actually asks. It is gated so narrowly it can only ever be about
`facts.steer_candidates`: never a bare, unscoped question, never anything
the fact sheet could already answer on its own (design rule 4).

Read `THRESHOLDS["STEER_MAX_QUESTIONS"]` from the script itself — never
hardcode the number `2` (or any other literal) in this file, so a future
constant change never requires touching this skill:

```bash
<invoker> -c "import sys; sys.path.insert(0, '${CLAUDE_PLUGIN_ROOT}'); import sarathi; print(sarathi.THRESHOLDS['STEER_MAX_QUESTIONS'])"
```

Take the first `STEER_MAX_QUESTIONS` entries of `facts.steer_candidates` (it
is already ranked deterministically by the script — longest-stalled-unruled
first — never re-rank, filter, or second-guess it here, rule 3).

- **If `facts.steer_candidates` is empty**: say so explicitly — "nothing to
  steer this run — no unruled drift" — rather than silently skipping the
  section. The fail-loudly convention applies to the good-news case too.
- **Otherwise**, for each of the first `STEER_MAX_QUESTIONS` candidates, ask
  exactly one `AskUserQuestion`, scoped to that one candidate by name (its
  project key or orphan slug in the question text), with exactly these four
  closed options mapped 1:1 to the verdict set — never an open-ended
  question, never a different option set:

  | Option shown to user | Verdict written |
  |---|---|
  | Park it | `parked` |
  | It's next | `active-next` |
  | Declare it dead | `dead` |
  | Keep watching | `keep-watching` |

- **If the user declines or gives no usable answer** to a given question
  (dismisses it / no usable answer): write nothing for that item and say so.
  A non-answer is not a `keep-watching` default — it is simply nothing
  decided.
- Never ask about anything not present in `facts.steer_candidates` — this is
  rule 4 enforced at the skill level: the candidate list is the *only*
  source of what's askable.

## 6. Realign — write exactly the decision files the user's answers authorize

For each question in §5 the user actually answered (skip entirely if none
did — say so, write nothing):

1. **`decided` = `facts.as_of`** from the fact sheet you already read in
   §3 — never "today" independently guessed; `facts.as_of` is the one date
   already grounding every other claim in this report run.
2. **Target path**: `<config-dir>/projects/<slug>/memory/sarathi-decision-<decided>.md`,
   using the candidate's own `"slug"` field straight from `steer_candidates`
   — never re-derived from the display key, never guessed (rule 3: the LLM
   never reimplements slug resolution). `<config-dir>` is the same
   `$CLAUDE_CONFIG_DIR`-or-`~/.claude` resolved in §1.
3. **Collision handling**: if a file already exists at that exact path,
   append `-2`, `-3`, ... (the lowest unused suffix) rather than overwriting
   it. Decisions accumulate — never edited or replaced in place.
4. **Write the file**, in exactly this format (the pinned decision-memory
   format — required frontmatter keys, nothing more):

   ```
   ---
   name: sarathi-decision-<decided>
   description: "<whatever reasoning the user gave, if any — may be empty>"
   type: sarathi-decision
   verdict: <parked|active-next|dead|keep-watching, from the table in §5>
   decided: <decided>
   ---

   <optional free-text body: further reasoning, if the user gave more than
   fits in a one-line description — may be empty>
   ```

   A bare option pick with no elaboration is still a complete, valid
   decision file — `description` and the body may both be empty.
5. **Show the write.** Immediately after writing, print the file's full
   contents back into the transcript verbatim, and state its absolute path
   explicitly. Never a silent write the user has to go looking for.
6. **Never touch any other file.** In particular: never edit or append to
   `MEMORY.md` in that memory directory, and never edit or delete any other
   memory file already present there — including an earlier decision file.
   Two different steer answers for two different candidates in the same run
   are two separate writes, each under its own project's/orphan's own
   memory directory, each shown verbatim with its own path — never batched
   into a single write or a single confirmation.

## 7. Optional, non-blocking: the animated report artifact

The design-of-record describes an optional animated HTML rendering of this
same report (motion encodes verdict severity, `prefers-reduced-motion`
respected). It is not required by this skill — the markdown/text report
above, printed in this session, is the complete deliverable this skill is
accountable for. If you choose to also produce the artifact, respect
`prefers-reduced-motion`; its absence is never a defect.
