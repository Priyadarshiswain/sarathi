---
name: report
description: Run measure and produce a cited interpretation of your projects — moving, losing steam, forgotten, ruled — every claim traced back to the fact sheet just written, published as one living, animated artifact (redeployed to the same URL every run), then steer (a small number of closed questions about what data can't resolve) and realign (turn each answer into a dated decision file). Use when the user asks for a status report, project review, or "what's going on with my projects."
allowed-tools: Bash, Read, Write, AskUserQuestion, Artifact
---

# Sarathi report

You produce Sarathi's stage-2 interpretation (moving / losing steam /
forgotten / ruled, every claim a citation into the fact sheet `measure`
just wrote or an explicitly labeled judgment call), publish it as
**one living, animated artifact** — redeployed to the same URL every run,
falling back to a local HTML file only when the Artifact tool isn't
available — then stage 3 (steer: at most a handful of closed questions
about exactly what data can't resolve) and stage 4 (realign: each answer
becomes a dated decision file). Since v0.4, the artifact (or its local
fallback) is the deliverable this skill is accountable for — its absence,
with no stated fallback reason, is a defect (§5 below). The interpretation
itself never writes files or asks a question until it has published —
only the publish step's fallback path, and the steer/realign steps after
it, ever write or ask, and only about what §6/§7 below scope them to.

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

## 4. Assemble the payload — exactly four sections, always, in this order

This step does the same classification work v0.3 always did — but its
output is the **payload object** (§6 of the story; held in memory or a
temp file for the publish step below), **not** a transcript printed to the
user. Nothing about *what* gets classified or cited changes; only where
the result goes.

Before sorting any project/orphan into a section, read its `ruled_flags`
(projects) or `ruled` (orphans): **an item whose current flags are entirely
covered by `ruled_flags` (or an orphan with `ruled: true`) belongs only in
the ruled section below — never also in moving / losing steam /
forgotten.** An item whose most recent decision has since expired
(`"expired": true`) is *not* ruled — classify it normally in the first
three sections, exactly as if it had no decision at all; you may optionally
add one **derived** claim noting it was previously ruled and has since
reawakened, citing the expired decision entry (exact phrasing is your call,
not a pinned string).

1. **`sections.moving`** — projects with clear recent activity (commits,
   file changes, or sessions close to `facts.as_of`) and no dormancy signal.
2. **`sections.losing_steam`** — projects showing a stall signal without
   being fully dormant: e.g. `facts.projects.<key>.flags` containing
   `"stalled mid-flight"` or `"thinking > shipping"`, or activity that's
   meaningfully slower than it used to be.
3. **`sections.forgotten`** — projects flagged `"dormant"`, and any
   `facts.orphans` entry (a memory trail with no corresponding project left
   on disk).
4. **`sections.ruled`** — every project/orphan excluded from the three
   sections above by the unruled-first check. Each item carries a claim
   stating the verdict, the decided date, and (if present) the decision's
   `reason`/description text, cited to
   `facts.projects.<key>.decisions.entries[<i>]` (or
   `facts.orphans.entries[<i>].decisions.entries[<j>]`), labeled
   **measured**, plus `ruled_meta: {"verdict": ..., "decided": ...}`.

`sections.<name>` is `[]`, never omitted, for a section with nothing to
put in it — the payload always carries all four keys, so the template can
render an explicit "none" state per section without a null check.

### Every claim is cited

Each `claims[]` entry's `citation` field uses the format
`facts.projects.<key>.<subsection>` — e.g. `facts.projects.tokenomics.git`
— or the equivalent path for roots or orphans (`facts.roots.<root>`,
`facts.orphans.entries[<i>]`). The citation must resolve to a real value in
the fact sheet you just read. A claim about a specific project with no
citation is a defect, not a style choice.

### Every claim is labeled

