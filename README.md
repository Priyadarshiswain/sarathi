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

**Current version: v0.1 — stage 1 only** (`measure` + `doctor`). Interpretation, steering,
and realignment are on the roadmap.

## Requirements

- Python 3.8+ (standard library only — no dependencies)
- `git` on PATH

## Quick start

Create `<config-dir>/sarathi/config.json`, where `<config-dir>` is `$CLAUDE_CONFIG_DIR`
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
- Reads only local files; writes only its own output. No network, no telemetry, ever.

## Uninstall

Sarathi's footprint is deliberately small — three paths, nothing else:

```bash
rm -rf <clone-dir>             # the code (wherever you cloned this repo)
rm -rf <config-dir>/sarathi    # config; <config-dir> is $CLAUDE_CONFIG_DIR or ~/.claude
rm <output-path>               # the fact sheet, at the output_path you set in config.json
```

That's a complete removal. Sarathi writes no caches, no state in your project
directories, nothing outside the paths above — and it never talks to the network, so
there is no account or remote data to clean up.

## Acknowledgements

Substantial portions of this codebase were written and reviewed with
[Claude](https://claude.com) (Anthropic). The design, the decisions, and the
responsibility for what ships are the author's.
