# `config.json` schema

`sarathi measure` and `sarathi doctor` read one config file:

```
<config-dir>/sarathi/config.json
```

where `<config-dir>` is `$CLAUDE_CONFIG_DIR` if that environment variable is
set, otherwise `~/.claude`. The config-dir override is an environment
variable only — it is never a key inside the config file itself, because a
config file can't relocate the directory it lives in.

This is a separate resolution mechanism from `${CLAUDE_PLUGIN_ROOT}`, the
path Claude Code's plugin loader sets to wherever the plugin itself is
installed (used by the `sarathi:doctor` and `sarathi:report` skills to
locate `sarathi.py`). The two are independent and must not be conflated:
`${CLAUDE_PLUGIN_ROOT}` says where the *code* lives; `$CLAUDE_CONFIG_DIR`
(or `~/.claude`) says where the *config and output* live. Installing,
moving, or uninstalling the plugin never affects config.json's location.

As of v0.2, `/sarathi:doctor` offers guided setup (init) when no config
exists or an existing one is stale — see the plugin's `skills/doctor/SKILL.md`.
You can still write this file by hand instead.

## Two required-vs-allowed layers (why this matters)

There are two distinct notions of "valid config" in this codebase, enforced
at two different layers, on purpose (SAR-02 criteria 18–22):

1. **`load_config()`** — the loose, permanent layer. Its **required** key
   set is exactly `{schema_version, project_roots, output_path}` and has
   never changed since v0.1. `voice` and `invoker` (added in schema v2, see
   below) are **allowed but never required** here — an untouched v0.1
   config keeps loading, forever, for `measure` and bare
   `python3 sarathi.py` usage, no matter how many optional keys later
   schema versions add. The one exception: if `voice` **is present**, its
   *value* must be `"plain"` or `"gen_z"` — an unrecognized value is
   rejected here, by value, even though `measure` never reads `voice`
   (deliberate rule-1 strictness, exactly parallel to how an unrecognized
   *key name* is already rejected). Absence is always fine; presence but
   invalid is loud.
