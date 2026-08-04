# Sarathi (सारथी)

*The charioteer for your side projects: deterministic code measures what you've built, an
LLM reads what it means, you steer with one small answer — and the decision is remembered,
so every run starts smarter.*

Sarathi is a four-stage loop:

1. **Measure** — a deterministic script scans your projects: git dates, uncommitted
   counts, session recency, memory ages. Byte-identical output on identical input,
   provable with a hash.
2. **Interpret** — an LLM reads the fact sheet and finds stalls, broken promises, and
   drift. Every claim must cite the fact rows behind it. The deliverable is **one living,
   animated artifact** — "Sarathi — Direction Report" — redeployed to the same URL every
   run, so the artifact platform's own version picker becomes the report's run history;
   when the Artifact tool isn't available, a local HTML file plays the same role instead.
3. **Steer** — you answer a few small questions, only about what data can't answer.
4. **Realign** — your answer becomes a dated decision ("parked, deliberately"), so the
   tool stops flagging what you already ruled on and gets quieter over time.

Since v0.5, a second, independent living artifact sits alongside the report: **"Sarathi —
Memory Ledger"** — every memory entry and every steering decision the fact sheet carries,
quoted verbatim, grouped into three fixed modules — **dev setup**, **working style**, and
**project memory** — published by `/sarathi:memory`. It performs no interpretation at all — no
moving/losing-steam/forgotten/ruled classification, no voice, nothing composed by the model —
a pure, read-only display of what `/sarathi:report` already reads about your memory files and
decisions, redeployed to its own URL the same way. Run either skill, both, or neither, in any
order; they never depend on each other.

Since v0.6, the ledger page opens in a compact **simple** view by default — headline stats plus
one line per entry — or a **verbose** view with every entry's full card, either by running
`/sarathi:memory --verbose` or by using the on-page toggle after the fact; a click on any row
also expands just that entry, independent of the page-wide view. Nothing about *what* the
ledger shows changed, only how it's grouped (three modules instead of five) and how much of
each entry is visible by default. If you've started tagging your own memory notes with a
`type: setup` frontmatter value — a personal habit for environment/tooling facts, nothing
Sarathi requires — those entries land in the `dev setup` module; everyone else simply sees that
module render "None recorded." until they adopt the same convention.

Since v0.7, both installing and updating Sarathi are things you can ask Claude Code to do in a
sentence, not command sequences you type yourself — the existing manual commands are kept as
the explicit alternative, never removed. `/sarathi:doctor` also gained one more check at the
very end of its own happy path: whether a newer tagged release exists on GitHub, offered as a
consent-gated update. This is the fourth, and lightest, network exception Sarathi has shipped —
see below.

**Current version: v0.7 — measure + doctor (now with an end-of-run update check), a**
**cited-interpretation report published as one redeployed artifact (or a local fallback file),**
**steer + realign, a second, independent living artifact — the memory ledger, three modules**
**wide, with simple/verbose views — exposing every memory entry and decision verbatim, and**
**install/update as a prompt you hand Claude Code, with the manual commands kept alongside.**

## Requirements

- Python 3.8+ (standard library only — no dependencies)
- `git` on PATH

## Install as a Claude Code plugin (recommended)

**Since v0.7, the easiest way to install is to just ask.** Tell Claude Code, in a sentence:

> Install the Sarathi plugin from github.com/Priyadarshiswain/sarathi

Claude Code runs, on your behalf:

```bash
claude plugin marketplace add Priyadarshiswain/sarathi
claude plugin install sarathi@sarathi
```

**The manual alternative** — if you'd rather type the commands yourself, the existing
slash-command form still works exactly as before, kept alongside the prompt-driven path, not
demoted or removed:

```
/plugin marketplace add Priyadarshiswain/sarathi
/plugin install sarathi
```

Both paths reach the same end state: the marketplace registered, the plugin installed, all
three skills available.

