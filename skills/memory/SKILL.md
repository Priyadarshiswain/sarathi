---
name: memory
description: Read-only ledger of everything Sarathi's measure step already knows about you from memory files and steering decisions — every entry and every decision quoted verbatim, published as one living artifact ("Sarathi — Memory Ledger"), redeployed to the same URL every run; in ledger mode it never interprets, never asks, never writes. With --scan it instead runs the deterministic memory-organization detectors (misfiled entries, drifted duplicates, index/link/frontmatter hygiene) and walks the user through consent-gated fixes. Use when the user asks what Sarathi knows about them, wants the memory ledger, or — for --scan — asks to organize, clean up, or check their memory folders.
argument-hint: "[--verbose] [--scan]"
allowed-tools: Bash, Read, Write, Artifact, AskUserQuestion
---

# Sarathi memory ledger

You produce Sarathi's read-only ledger — every memory entry, bucketed into three fixed modules
(`setup` / `working_style` / `project_memory`, bucketed by a fixed rule) — and every steering
decision the fact sheet already carries, copied verbatim, never interpreted, never paraphrased,
no voice adjustment — and publish it as **one living artifact**, "Sarathi — Memory Ledger",
redeployed to the same URL every run, falling back to a local HTML file only when the Artifact
tool isn't available. The published page opens in **simple** density by default (headline stats
plus a one-line row per entry) or **verbose** density (every entry's full card) when the user's
own invocation carried `--verbose` (§4 below); either way, a header toggle and each row's own
independent expand let a reader switch density client-side, no re-fetch, same payload either
way (SAR-06). This is a sibling to `/sarathi:report`, not a replacement for it: independent
title, independent template, independent payload. A user can run either skill, both, or
neither, in any order, any number of times. Nothing in `skills/report/` is touched by this
skill, and in this mode the skill never asks a question, never writes a memory file or decision
file, and never touches `MEMORY.md`.

**Mode fork (SAR-11):** if the user's own invocation text carries `--scan` (detected exactly the
way §4 detects `--verbose` — the literal token in the invocation, never inferred from phrasing),
you take §9's scan path INSTEAD of the ledger path (§§1–7 are skipped entirely; no artifact is
published). Everything above and every rule in §8's first list is the LEDGER mode's law and is
untouched by the fork; §9 carries its own, different law. When `--scan` is absent, §9 does not
exist for you.

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
not build a ledger against a fact sheet that wasn't actually just written.

## 3. Read the fact sheet

Read the JSON file at the `output_path` recorded in config.json (the one
`measure` just wrote) — this is also the `--facts` argument §5 below passes
straight through.

**Read `facts.roots` before you draw any conclusion from `facts.orphans`.**
A root reporting `"failed"` or `"empty"` is why §5's payload builder attaches
a `root_unreadable` caveat to any orphan whose slug it prefixes — a root you
couldn't fully read right now is a reason a project might not really be
gone, not proof that it is.

## 4. Determine the requested view from your own invocation text

Before building the payload, look at the literal text the user used to invoke this skill this
run (e.g. `/sarathi:memory --verbose` vs. plain `/sarathi:memory`):

- If that invocation text contains the exact token `--verbose`, matched case-insensitively,
  anywhere in the text: `requested_view = "verbose"`.
- Otherwise: `requested_view = "simple"`.

**Unrecognized argument text — loud, not fatal.** If the invocation carried other non-empty
argument text that is not `--verbose` (a typo, an unsupported flag, stray text after the skill
name), say so in one line in-session — *"ignored unrecognized argument: `<text>` — the only
supported flag is `--verbose`"* — and proceed in **simple** view. Never guess intent from a
near-miss token (e.g. `-verbose`, `--verbos`, `verbose` with no dashes all count as
unrecognized, not as `--verbose`); the exact token is the only thing that flips the view.

This is a parsed invocation argument, not a question — `AskUserQuestion` is never called here,
consistent with §8's read-only, no-question contract. `requested_view` flows into two places:
§5's CLI call (`--default-view <requested_view>`) and the fallback path's listing-verbosity
choice (§6 below).

