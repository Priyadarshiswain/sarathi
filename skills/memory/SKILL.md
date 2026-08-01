---
name: memory
description: Read-only ledger of everything Sarathi's measure step already knows about you from memory files and steering decisions — every entry and every decision quoted verbatim, published as one living artifact ("Sarathi — Memory Ledger"), redeployed to the same URL every run. Never interprets, never asks, never writes. Use when the user asks what Sarathi knows about them, wants to see their memory entries or steering decisions, or asks for the memory ledger.
allowed-tools: Bash, Read, Write, Artifact
---

# Sarathi memory ledger

You produce Sarathi's read-only ledger — every memory entry (`user` / `feedback` / `project` /
`reference` / `untyped`, bucketed by a fixed rule) and every steering decision the fact sheet
already carries, copied verbatim, never interpreted, never paraphrased, no voice adjustment —
and publish it as **one living artifact**, "Sarathi — Memory Ledger", redeployed to the same
URL every run, falling back to a local HTML file only when the Artifact tool isn't available.
This is a sibling to `/sarathi:report`, not a replacement for it: independent title, independent
template, independent payload. A user can run either skill, both, or neither, in any order, any
number of times. Nothing in `skills/report/` is touched by this skill, and this skill never
asks a question, never writes a memory file or decision file, and never touches `MEMORY.md`.

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
`measure` just wrote) — this is also the `--facts` argument §4 below passes
straight through.

**Read `facts.roots` before you draw any conclusion from `facts.orphans`.**
A root reporting `"failed"` or `"empty"` is why §4's payload builder attaches
a `root_unreadable` caveat to any orphan whose slug it prefixes — a root you
couldn't fully read right now is a reason a project might not really be
gone, not proof that it is.

## 4. Build the payload — mechanical, via a script, never assembled by hand

Unlike `/sarathi:report`, this step writes **no prose at all**. Every payload
field is either copied character-for-character from the fact sheet or a pure
count — there is no "which section does this belong in" judgment call
anywhere in this skill (design rule 3, sharper here than in `/sarathi:report`).
That mechanical work is a script, not something you compose by hand:

```bash
<invoker> "${CLAUDE_PLUGIN_ROOT}/skills/memory/build_ledger_payload.py" \
  --facts <output_path recorded in config.json> \
  --out <temp-payload-path>
```

This one call does everything §6 of the story pins:

- Walks `facts.projects` (key order) then `facts.orphans.entries` (the fact
  sheet's own list order); within a source, entries stay in the order
  `sarathi.py` already wrote them — never re-sorted by date or name.
- Skips any project whose `status` isn't `"ok"` — a configured child
  directory that vanished mid-run — without erroring.
- Buckets each memory entry by its `type` field, exactly and
  case-sensitively against `"user"` / `"feedback"` / `"project"` /
  `"reference"`; anything else — including the literal `"untyped"` default
  — falls into `untyped`, with the entry's own `type` field left exactly as
  written (never rewritten to match its bucket).
- Trims every orphan's `source` to the root-prefix-stripped slug — the
  identical procedure `/sarathi:report` already uses for its own `key`
  field — so the local OS username embedded in the raw slug never appears
  in the payload.
- Collects `caveats[]` for any source whose `memory`/`decisions` status is
  `"failed"` or `"ok"` with a non-null `reason` (a partial parse), and for
  any orphan whose matched root currently reports `"failed"`/`"empty"`.
- Computes `stats` — pure counts over the two walks above.

Never re-derive any of this by hand — the script is the single source of
truth for bucketing, trimming, ordering, and the caveat rules. Your job at
this step is entirely mechanical: run the command, hold onto the output path
for §5.

## 5. Publish — turn the payload into the one living artifact

Using the invoker already resolved in §1:

1. The payload is already written to the temp path from §4.
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
3. Print the **full ledger as markdown** into the transcript — every group
   under its own fixed heading (`about you`, `working style`,
   `project state`, `reference`, `untyped`), every entry's verbatim fields
   (name, description, date, type if it differs from its bucket, source,
   date, threads), then a `steering decisions` heading listing every
   decision's verbatim fields, then any `caveats[]` under their own
   heading. This is a **mechanical reformatting of the payload §4 already
   built** — list fields verbatim, under fixed headings mirroring the
   pinned group labels, never compose a sentence about an entry. Nothing on
   this page is LLM-composed prose, so "the full text report" here means
   exactly this: the payload's own content, not a re-derivation of it.

### Artifact-mode in-session remainder (only when the artifact-tool path succeeds)

Print a **short summary only** — never the full per-group listing
duplicated:

- The `stats` block's headline counts (total entries, per-group counts,
  steering-decisions count).
- The published artifact's URL.
- Any `caveats[]` present, named explicitly (never silently absorbed into a
  clean-looking summary — rule 2).
- The network-exposure statement (§6 below) — **every run this path is
  taken**, not once.

## 6. Network exposure — state this every run this path is taken

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
  slug (§4) — the raw slug, which embeds your local OS username, never
  leaves this machine.
- **Two living artifacts now exist off-machine if you run both skills** —
  worth naming explicitly the first time `/sarathi:memory` publishes: this
  is a *second* artifact, independent of "Sarathi — Direction Report," not
  a replacement for it.

## 7. What this skill never does

- Never calls `AskUserQuestion` — `allowed-tools` omits it entirely, on
  purpose. This skill asks nothing, ever.
- Never writes a memory file, a decision file, or `MEMORY.md` — read-only,
  end to end, stronger than `/sarathi:report`'s own relationship to those
  files (which at least writes decisions via realign).
- Never reads or writes `config.json`'s `voice` key, and never composes any
  free-text phrasing — there is nothing on this page for a voice setting to
  govern.
- Never stores the artifact's URL in `config.json` — the title-lookup
  approach's bounded-search cost is the same, accepted position
  `/sarathi:report` already takes for its own artifact.
- Writes only `output_path` (via the reused `measure` step) and, fallback
  mode only, `<dir of output_path>/ledger-<as_of>.html` — no other file, no
  other directory, ever.
