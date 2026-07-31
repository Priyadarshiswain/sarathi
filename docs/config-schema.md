# `config.json` schema

`sarathi measure` and `sarathi doctor` read one config file:

```
<config-dir>/sarathi/config.json
```

where `<config-dir>` is `$CLAUDE_CONFIG_DIR` if that environment variable is
set, otherwise `~/.claude`. The config-dir override is an environment
variable only — it is never a key inside the config file itself, because a
config file can't relocate the directory it lives in.

There is no `sarathi init` yet (planned for v0.2). Until then, write this
file by hand, or have an LLM fill in the values below and save it — the
LLM fills the form, it does not invent the logic that reads it.

## Keys

Every key below is **required**. Any key not listed here is **rejected by
name** when the config is loaded (`unknown config key: '<name>'`) — a typo
must never silently change behavior. There are no optional keys in schema
version 1.

| Key | Type | Description |
|---|---|---|
| `schema_version` | integer | Config schema version. Must equal `1` for this version of the script. `sarathi doctor` reports the config as stale if it doesn't match. |
| `project_roots` | array of strings | Absolute paths to **parent directories**, e.g. `~/Projects` — not individual project paths. Each root is auto-scanned for its immediate child directories, and every child found is one measured project. There is no hand-maintained list of individual projects: a new directory created under a configured root shows up in the fact sheet on the very next `measure` run, with no config edit. Each discovered child is scanned for files, git state, and (via its slug under the config dir's `projects/` folder) Claude session and memory history. |
| `output_path` | string | Path (absolute or relative to the current working directory) where `sarathi measure` writes its JSON fact sheet. The containing directory is created if it doesn't exist. `sarathi doctor` never writes here — it only checks that the location is writable. |

## Example

```json
{
  "schema_version": 1,
  "project_roots": [
    "/Users/alice/Projects",
    "/Users/alice/work-projects"
  ],
  "output_path": "/Users/alice/.claude/sarathi/facts.json"
}
```

With this config, every immediate subdirectory of `/Users/alice/Projects`
and of `/Users/alice/work-projects` is discovered and measured — e.g. a
`tokenomics/` folder under either one becomes a `facts.projects` entry
automatically, with no need to list `tokenomics` in the config.

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
  is a possible future evolution, not part of this schema.