2. **`sarathi doctor`'s `config` check** — the stricter, skill-facing
   layer. It additionally requires that a config whose `schema_version`
   equals `CONFIG_SCHEMA_VERSION` (the "current" version the script and its
   skills expect) actually carries **both** `voice` and `invoker`. A
   config missing one of them at the current schema version is reported
   `failed`, with wording that says "malformed v2 config, not a stale v1
   one" — distinct from the separate "stale" case below. This is what
   makes it true that `measure` still runs fine against such a config
   (layer 1's optionality) while `doctor` still flags the inconsistency
   (layer 2's stricter check) — two different, both-correct answers to two
   different questions.

A config whose `schema_version` does **not** equal `CONFIG_SCHEMA_VERSION`
at all (e.g. an untouched v0.1 config, `schema_version: 1`) is reported
`failed` by the `config` check too, worded as **stale**, pointing at
`/sarathi:doctor`'s guided migration step — never the generic "missing
required key" message a genuinely broken config would get from
`load_config()` itself. The two failure modes ("stale" vs. a genuine
`ConfigError` from `load_config`, e.g. a truly missing/unparseable file)
produce different `detail` text on purpose, so a skill quoting the message
verbatim never confuses "this config needs migrating" with "this config is
broken."

## Keys

| Key | Required by `load_config`? | Type | Description |
|---|---|---|---|
| `schema_version` | **yes** | integer | Config schema version. `sarathi doctor`'s `config` check reports the config as **stale** if it doesn't match the script's current `CONFIG_SCHEMA_VERSION` (currently `2`) — `load_config()` itself accepts any integer here. |
| `project_roots` | **yes** | array of strings | Absolute paths to **parent directories**, e.g. `~/Projects` — not individual project paths. Each root is auto-scanned for its immediate child directories, and every child found is one measured project. There is no hand-maintained list of individual projects: a new directory created under a configured root shows up in the fact sheet on the very next `measure` run, with no config edit. Each discovered child is scanned for files, git state, and (via its slug under the config dir's `projects/` folder) Claude session and memory history. |
| `output_path` | **yes** | string | Path (absolute or relative to the current working directory) where `sarathi measure` writes its JSON fact sheet. The containing directory is created if it doesn't exist. `sarathi doctor` never writes here — it only checks that the location is writable. |
| `voice` | no (schema v2+) | string, one of `"plain"` \| `"gen_z"` | Report register for `/sarathi:report`. Asked once by `/sarathi:doctor`'s guided setup, never inferred from the user's writing style — no scan can observe how a user wants to be spoken to. Changes phrasing only, never which facts, citations, or measured/derived labels appear. If present, an unrecognized value is rejected by `load_config()` itself (see above) — a typo must never silently fall back to a default register. |
| `invoker` | no (schema v2+) | string | Absolute path to the Python executable `/sarathi:doctor` and `/sarathi:report` shell out with (e.g. `/usr/bin/python3` or `/usr/local/bin/python3.11`) — **not** a bare command name like `python3`. Resolved and proven (version checked against the script's own minimum) by `/sarathi:doctor`'s guided setup exactly once; every subsequent `doctor`/`report` run uses this stored path directly rather than re-guessing which Python to use. |

Any key not listed here is **rejected by name** when the config is loaded
(`unknown config key: '<name>'`) — a typo must never silently change
behavior.

## Example (schema v2, current)

```json
{
  "schema_version": 2,
  "project_roots": [
    "/Users/alice/Projects",
    "/Users/alice/work-projects"
  ],
  "output_path": "/Users/alice/.claude/sarathi/facts.json",
  "voice": "plain",
  "invoker": "/usr/bin/python3"
}
```

With this config, every immediate subdirectory of `/Users/alice/Projects`
and of `/Users/alice/work-projects` is discovered and measured — e.g. a
`tokenomics/` folder under either one becomes a `facts.projects` entry
automatically, with no need to list `tokenomics` in the config.

## Example (schema v1, still works for `measure`)

```json
{
  "schema_version": 1,
  "project_roots": ["/Users/alice/Projects"],
  "output_path": "/Users/alice/.claude/sarathi/facts.json"
}
```

`python3 sarathi.py` (bare `measure`) runs this exactly as it did in v0.1 —
exits 0, writes an identically-shaped fact sheet. `sarathi doctor`, however,
reports the `config` check as `failed`, worded as stale, and points at
`/sarathi:doctor`'s guided migration step to bring it up to schema v2.

## v1 → v2 migration

`/sarathi:doctor`'s guided setup (`init`) migrates an existing v1 config
in place: it reads and preserves `project_roots` and `output_path`
**unchanged, byte-for-byte**, asks only the one new question (`voice`), and
resolves `invoker` by proving a candidate Python interpreter (never asked
as a question — see the skill for the proof steps) — then writes back a
config.json with `schema_version: 2` and all four keys. It never re-asks
for roots or an output path that were already valid.

Migrating by hand: add `"voice"` (`"plain"` or `"gen_z"`) and `"invoker"`
(an absolute path to a Python 3.8+ executable) to the JSON object above,
and bump `"schema_version"` to `2`.

## Notes

- `project_roots` entries are parent directories, not project directories.
  A root that doesn't exist on disk (deleted/renamed) is reported under
  `facts.roots[<root>]` as `"status": "failed"` with a reason; a root that
  exists but currently has no child directories is reported `"status":
  "empty"`. Either way `sarathi measure` still exits 0 and produces a
  complete fact sheet — nothing else is affected.
- **Project-key disambiguation.** Keys in `facts.projects` are child-directory
  basenames (e.g. `"tokenomics"`). If two different configured roots each
  contain a child directory with the *same* basename, a bare-basename key
  would silently collide — instead, every child whose basename is not
  globally unique across all discovered projects gets its key qualified
  with its parent root's own basename, e.g. `"app (Projects)"` and `"app
  (work-projects)"`. In the rare case that even the qualified form
  collides, a numeric suffix (`" #2"`, `" #3"`, ...) is appended,
  assigned deterministically in configured-root order. Two entries never
  silently overwrite each other. Prefer giving projects globally unique
  names to avoid the qualified form altogether.
- Orphaned-memory detection (`facts.orphans`) compares memory directories
  under the config dir's `projects/` folder against the *currently
  discovered* children of each configured root — since every child that
  exists on disk is auto-discovered and measured, a memory directory that
  doesn't correspond to any discovered child genuinely means that project
  was renamed or deleted, not merely "not configured."
- Thresholds and other behavior-affecting constants (uncommitted-file
  count, stalled/dormant/thinking-vs-shipping day windows, etc.) are **not**
  configurable via `config.json` in this version — they live in one named
  constants block near the top of `sarathi.py`. Making them config-driven
  is a possible future evolution, not part of this schema. This includes
  the two constants v0.3 added — `THRESHOLDS["STEER_MAX_QUESTIONS"]` and
  `THRESHOLDS["ACTIVE_NEXT_GRACE_DAYS"]` (see below) — neither is a
  `config.json` key.

## Fact-sheet output: `decisions` / `ruled_flags` / `steer_candidates` (schema v2)

This section documents shapes `sarathi measure` *writes* into its output
fact sheet (the file at `output_path`) — not `config.json` keys. v0.3 adds
no config keys at all; everything below is output only, added by the
steer/realign feature (decision memory files, parsed back by `measure`).
The fact sheet's own `schema_version` bumped `1` → `2` for this addition —
every new key is additive and always present, never conditionally omitted,
so a v1-shaped consumer reading only the old keys keeps working.

### Decision memory files (new file type, not config)

Written exclusively by `/sarathi:report`'s realign step, read exclusively
by `measure`'s decision parser — never written by `sarathi.py` itself.
Location: `<config-dir>/projects/<slug>/memory/`, the same memory directory
`measure`'s `memory` subsection already reads. Filename (SAR-09 amends):
`sarathi-decision-<project-basename>-<YYYY-MM-DD>[-N].md` for projects,
`sarathi-decision-<YYYY-MM-DD>[-N].md` for orphans and all pre-SAR-09
files (the original shape stays matched forever), both covered by
`^sarathi-decision-(?:[A-Za-z0-9._-]+-)?\d{4}-\d{2}-\d{2}(?:-\d+)?\.md$` —
any file matching this pattern is permanently claimed as a decision file,
never reinterpreted as an ordinary memory entry even if its contents fail
to parse. Required frontmatter:

```
---
name: sarathi-decision-2026-08-01
description: "parked — waiting on the tokenomics contract to settle first"
type: sarathi-decision
verdict: parked
decided: 2026-08-01
---

Optional free-text body, truncated the same length as a regular memory
description (THRESHOLDS["DESCRIPTION_TRUNCATE_CHARS"]).
```

`verdict` is one of exactly four values (`VALID_VERDICT_VALUES` in
`sarathi.py`): `parked` | `active-next` | `dead` | `keep-watching`.
`decided` is an ISO `YYYY-MM-DD` date. Anything else (missing/unrecognized
verdict, missing/unparseable `decided`) is a parse failure, surfaced loudly
in `decisions.status`/`decisions.reason` — never silently dropped.

### `facts.projects.<key>.slug` (new)

Every project entry now carries its own config-dir slug — the same value
already used internally to resolve that project's `sessions`/`memory`
subsections (`slug(<absolute project root path>)`), now also exposed so a
consumer (realign) doesn't have to re-derive it from the display key, which
is not always a pure function of the path (see "Project-key
disambiguation" above).

### `facts.projects.<key>.decisions` / `facts.orphans.entries[i].decisions` (new)

Same `status`/`reason`/`entries` subsection shape as `git`/`files`/
`sessions`/`memory`:

- `"empty"` — no files under that memory directory match the decision
  filename pattern.
- `"ok"` — every matching file parsed; `entries` is the parsed list,
  sorted by `decided`, each carrying `{"verdict", "decided", "reason"
  (from the frontmatter `description`, truncated), "source" (filename),
  "expired": bool}`.
- `"ok"` with a non-null `reason` — a *partial* result: some matching
  files parsed, some didn't; `reason` names the ones that failed, `entries`
  holds only the ones that parsed.
- `"failed"` — every matching file failed to parse; `reason` names why;
  `entries` is `[]`.

`"expired"` (per entry): `true` iff any of that project's own activity
signals (`git.last_commit`, `sessions.last_session`, `files.newest`, plus
the max `date` across that project's own non-decision `memory.entries`) is
**strictly after** `decided` — not on-or-after, since writing the decision
file itself touches session-folder activity the same calendar day. For
orphans (no git/files/sessions at all), only the max-memory-entry-date
signal applies. **`active-next` additionally expires** once
`days_since(decided, facts.as_of) > THRESHOLDS["ACTIVE_NEXT_GRACE_DAYS"]`
even with zero activity — a broken "it's next" promise must not stay
suppressed forever. The other three verdicts never time-expire; only new
activity unrules them.

### `facts.projects.<key>.ruled_flags` (new)

A list of `{"flag", "verdict", "decided", "source"}`, one entry per
currently-in-`flags` flag name covered by the *most recent unexpired*
decision for that project. `[]` if no unexpired decision exists or the
project has no flags. **`flags` itself is never mutated** — `ruled_flags`
is a sibling annotation, always present.

### `facts.orphans.entries[i].ruled` (new)

`true` iff at least one unexpired decision exists for that orphan's memory
directory.

### `facts.steer_candidates` (new, top-level under `facts`)

A list, `[]` when there is nothing to steer — one entry per project/orphan
carrying at least one currently-unruled signal:

```json
{"kind": "project", "key": "tokenomics", "slug": "-Users-alice-Projects-tokenomics",
 "days_stalled": 45, "unruled_flags": ["dormant"]}
```
```json
{"kind": "orphan", "slug": "-Users-alice-Projects-old-thing",
 "days_stalled": 1000000, "unruled_flags": []}
```

`days_stalled` for a project reuses the same "days since most recent of
last commit / newest file / last session" computation the `dormant` flag
already uses; for an orphan it is
`THRESHOLDS["UNREACHABLE_DAYS_SENTINEL"]` (orphans always sort at or near
the top). The list is sorted by `days_stalled` descending, ties broken by
`slug` ascending — deterministic. `/sarathi:report`'s steer step reads the
top `THRESHOLDS["STEER_MAX_QUESTIONS"]` of this list as-is; it never
re-ranks, filters, or invents a candidate outside it.