This installs three skills, `/sarathi:doctor`, `/sarathi:report`, and `/sarathi:memory`.
`/sarathi:doctor` self-heals a missing or stale config on first use — it walks you through
setup, proving every answer (Python interpreter, project-root discovery, output-path
writability) before writing anything — so there is no config file to hand-write. Once it
reports healthy, run `/sarathi:report` to get a cited interpretation of your projects, or
`/sarathi:memory` to see the raw memory entries and steering decisions behind it, quoted
verbatim with no interpretation at all — the two are independent; run either, or both, in
any order. `/sarathi:memory` opens its page in **simple** view by default; run
`/sarathi:memory --verbose` to open it in **verbose** view instead — either way, the on-page
toggle and each row's own click-to-expand switch density afterward without needing another run.

Since v0.8, `/sarathi:memory --scan` takes a different path entirely: instead of publishing
the ledger, it runs a deterministic scanner over your Claude Code memory folders and surfaces
what's organizationally wrong — entries filed under one project but verifiably *about* another
(they cite the other project's path), the same entry drifting apart in two folders, memory
folders for projects that no longer exist, index files out of sync with what's on disk, broken
`[[links]]`, and a token-cost table showing where the weight sits. Findings it can't decide it
asks about (closed questions, one per finding — "move it", "it stays", "archive it"); hygiene
fixes it batches into one itemized confirmation. Nothing is ever changed without your answer
in that same session, every file operation is shown with exact paths, and each ruling is
recorded so an unchanged corpus asks nothing on the next run. The scanner itself is plain
stdlib Python with zero network access, like `sarathi.py`; scan mode publishes no artifact.

Both the prompt-driven `claude plugin ...` commands and the manual `/plugin ...` slash commands
are Claude Code's own operations, and both reach the network (GitHub) to fetch the marketplace
and plugin contents — that access belongs to Claude Code's plugin infrastructure, not to
Sarathi, regardless of which of the two equivalent forms you (or Claude, on your behalf) use.
Once installed, `sarathi.py` itself still makes zero network calls, exactly as described below:
"no network, ever" is a claim about the tool, not about the one-time install step.

**A second, equally explicit exception, since v0.4:** when you run `/sarathi:report` and
the Artifact tool is available and used, the rendered report — project names, git/file/
session-derived claims, memory-derived claims, citation paths, and the steer-preview text —
is sent to the artifact-hosting platform so it can be rendered as a page with a shareable
URL. This is content you were already going to read in the chat transcript; only *where it
goes* is new. Scoped precisely: `sarathi.py` itself still makes zero network calls, always —
the exposure is entirely inside the report skill's publish step, an LLM-driven action using a
host-provided tool, the same category of exception as the plugin-install carve-out above
(host infrastructure initiating the network access, not Sarathi's own code). It happens only
when the Artifact tool is actually available and actually invoked — a session without that
tool (the common case for a bare CLI / headless run) never sends anything anywhere; the
local-fallback report file is fully local, matching every version through v0.3 exactly.
Artifacts start private (shareable only if you later choose to share them) — not "posted
publicly by default," but also not "stays on this machine." The skill states this every
single run it happens, never a one-time decision you forget was made.

**A third exception, since v0.5, and the most pointed one of the three:** `/sarathi:memory`'s
publish step, under the same conditions (Artifact tool available and used), sends the literal
text of your memory files off this machine — not the model's synthesis of your activity, the
actual dated notes, working-style feedback, and project-state records a past session wrote
about you, plus every steering decision's verdict and reasoning. Read that distinction again:
the report sends the model's own claims about what your git history and files show; the
memory ledger sends what you, or a past session on your behalf, actually wrote down about
yourself. Anything filed under a `"user"`-typed memory entry is personal context in the most
direct sense the fact sheet carries anywhere. The same scoping applies — zero network calls
from `sarathi.py` itself, exposure confined to this one skill's publish step, only when the
Artifact tool is available and used, artifacts start private, orphan source names are always
the trimmed, username-redacted slug (identical mitigation to the report's) — but the content
itself carries more of you than anything Sarathi has published before, and the skill says so
in-session every time this path runs, not as a one-time notice.

**A fourth exception, since v0.7, and the lightest one Sarathi has shipped.** At the end of a
successful `/sarathi:doctor` run, the skill makes one anonymous, read-only `git ls-remote
--tags` request against `github.com/Priyadarshiswain/sarathi` to check whether a newer release
exists — nothing about you, your projects, or your memory files leaves the machine this way.
Unlike the report's and the ledger's own exceptions above, this one sends no user content at
all: the request is exactly what any anonymous visitor to that public GitHub repo could already
see, and `check_update.py`, the script that actually parses the result, never even receives a
URL — only the already-fetched text and a local `plugin.json` path — so there is no code path
by which this exception could carry your content, structurally, not merely by policy. It only
runs when doctor's own result is a confirmed success; a `stop`ped or declined run never makes
this request. `sarathi.py` itself still makes zero network calls, always — this, like every
exception above, lives entirely inside a skill's own step, not inside the deterministic script.
If you choose to update, `claude plugin update sarathi@sarathi` is a second, separate,
explicitly consent-gated action that reaches GitHub again via Claude Code's own plugin
infrastructure — the same category of access already disclosed for install above, not a new
kind of exception. The skill states what's happening every single run this step is reached,
never a one-time notice.

## Updating

Since v0.7, there are three equivalent ways to update, in the order you're most likely to
reach for them:

1. **Ask Claude Code** — the same prompt-driven shape as install: "check if there's a newer
   Sarathi release" or "update Sarathi." Claude reaches for the same `claude plugin update
   sarathi@sarathi` command below.
2. **Run `/sarathi:doctor`** — since v0.7, it checks for a newer release at the end of its own
   happy path and offers to update, consent-gated (see the fourth network exception above). It
   never updates without asking first.
3. **Run the manual command yourself:**
   ```bash
   claude plugin update sarathi@sarathi
   ```

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
  `/sarathi:report`'s realign step writes on your explicit, answered say-so, plus (from v0.4)
  the local-fallback report file the publish step writes only when the Artifact tool is
  unavailable or errors, plus (from v0.5) the local-fallback memory-ledger file
  `/sarathi:memory`'s publish step writes under the identical condition — never silent,
  always shown to you verbatim with the exact path, never anything else. `sarathi.py` itself
  makes zero network calls, always — the exceptions are `/sarathi:report`'s and
  `/sarathi:memory`'s own publish steps sending their rendered pages to the Artifact tool's
  hosting platform, only when that tool is available and used (see above). `/sarathi:memory`'s
  ledger mode is stronger still on the write side: it never writes a memory file, a decision
  file, or `MEMORY.md` — read-only end to end. Its scan mode (v0.8) is the one deliberate
  exception to that read-only stance, and it writes nothing until you answer: every move,
  merge, archive, index fix, and ruling record happens only on consent given in that same
  session, is shown verbatim with exact paths, and deletes are confirmed one file at a time,
  never inside a batch yes. No telemetry, ever.

## Privacy

The complete data-flow picture, consolidated from the sections above — nothing here is new,
and if this section ever disagrees with the detailed prose above, the detailed prose wins:

- **`sarathi.py` makes zero network calls, always.** This is a permanent design invariant,
  not a current implementation detail. The measurement script reads only local files (your
  git repositories, Claude Code session and memory files under your config directory) and
  writes only its own configured output file. No telemetry, ever.
- **Exactly four network exceptions exist, all in the skill layer, all disclosed in
  detail above:**
  1. **Plugin install/update** — Claude Code's own marketplace infrastructure fetches this
     repository from GitHub. Host infrastructure, not Sarathi's code.
  2. **`/sarathi:report` publish** — sends the rendered report (the model's cited claims
     about your projects) to claude.ai's artifact hosting, only when the Artifact tool is
     available and used. Disclosed in-session every run. Artifacts start private.
  3. **`/sarathi:memory` publish** — sends your memory entries and steering decisions,
     verbatim, to the same artifact hosting under the same conditions. This is the most
     personal content Sarathi handles, and the skill says so explicitly on every run.
     Orphaned-project names are trimmed so your OS username never leaves the machine.
  4. **`/sarathi:doctor` version check** — one anonymous, read-only `git ls-remote` against
     this public repository's tag list. Nothing about you or your projects is sent.
     Updating afterward is a separate, consent-gated action.
- **Write surface, complete list:** the config file (during guided setup), the fact-sheet
  output file, dated decision files written only on your explicitly answered say-so during
  realign, local-fallback report/ledger HTML files written only when the Artifact tool
  is unavailable, and — since v0.8, all of it consent-gated inside `/sarathi:memory --scan` —
  the scan findings JSON (next to the fact sheet), the organize fixes you approve inside
  `<config-dir>/projects/*/memory/` (moves, index lines, frontmatter fills, link removals),
  the archive tree `<config-dir>/memory-archive/` fixes move entries into, and dated
  `sarathi-organize-*.md` ruling records. Scan mode adds **no network exception** — the
  scanner is zero-network like `sarathi.py`, and scan mode publishes nothing. The Uninstall
  section below accounts for every one of them.
- **No secrets, tokens, or credentials are ever read or logged.**

## Uninstall

If you installed the plugin, remove it first:

```
/plugin uninstall sarathi
```

This removes the installed `sarathi:doctor`, `sarathi:report`, and `sarathi:memory` skills and
unregisters the plugin from Claude Code. It is **not** the same operation as the manual
cleanup below — uninstalling the plugin never touches your config, your fact-sheet output, or
any decision file it wrote, on purpose, the same way `doctor`/`report`/`memory` never write
outside their documented files. If you also want to remove those, or if you only ever used the
bare-clone path, Sarathi's remaining footprint is small and fully accounted for:

```bash
rm -rf <clone-dir>             # the code (wherever you cloned this repo), if you cloned it
rm -rf <config-dir>/sarathi    # config; <config-dir> is $CLAUDE_CONFIG_DIR or ~/.claude
rm <output-path>               # the fact sheet, at the output_path you set in config.json
rm <dir of output-path>/report-*.html   # local fallback report(s), from v0.4, if any exist
rm <dir of output-path>/ledger-*.html   # local fallback ledger(s), from v0.5, if any exist
rm <dir of output-path>/sarathi-findings.json  # scan findings, from v0.8, if you ever ran --scan
rm -rf <config-dir>/memory-archive     # entries scan mode archived on your say-so, from v0.8
```

Since v0.3, `/sarathi:report`'s realign step also writes decision files named
`sarathi-decision-<date>[-N].md` (since v0.8 usually `sarathi-decision-<project>-<date>[-N].md`)
inside the same per-project memory directories Claude Code already maintains under
`<config-dir>/projects/<slug>/memory/` — the same directories `doctor`/`report` were already
reading from before v0.3, not a new location Sarathi introduced. Since v0.8,
`/sarathi:memory --scan` records its rulings in `sarathi-organize-<date>[-N].md` files in the
same places. Both kinds are plain markdown, easy to find (`find <config-dir>/projects -name
'sarathi-decision-*.md' -o -name 'sarathi-organize-*.md'`) and delete by hand if you want a
truly clean slate; leaving them is also fine — an uninstalled Sarathi simply stops reading
them. One caution unique to scan mode: fixes you approved (moved or archived entries, edited
index lines) changed your memory folders themselves — that's their job, they were shown to
you at the time, and uninstalling doesn't (and couldn't) revert them.

That's a complete removal of everything on this machine. Sarathi writes no caches, no state
in your project directories, nothing outside the paths above — and `sarathi.py` itself never
talks to the network, so there is no account or remote data of *its own* to clean up (the
plugin-install step and the Artifact-tool publish steps are the exceptions, all of them
Claude Code's own network access, not Sarathi's — see above). One thing this local cleanup
does **not** reach: if `/sarathi:report` and/or `/sarathi:memory` ever published to the
Artifact tool, an artifact titled "Sarathi — Direction Report" and/or "Sarathi — Memory
Ledger" remains on that hosting platform, inert, after an uninstall — nothing in this
codebase ever deletes an artifact it created, only creates or updates one, mirroring
decision files' own never-delete discipline above. Delete either one by hand on the artifact
platform if you want it gone.

## Acknowledgements

Substantial portions of this codebase were written and reviewed with
[Claude](https://claude.com) (Anthropic). The design, the decisions, and the
responsibility for what ships are the author's.