## 5. Build the payload — mechanical, via a script, never assembled by hand

Unlike `/sarathi:report`, this step writes **no prose at all**. Every payload
field is either copied character-for-character from the fact sheet or a pure
count — there is no "which section does this belong in" judgment call
anywhere in this skill (design rule 3, sharper here than in `/sarathi:report`).
That mechanical work is a script, not something you compose by hand:

```bash
<invoker> "${CLAUDE_PLUGIN_ROOT}/skills/memory/build_ledger_payload.py" \
  --facts <output_path recorded in config.json> \
  --default-view <requested_view from §4> \
  --out <temp-payload-path>
```

This one call does everything §6 of the story pins:

- Walks `facts.projects` (key order) then `facts.orphans.entries` (the fact
  sheet's own list order); within a source, entries stay in the order
  `sarathi.py` already wrote them — never re-sorted by date or name.
- Skips any project whose `status` isn't `"ok"` — a configured child
  directory that vanished mid-run — without erroring.
- Buckets each memory entry into one of three fixed modules by its `type`
  field, exactly and case-sensitively: `"setup"` → the `setup` module;
  `"feedback"` or `"user"` → the `working_style` module; anything else —
  `"project"`, `"reference"`, the literal `"untyped"` default, or any other
  free-text value — → the `project_memory` module. The entry's own `type`
  field is left exactly as written (never rewritten to match its module).
- Trims every orphan's `source` to the root-prefix-stripped slug — the
  identical procedure `/sarathi:report` already uses for its own `key`
  field — so the local OS username embedded in the raw slug never appears
  in the payload.
- Collects `caveats[]` for any source whose `memory`/`decisions` status is
  `"failed"` or `"ok"` with a non-null `reason` (a partial parse), and for
  any orphan whose matched root currently reports `"failed"`/`"empty"`.
- Computes `stats` — pure counts over the two walks above, keyed by module
  (`stats.by_module`).
- Writes the requested view straight into `meta.default_view` — an
  explicit, non-`voice`-derived input, never inferred from `config.json` or
  any fact-sheet field.

Never re-derive any of this by hand — the script is the single source of
truth for bucketing, trimming, ordering, the caveat rules, and the view
value. Your job at this step is entirely mechanical: run the command, hold
onto the output path for §6.

## 6. Publish — turn the payload into the one living artifact

Using the invoker already resolved in §1:

1. The payload is already written to the temp path from §5.
2. Run `render_report.py` (unmodified, shared byte-for-byte with
   `/sarathi:report`) in fragment mode against
   `${CLAUDE_PLUGIN_ROOT}/skills/memory/ledger-template.html` and the
   payload file:

   ```bash
   <invoker> "${CLAUDE_PLUGIN_ROOT}/skills/report/render_report.py" \
     --template "${CLAUDE_PLUGIN_ROOT}/skills/memory/ledger-template.html" \
     --payload <temp-payload-path>
   ```

3. **Attempt the Artifact tool** — only when this session's tool set
   actually includes it. Call it with `action: "list"` (your own
   artifacts, `limit: 50`) and look for a title exactly matching
   `"Sarathi — Memory Ledger"`.
   - **Found**: call `Artifact` again with that same `url`, the rendered
     fragment as the `file_path` content, `favicon: "📒"` (fixed, never
     changed across republishes — chosen distinct from `/sarathi:report`'s
     `"🧭"`), and `label`/version marker taken from the payload's
     `meta.version_label`. This updates the same artifact in place.
   - **Not found among the 50 most recent**: publish with no `url`
     (creates a new artifact) and say so explicitly, in-session, in
     substance: *"could not find a prior 'Sarathi — Memory Ledger' artifact
     among your 50 most recent — publishing a new one; if an older one
     exists further back, you may want to delete it by hand to avoid two
     living copies."* A bounded lookup with a stated limitation, never an
     unbounded search silently presented as complete.
4. **If the Artifact tool is unavailable in this session** (not present in
   this run's tool set), **or the publish attempt itself errors**: go to
   the fallback path below. This is a **capability check, not a retry
   loop** — never attempt the Artifact tool speculatively more than once
   per run.

### Fallback path (Artifact tool unavailable or errors)

1. Run `render_report.py` in **standalone** mode against the same
   template/payload, writing to
   `<directory containing output_path>/ledger-<facts.as_of>.html`:

   ```bash
   <invoker> "${CLAUDE_PLUGIN_ROOT}/skills/report/render_report.py" \
     --template "${CLAUDE_PLUGIN_ROOT}/skills/memory/ledger-template.html" \
     --payload <temp-payload-path> \
     --standalone "Sarathi — Memory Ledger" \
     --out "<dir of output_path>/ledger-<facts.as_of>.html"
   ```

   **Overwritten in place** if a file for that same `as_of` already exists —
   the local analogue of "redeployed to the same URL," identical convention
   to `/sarathi:report`'s own fallback file.
2. State explicitly, in-session: the Artifact tool was unavailable (or
   errored) this run, the ledger was written locally instead, and its
   absolute path.
3. Print the ledger into the transcript — **shape depends on
   `requested_view` from §4**, both shapes a **mechanical reformatting of
   the payload §5 already built**, fixed headings only, list fields
   verbatim, never compose a sentence about an entry:
   - **`requested_view == "simple"` (default):** one line per entry — name,
     date, source — under each of the three fixed module headings
     (`dev setup`, `working style`, `project memory`), in the payload's own
     module/entry order. A module with no entries still prints its heading
     with a "None recorded." line (rule 2, unchanged) — this is expected
     and correct for `dev setup` on the very first run after this story
     ships, for every user, since no memory file yet uses the `type: setup`
     convention; it is not a sign anything is broken. Steering decisions
     and caveats still print in full underneath — this density choice only
     changes the memory-entry listing, not the decisions/caveats sections,
     which were already terse, single-line-per-item shapes with no fuller
     form to omit down from.
   - **`requested_view == "verbose"`:** the full per-entry verbatim listing
     — name, description, date, type (when it differs from its module's
     native type), source, threads — under the same three fixed module
     headings, then `steering decisions` listing every decision's verbatim
     fields, then any `caveats[]` under their own heading.
   - Nothing on this page is LLM-composed prose in either shape, so "the
     full text report" here means exactly this: the payload's own content,
     reformatted mechanically, not a re-derivation of it.

### Artifact-mode in-session remainder (only when the artifact-tool path succeeds)

Print a **short summary only** — never the full per-module listing
duplicated:

- The `stats` block's headline counts (total entries, per-module counts,
  steering-decisions count).
- The published artifact's URL.
- Any `caveats[]` present, named explicitly (never silently absorbed into a
  clean-looking summary — rule 2).
- One clause stating which view the published page opened in — *"opened in
  {simple|verbose} view — the on-page toggle switches either way"* — never
  a duplicate of the full listing.
- The network-exposure statement (§7 below) — **every run this path is
  taken**, not once.

## 7. Network exposure — state this every run this path is taken

**This is the most personal content Sarathi has ever sent off-machine, and
the disclosure must read that way — at least as pointed as `/sarathi:report`'s
own network-exposure statement, not a lighter-touch copy of it.** Say, in
substance, at least:

- **What leaves the machine and where**: every memory entry's name,
  description, date, and type, every steering decision's verdict/date/
  reason, and each entry's source project or (trimmed) orphan name — sent
  to the artifact-hosting platform, unmodified, exactly as it reads in your
  own memory files, so the page can render it.
- **This is more personal than the report.** `/sarathi:report`'s claims are
  the model's own synthesis of git/file activity; this page's content is,
  in significant part, verbatim personal and working-style notes a past
  session wrote about you specifically — do not understate this by reusing
  the report's exact wording unchanged.
- **`sarathi.py` itself still makes zero network calls, always** — the
  exposure is entirely inside this skill's publish step, an LLM-driven
  action using a host-provided tool.
- **Only when the Artifact tool is actually available and actually
  invoked** — a session without it never sends anything; the fallback is
  fully local.
- **Artifacts start private**, shareable only if you later choose to.
- **Username redaction**: the orphan `source` field is always the trimmed
  slug (§5) — the raw slug, which embeds your local OS username, never
  leaves this machine.
- **Two living artifacts now exist off-machine if you run both skills** —
  worth naming explicitly the first time `/sarathi:memory` publishes: this
  is a *second* artifact, independent of "Sarathi — Direction Report," not
  a replacement for it.
- **Verbose view is a local rendering choice, not additional network
  exposure.** Both densities render the same already-sent payload; whether
  a reader opens verbose by default (`--verbose`) or reaches it via the
  on-page toggle, nothing extra is fetched or sent — verbose just surfaces
  fields simple view was hiding, in the browser, from data already there.

## 8. What this skill never does (ledger mode — the list scan mode §9 amends for itself)

- Never calls `AskUserQuestion` in ledger mode. (SAR-11 adds the tool to
  `allowed-tools` for §9's steer alone; the ledger path still asks
  nothing, ever.)
- Never writes a memory file, a decision file, or `MEMORY.md` in ledger
  mode — read-only, end to end, stronger than `/sarathi:report`'s own
  relationship to those files (which at least writes decisions via
  realign). Scan mode writes exactly what §9 authorizes, nothing else.
- Never reads or writes `config.json`'s `voice` key, and never composes any
  free-text phrasing — there is nothing on this page for a voice setting to
  govern.
- Never stores the artifact's URL in `config.json` — the title-lookup
  approach's bounded-search cost is the same, accepted position
  `/sarathi:report` already takes for its own artifact.
- Writes only `output_path` (via the reused `measure` step) and, fallback
  mode only, `<dir of output_path>/ledger-<as_of>.html` — no other file, no
  other directory, ever.

## 9. Scan mode — `--scan` (SAR-10 + SAR-11): detect, ask, fix by prompt

The organize surface. Three stages, in order, never reordered: the script
detects (deterministically, no model in the loop), you ask (closed
questions, bounded verdicts, every question citing a finding id), and you
fix (each fix a fixed procedure, executed only on this run's explicit
consent, every file operation shown in the transcript). You never discover
a finding yourself, never re-classify one, and never act without a consent
given in this session (rule 3, and the owner's 2026-08-05 flow ruling).

### 9.1 Detect — run the scanner, read the findings

1. Resolve `<config-dir>` and read `config.json` exactly as §1/§2 do; you
   need `project_roots` and `output_path` from it.
2. Run the detector script — all logic lives there, unit-tested, stdlib
   only (SAR-10):

   `<python> <skill-dir>/scan_memory_org.py --roots <each project_roots value> --out <dir of output_path>/sarathi-findings.json`

   The `--roots` values are handed over verbatim from the config — the
   script deliberately does not re-read or re-validate config.json.
3. Read the findings JSON. Present a short mechanical summary first:
   finding count per family, the rent table's total and largest folder
   (verbatim numbers), and the `corpus_hash`. Quote evidence only from the
   findings document — never from your own re-reading of the corpus.
4. **Prior rulings suppress re-asks:** before steering, read any
   `sarathi-organize-*.md` files in each finding's home memory folder. A
   finding whose id appears in one, with the same recorded
   `entry_sha` as the current finding's entry content, is already ruled —
   report it as such and do not ask again. A changed hash reopens the
   question (state that it reopened and why).

### 9.2 Steer — families `placement` and `duplication` always ask first

One closed question per unruled finding, via `AskUserQuestion` (≤4
questions per call; batch until done — a dedicated scan run has no
report-style 2-question cap). The verdict sets are fixed per detector:

| detector | verdicts |
|---|---|
| `foreign_path` | move to `<target>` · stays (cross-reference) · archive |
| `wikilink_demand` | record demand · remove link |
| `orphaned_folder` | renamed → remap to one of the listed candidates · dead → archive folder · leave |
| `same_basename` (state `drifted`) | pick a winner (one option per folder) · merge · keep both knowingly |
| `same_basename` (state `identical`) | keep one (one option per folder) · keep both knowingly |
| `same_basename` where every colliding file matches the decision-filename pattern | migrate (rename each to its slug-bearing SAR-09 form + index it) · leave |

"Stays", "leave", and "keep both knowingly" are real verdicts — they get
recorded like any other (9.4) so the finding never re-asks.

### 9.3 Fix — family `hygiene` is one batched confirmation, then procedures

Hygiene findings carry no ruling content. List every proposed hygiene fix
as one itemized preview (finding id → exact operation), ask ONE yes/no
confirmation for the batch, then execute. Exception: any DELETE of a file
is pulled out of the batch and consented singly, always.

The fix procedures, by `fix_class` (fixed, never improvised):

- **move+reindex**: write the entry at the destination memory folder
  (create the folder and a `# Memory index` MEMORY.md if absent) → append
  its index line there → delete the source file (singly consented) →
  remove its source index line. Append `moved_from: <home slug>` and
  `moved_on: <date>` lines to the moved entry's frontmatter metadata.
- **merge-or-pick**: show both copies verbatim → the user picks the winner
  or dictates the merge → write the result to the ruled home → delete the
  loser (singly consented) → fix both indexes.
- **archive**: move the file to `<config-dir>/memory-archive/<home slug>/`
  (created on demand; no session ever loads it) → remove its index line.
- **add-index-line**: append the standard `- [Name](file.md) — description`
  line (creating MEMORY.md with the `# Memory index` header if absent).
  Append-only, §7-of-report posture: never edit or reorder existing lines.
- **fill-frontmatter**: add the missing keys with values quoted or
  minimally summarized from the entry's own text — never invented facts.
- **remove-link**: delete the dangling `[[link]]` text (or the dangling
  index line) only; the surrounding sentence is otherwise untouched.
- **record-only**: nothing on disk beyond the 9.4 record.
- **migrate** (decision files): rename to
  `sarathi-decision-<project-basename>-<decided>.md` where the basename
  comes from the folder's matched project (the findings document's
  evidence), old name shown → new name shown; then add its index line.
  Orphan folders' decision files keep their name (no basename exists to
  use — same rule as report §7 step 2).

