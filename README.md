# Sarathi (सारथी)

*The charioteer for your side projects: deterministic code measures what you've built, an
LLM reads what it means, you steer with one small answer — and the decision is remembered,
so every run starts smarter.*

Sarathi is a four-stage loop:

1. **Measure** — a deterministic script scans your projects: git dates, uncommitted
   counts, session recency, memory ages. Byte-identical output on identical input,
   provable with a hash.
2. **Interpret** — an LLM reads the fact sheet and finds stalls, broken promises, and
   drift. Every claim must cite the fact rows behind it.
3. **Steer** — you answer a few small questions, only about what data can't answer.
4. **Realign** — your answer becomes a dated decision ("parked, deliberately"), so the
   tool stops flagging what you already ruled on and gets quieter over time.

**Current version: v0.3 — all four stages now ship: measure + doctor, a cited-interpretation**
**report skill (moving / losing steam / forgotten / ruled), and steer + realign — your answers**
**become dated decision files that quiet the report on every later run.**

## Requirements

- Python 3.8+ (standard library only — no dependencies)
- `git` on PATH

## Install as a Claude Code plugin (recommended)

```
/plugin marketplace add Priyadarshiswain/sarathi
/plugin install sarathi
```

This installs two skills, `/sarathi:doctor` and `/sarathi:report`. `/sarathi:doctor`
self-heals a missing or stale config on first use — it walks you through setup, proving
every answer (Python interpreter, project-root discovery, output-path writability) before
writing anything — so there is no config file to hand-write. Once it reports healthy, run
`/sarathi:report` to get a cited interpretation of your projects.

`/plugin marketplace add` and `/plugin install` are Claude Code's own operations and do
reach the network (GitHub) to fetch the marketplace and plugin contents — that access
belongs to Claude Code's plugin infrastructure, not to Sarathi. Once installed, `sarathi.py`
itself still makes zero network calls, exactly as described below: "no network, ever" is a
claim about the tool, not about the one-time install step.

## Quick start (bare clone, no plugin)

Cloning the repo and running the script directly keeps working exactly as before — the
plugin wraps `sarathi.py`, it never replaces this path. Create
`<config-dir>/sarathi/config.json`, where `<config-dir>` is `$CLAUDE_CONFIG_DIR`
if set, otherwise `~/.claude`:

```json
{
  "schema_version": 1,
  "project_roots": ["/path/to/your/projects"],
  "output_path": "/path/to/facts.json"
}
```

`project_roots` are **parent directories** — every child directory is auto-discovered as a
project. You never hand-list projects; a new one appears in the next run automatically.
Full key reference: [docs/config-schema.md](docs/config-schema.md).

Then:

```bash
python3 sarathi.py doctor
```

checks your environment (Python version, git, config validity, paths) and names anything
broken with its exact fix. When it's green:

```bash
python3 sarathi.py --as-of 2026-08-01
```

writes the JSON fact sheet. `--as-of` pins the reference date all age-based verdicts are
computed against (defaults to today); same project trees + same date → byte-identical
`facts`, so runs are reproducible and comparable.

## Design rules

- Deterministic given the config — logic is universal, machine variance lives in config.
- Fail loudly, never emptily — every section reports `ok` / `failed: reason` / `empty`;
  "couldn't look" is never dressed up as "nothing found".
- Reads only local files; writes only its own output, plus (from v0.3) the decision files
  `/sarathi:report`'s realign step writes on your explicit, answered say-so — never silent,
  always shown to you verbatim with the exact path, never anything else. No network, no
  telemetry, ever.

## Uninstall

If you installed the plugin, remove it first:

```
/plugin uninstall sarathi
```

This removes the installed `sarathi:doctor` and `sarathi:report` skills and unregisters
the plugin from Claude Code. It is **not** the same operation as the manual cleanup below —
uninstalling the plugin never touches your config, your fact-sheet output, or any decision
file it wrote, on purpose, the same way `doctor`/`report` never write outside their
documented files. If you also want to remove those, or if you only ever used the bare-clone
path, Sarathi's remaining footprint is small and fully accounted for:

```bash
rm -rf <clone-dir>             # the code (wherever you cloned this repo), if you cloned it
rm -rf <config-dir>/sarathi    # config; <config-dir> is $CLAUDE_CONFIG_DIR or ~/.claude
rm <output-path>               # the fact sheet, at the output_path you set in config.json
```

Since v0.3, `/sarathi:report`'s realign step also writes decision files named
`sarathi-decision-<date>[-N].md` inside the same per-project memory directories Claude Code
already maintains under `<config-dir>/projects/<slug>/memory/` — the same directories
`doctor`/`report` were already reading from before v0.3, not a new location Sarathi
introduced. They're plain markdown, easy to find (`find <config-dir>/projects -name
'sarathi-decision-*.md'`) and delete by hand if you want a truly clean slate; leaving them is
also fine — an uninstalled Sarathi simply stops reading them.

That's a complete removal. Sarathi writes no caches, no state in your project
directories, nothing outside the paths above — and `sarathi.py` itself never talks to the
network, so there is no account or remote data to clean up (the plugin install step is the
one exception, and it's Claude Code's own network access, not Sarathi's — see above).

## Acknowledgements

Substantial portions of this codebase were written and reviewed with
[Claude](https://claude.com) (Anthropic). The design, the decisions, and the
responsibility for what ships are the author's.