Each `claims[]` entry's `label` field is exactly `"measured"` (a direct
read of a fact-sheet field — e.g. "last commit 2026-07-20") or `"derived"`
(your own synthesis — e.g. "this reads as stalled, not abandoned, because
the memory file still shows active threads"). A claim with any other label
value is a defect.

### Voice governs phrasing only

Read `voice` from config.json (`"plain"` or `"gen_z"`) and match every
claim's `text` register to it. This changes wording only — it never
changes which facts are reported, which citations are used, or the
measured/derived labeling. The same underlying claims and citations must
appear regardless of voice. Store the resolved voice in the payload's
`meta.voice` field.

### `momentum_pct` — a presentational judgment call, not a new fact

For every item in `sections.moving` and `sections.losing_steam`, set
`momentum_pct` (0–100, integer): how full that item's meter animates on
the page. This is **not** a new deterministic script output — it has no
citation of its own, and it never decides *which* section an item lands
in (that's the flags/`ruled_flags`/`decisions` logic above, unchanged). A
reasonable, non-pinned heuristic — e.g. inversely related to
`days_stalled` (from `facts.steer_candidates` or recomputed the same way),
clamped to `[0, 100]` — is your call, the same kind of judgment SAR-03
already allowed for the "reawakened" derived line. Moving items should
read as fuller/faster on average than losing-steam items purely because of
these values, not a different rule per section. Items in `forgotten` and
`ruled` never carry `momentum_pct`.

### Orphan `key` is the trimmed slug, never the raw slug

`facts.orphans` entries carry no display name of their own — their `slug`
field is a mangled absolute filesystem path (and therefore contains the
local OS username, e.g. `-Users-alice-Projects-old-thing`) and must never
be written into the payload. For every orphan item, compute the payload's
`key` by stripping the matched root-prefix from the front of the slug —
the same prefix `collect_orphans()` already matches against
(`sarathi.slug(os.path.normpath(root)) + "-"`, for whichever root in
`facts.roots` prefixes that orphan's slug) — leaving only the trailing
path segment(s). Project items already avoid this problem: their `key` is
already the safe basename `assign_project_keys()` assigned.

### `steer_preview` — the same candidates, never re-derived

Build `steer_preview` from the first `THRESHOLDS["STEER_MAX_QUESTIONS"]`
entries of `facts.steer_candidates` — the exact same ranked list, read the
same way, that §6 below reads for the actual steer step (the one-liner
below). Never re-rank, filter, or independently select entries for the
page. Each entry's `prompt` is fixed, literal text describing the
four-option closed question §6's table below spells out (e.g. `"Park it,
say it's next, declare it dead, or keep watching?"`) — descriptive text
only, never an interactive element.

### No question before the report is complete

Do not ask the user anything until the **publish step (§5) has finished** —
meaning the artifact has been published (or the local-fallback file
written) **and** the in-session remainder (the short summary, or the full
fallback text report) has been printed. Composing the payload internally
is not enough on its own. This is v0.4's redefinition of SAR-02 criterion
31 / SAR-03's narrowing of it: the underlying rule — steer never happens
early, never happens unscoped — is unchanged; only what counts as "the
report is complete" is updated to include publishing.

## 5. Publish — turn the payload into the one living artifact

Using the invoker already resolved in §1:

1. Write the payload (§4 above) to a temp JSON file.
2. Run `render_report.py` in fragment mode against
   `${CLAUDE_PLUGIN_ROOT}/skills/report/report-template.html` and the
   payload file:

   ```bash
   <invoker> "${CLAUDE_PLUGIN_ROOT}/skills/report/render_report.py" \
     --template "${CLAUDE_PLUGIN_ROOT}/skills/report/report-template.html" \
     --payload <temp-payload-path>
   ```

3. **Attempt the Artifact tool** — only when this session's tool set
   actually includes it. Call it with `action: "list"` (your own
   artifacts, `limit: 50`) and look for a title exactly matching
   `"Sarathi — Direction Report"`.
   - **Found**: call `Artifact` again with that same `url`, the rendered
     fragment as the `file_path` content, `favicon: "🧭"` (fixed, never
     changed across republishes), and `label`/version marker taken from
     the payload's `meta.version_label`. This updates the same artifact in
     place — the run history now lives in the artifact platform's own
     version picker, not duplicated inside the page.
   - **Not found among the 50 most recent**: publish with no `url`
     (creates a new artifact) and say so explicitly, in-session, in
     substance: *"could not find a prior 'Sarathi — Direction Report'
     artifact among your 50 most recent — publishing a new one; if an
     older one exists further back, you may want to delete it by hand to
     avoid two living copies."* A bounded lookup with a stated
     limitation, never an unbounded search silently presented as
     complete.
4. **If the Artifact tool is unavailable in this session** (not present in
   this run's tool set), **or the publish attempt itself errors**: go to
   the fallback path below. This is a **capability check, not a retry
   loop** — never attempt the Artifact tool speculatively more than once
   per run.

### Fallback path (Artifact tool unavailable or errors)

1. Run `render_report.py` in **standalone** mode against the same
   template/payload, writing to
   `<directory containing output_path>/report-<facts.as_of>.html`:

   ```bash
   <invoker> "${CLAUDE_PLUGIN_ROOT}/skills/report/render_report.py" \
     --template "${CLAUDE_PLUGIN_ROOT}/skills/report/report-template.html" \
     --payload <temp-payload-path> \
     --standalone "Sarathi — Direction Report" \
     --out "<dir of output_path>/report-<facts.as_of>.html"
   ```

   **Overwritten in place** if a file for that same `as_of` already exists
   — deliberately unlike decision files' never-overwrite rule: this file
   plays the "one living artifact" role locally, so overwrite-in-place is
   the correct local analogue of "redeployed to the same URL," not a
   violation of decision files' immutability rule (decision files remain
   the only thing in this codebase that must never be overwritten).
2. State explicitly, in-session: the Artifact tool was unavailable (or
   errored) this run, the full report was written locally instead, and its
   absolute path.
3. Print the **full four-section text report** — project/orphan, every
   claim, every citation, every measured/derived label, exactly as §4's
   classification produced it — into the transcript. This is what
   "fallback" means concretely: the deliverable this skill is accountable
   for, in a form the current session can actually produce.

### Artifact-mode in-session remainder (only when the artifact-tool path succeeds)

Print a **short summary only** — never the full four-section text
duplicated:

- The `stats` block's headline counts (N projects, N moving, N losing
  steam, N forgotten, N ruled).
- The single top item from each of moving / losing steam / forgotten (one
  line each, still cited and labeled — the citation/label rule applies
  here too, in reduced form, never waived).
- The published artifact's URL.
- A **network-exposure statement**, every run this path is taken (never a
  one-time decision the user forgets was made) — in substance: this
  report's content (project names, git/file/session-derived claims,
  memory-derived claims, citation paths, the steer-preview text) was sent
  to the artifact-hosting platform to render this page; `sarathi.py`
  itself makes zero network calls, unchanged; this only happens because
  the Artifact tool was available and used this run; the artifact starts
  private, shareable only if you choose to share it later.

Then steer (§6) and realign (§7) proceed exactly as before, now gated on
"the summary has been printed and the artifact published" (or, in
fallback mode, "the full text report has been printed and the local file
written") — never on merely composing the section text internally.

## 6. Steer — at most `STEER_MAX_QUESTIONS` closed questions, scoped only to `facts.steer_candidates`

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
first — never re-rank, filter, or second-guess it here, rule 3). This is
the exact same list `steer_preview` (§4) was built from — never re-derived.

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
  source of what's askable. This never includes anything from the page's
  `steer_preview` block — that block only *names* what's coming; the actual
  question only ever happens here, in-session.

## 7. Realign — write exactly the decision files the user's answers authorize

For each question in §6 the user actually answered (skip entirely if none
did — say so, write nothing):

1. **`decided` = `facts.as_of`** from the fact sheet you already read in
   §3 — never "today" independently guessed; `facts.as_of` is the one date
   already grounding every other claim in this report run.
2. **Target path** (filename amended by SAR-09 ruling C):
   `<config-dir>/projects/<slug>/memory/sarathi-decision-<key>-<decided>.md`
   for a candidate of kind `project`, where `<key>` is the candidate's own
   `"key"` field copied verbatim from `steer_candidates`; a candidate of
   kind `orphan` has no `"key"` field, so orphans keep the original
   `sarathi-decision-<decided>.md` shape — never derive a name component
   from the slug or the display text (rule 3: the LLM never reimplements
   slug or name resolution). The directory `<slug>` likewise comes
   straight from the candidate's `"slug"` field. `<config-dir>` is the
   same `$CLAUDE_CONFIG_DIR`-or-`~/.claude` resolved in §1. Old-format
   files already on disk (`sarathi-decision-<decided>.md` under a
   project) remain valid decision files forever — read, never renamed by
   this skill (migration is the memory skill's scan mode's consent-gated
   job, SAR-11).
3. **Collision handling**: if a file already exists at that exact path,
   append `-2`, `-3`, ... (the lowest unused suffix) rather than overwriting
   it. Decisions accumulate — never edited or replaced in place.
4. **Write the file**, in exactly this format (the pinned decision-memory
   format — required frontmatter keys, nothing more):

   ```
   ---
   name: <the filename from step 2, without .md>
   description: "<whatever reasoning the user gave, if any — may be empty>"
   type: sarathi-decision
   verdict: <parked|active-next|dead|keep-watching, from the table in §6>
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
6. **Index the write** (SAR-09 ruling A — the one carve-out from step 7's
   never-touch rule): append exactly one line to `MEMORY.md` in that same
   memory directory —

   `- [Sarathi decision <decided>](<filename from step 2>) — <verdict>: <the description text, or "no reason given">`

   — creating the file first with the single header line `# Memory index`
   and a blank line if it does not exist. Append-only: never edit,
   reorder, or delete any existing line, and if the exact line is somehow
   already present, skip the append rather than duplicate it. Show the
   appended line (and note if MEMORY.md was created) in the transcript,
   same no-silent-writes posture as step 5.
7. **Never touch any other file.** Beyond the decision file (step 4) and
   the single MEMORY.md index-line append (step 6), never edit or delete
   any other memory file already present there — including an earlier
   decision file.
   Two different steer answers for two different candidates in the same run
   are two separate writes, each under its own project's/orphan's own
   memory directory, each shown verbatim with its own path — never batched
   into a single write or a single confirmation.