### 9.4 Record — every verdict becomes a dated organize file

For each ruled finding (including "stays"/"leave"), write ONE file in the
finding's home memory folder:
`sarathi-organize-<date>[-N].md` (N on collision, lowest unused), with
frontmatter `name` (the filename stem), `description` (one line: verdict +
finding id), `type: sarathi-organize`, and a body listing: finding id,
detector, verdict, the entry's `sha` at ruling time (`entry_sha: <hash>`,
copied from the findings JSON — this is what 9.1 step 4 compares), and
every file operation performed. Batch hygiene fixes get one shared file
per home folder. Index each written file (add-index-line procedure).
These files deliberately do NOT match the decision-filename pattern —
measure's decision parser never sees them; they are ordinary memory
entries recording organize rulings.

### 9.5 Scan mode's own law

- Nothing is written before its consent in THIS run; consent is per
  action class per run, never standing.
- Every write, move, rename, append, and delete is shown in the
  transcript with exact paths (old → new where applicable). No silent
  operations, ever.
- Deletes are singly consented, always — never inside a batch yes.
- Never edit an entry's body text except the two authorized touches:
  `moved_from`/`moved_on` metadata on a move, and `remove-link`'s exact
  deletion. Never rewrite, rephrase, or "improve" anyone's memory.
- Import is out of scope (the fork is parked): a move relocates the only
  copy; you never copy a rule into additional projects. If the user asks
  for an import mid-run, record it in the 9.4 file as demand evidence and
  move on.
- No artifact, no network beyond what the Artifact-free path already
  does: the scanner script is zero-network by construction, and scan mode
  publishes nothing.
- Writes allowed in scan mode, exhaustively: the findings JSON at
  `<dir of output_path>/sarathi-findings.json`, consented fixes inside
  `<config-dir>/projects/*/memory/`, the archive tree
  `<config-dir>/memory-archive/`, and 9.4's organize files. Nothing else,
  nowhere else.
