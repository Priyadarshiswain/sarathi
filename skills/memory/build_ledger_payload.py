#!/usr/bin/env python3
"""build_ledger_payload.py — deterministic, mechanical assembly of the
Sarathi memory-ledger payload (story SAR-05 §6, amended by SAR-06 §6) from
the fact sheet `sarathi.py measure` already wrote.

Pure Python 3, stdlib only. No network calls, ever. One pure function:

    build_payload(fact_sheet, default_view="simple") -> payload

plus a CLI wrapping it, invoked by skills/memory/SKILL.md's §4 the same
way that skill already shells out to sarathi.py and
skills/report/render_report.py. This script exists because SAR-05's
rule-3 posture is sharper than SAR-04's report payload: every field here
is either copied character-for-character from the fact sheet or a pure
aggregate (a count, a grouping) computed by a fixed, restatable rule —
there is no "which section does this belong in" judgment call anywhere,
so the mechanical walk belongs in a two-line, unit-testable script
instead of something assembled by hand at generation time (design rule 3;
SAR-05 §4/§8, and §12's note on acceptance criterion 9, which this
approach answers by making the payload builder itself Python-testable in
isolation — see the story's "Implementation handoff" section).
SKILL.md's own publish step invokes this script exactly the way it
already invokes render_report.py; it never re-derives this walk by hand.

SAR-06 amends this file two ways (its own §3, the one file in the memory
skill that story explicitly expects to change): the five-group bucketing
rule collapses to three fixed modules (`setup` / `working_style` /
`project_memory`, §6 below), and `build_payload()`/the CLI gain an
explicit `default_view` input (`"simple"` or `"verbose"`) written into
`meta.default_view` — never inferred from `config.json` or any fact-sheet
field, only from this explicit parameter/flag (SAR-06 §6's field-mapping
table).

sarathi.py itself has zero diff in this story (SAR-05 §3, SAR-06 §3) —
this script only *reads* the fact sheet sarathi.py already writes.
`slug()` below is copied verbatim from sarathi.py's own slug(), not
imported, so this script stays a standalone, dependency-free CLI — the
same posture render_report.py already takes relative to sarathi.py.
"""
import argparse
import json
import os
import re
import sys

# -- fixed, pinned shape (SAR-06 §6, supersedes SAR-05's five-group table) --
MODULE_ORDER = ["setup", "working_style", "project_memory"]
MODULE_LABELS = {
    "setup": "dev setup",
    "working_style": "working style",
    "project_memory": "project memory",
}
# Each module's native `type` value — the fixed constant the front-end
# chip rule keys off (never re-derived from an entry actually present in
# that module; SAR-06 §6 acceptance criterion 5).
MODULE_NATIVE_TYPE = {
    "setup": "setup",
    "working_style": "feedback",
    "project_memory": "project",
}
DEFAULT_VIEWS = ("simple", "verbose")


def slug(path):
    """Slugify an absolute path — copied verbatim from sarathi.py's own
    slug(), the same Claude-Code session-folder naming rule
    facts.orphans.entries[*].slug is already written against (SAR-05 §6:
    "the exact same procedure SAR-04 §7/§6 already specifies"). Restated
    here, not re-derived and not imported, so this script has no runtime
    dependency on sarathi.py's own module (the same independence
    render_report.py already has)."""
    return re.sub(r"[^A-Za-z0-9]", "-", path)


def bucket_for_type(type_value):
    """Fixed rule (SAR-06 §6, acceptance criteria 1-2, supersedes SAR-05's
    bucket_for_type()): `"setup"` (exact, case-sensitive) sorts into the
    `setup` module; `"feedback"` or `"user"` sort into `working_style`;
    everything else — `"project"`, `"reference"`, the literal `"untyped"`
    default sarathi.py itself writes when a memory file's frontmatter
    carries no `type` key, and any other free-text value a hand-written
    frontmatter `type:` line could carry — sorts into `project_memory`.
    This function only decides *where* an entry is grouped; the caller is
    responsible for copying the entry's own `type` field into the payload
    unrewritten (criterion 2's negative check)."""
    if type_value == "setup":
        return "setup"
    if type_value in ("feedback", "user"):
        return "working_style"
    return "project_memory"


def _match_root(raw_slug, roots):
    """Return the configured root (a facts.roots key) whose slug-prefix
    matches `raw_slug`, or None. Same prefix collect_orphans() already
    matched to produce this orphan entry in the first place (SAR-04 §7 /
    SAR-05 §6: `slug(os.path.normpath(root)) + "-"`). Iterated in sorted
    key order for determinism — makes no assumption about json.load()'s
    dict-ordering behavior, even though the fact sheet is itself written
    with sort_keys=True."""
    for root in sorted(roots.keys()):
        prefix = slug(os.path.normpath(root)) + "-"
        if raw_slug.startswith(prefix):
            return root
    return None


def _trim_orphan_slug(raw_slug, roots):
    """The payload's `source` value for an orphan entry: the matched
    root's prefix stripped from the front of the raw slug (privacy —
    SAR-05 §6, identical procedure to SAR-04 §6/§7 — the raw slug embeds
    the local OS username and must never appear in payload content).
    Falls back to the raw slug only if no configured root's prefix
    matches (shouldn't happen for anything collect_orphans() itself
    produced, but this never silently KeyErrors if it does)."""
    root = _match_root(raw_slug, roots)
    if root is None:
        return raw_slug
    prefix = slug(os.path.normpath(root)) + "-"
    return raw_slug[len(prefix):]


def _entry_payload(entry, source, source_kind):
    """One `modules[*].entries[]` item — every string field copied
    verbatim (acceptance criterion 4: no truncation beyond what
    sarathi.py itself already applied, no paraphrase, no voice
    adjustment)."""
    return {
        "name": entry.get("name", ""),
        "desc": entry.get("desc", ""),
        "date": entry.get("date", ""),
        "type": entry.get("type", "untyped"),
        "source": source,
        "source_kind": source_kind,
        "threads": list(entry.get("threads", [])),
    }


def _decision_payload(decision, source, source_kind):
    return {
        "source": source,
        "source_kind": source_kind,
        "verdict": decision.get("verdict"),
        "decided": decision.get("decided"),
        "reason": decision.get("reason", ""),
        "source_file": decision.get("source"),
        "expired": bool(decision.get("expired")),
    }


def _memory_caveat(status, reason, source, source_kind):
    """Rule 2 (fail loudly, never emptily): a source whose memory status
    is "failed", or "ok" with a non-null `reason` (a partial parse), must
    surface a caveat — never silently dropped (acceptance criterion 14)."""
    if status == "failed" or (status == "ok" and reason):
        return {"source": source, "source_kind": source_kind, "kind": "memory",
                "status": status, "reason": reason}
    return None


def _decisions_caveat(decisions_sub, source, source_kind):
    status = decisions_sub.get("status")
    reason = decisions_sub.get("reason")
    if status == "failed" or (status == "ok" and reason):
        return {"source": source, "source_kind": source_kind, "kind": "decisions",
                "status": status, "reason": reason}
    return None


def _root_caveat(raw_slug, roots, source, source_kind):
    """SAR-05 §6's `facts.roots` reliability caveat (acceptance criterion
    15): an orphan whose matched root currently reports "failed" or
    "empty" carries a `root_unreadable` caveat — a root that couldn't be
    read right now is a reason a project might not really be gone, not
    proof that it is."""
    root = _match_root(raw_slug, roots)
    if root is None:
        return None
    root_entry = roots.get(root) or {}
    status = root_entry.get("status")
    if status not in ("failed", "empty"):
        return None
    detail = root_entry.get("reason")
    reason = (
        "root '{0}' currently reports status '{1}'".format(root, status)
        + (": {0}".format(detail) if detail else "")
    )
    return {"source": source, "source_kind": source_kind, "kind": "root_unreadable",
            "status": status, "reason": reason}


def build_payload(fact_sheet, default_view="simple"):
    """The one pure function this script exists for. `fact_sheet` is the
    full JSON object `sarathi.py measure` writes (top-level
    `schema_version`/`run`/`facts`) — exactly what `--facts` points at.
    `default_view` (SAR-06 §6, new this story) is an explicit,
    non-fact-sheet-derived input — `"simple"` by default, matching the
    CLI's own default — written straight into `meta.default_view`; never
    read from `config.json` or any fact-sheet field (acceptance
    criterion 9).

    Reads only the documented paths (acceptance criterion 9):
    facts.projects.*.memory, facts.projects.*.decisions,
    facts.orphans.entries[*].memory, facts.orphans.entries[*].decisions,
    facts.roots, facts.as_of, run.generated_at, and the explicit
    `default_view` argument. `facts.steer_candidates` and every other
    unrelated field is never read.

    Deterministic given the same input (rule 1): same fact sheet + same
    `default_view` -> byte-identical payload, every time — no randomness,
    no session-order dependence, no wall-clock read of its own. Ordering
    follows the fact sheet's own already-deterministic structure (SAR-05
    §6, restated by SAR-06 §11 criterion 10): projects in key order, then
    orphans in the fact sheet's own list order, then within a source in
    the order sarathi.py already wrote its entries — never independently
    re-sorted here, and never re-sorted *within* a module by the new
    three-way bucketing either.
    """
    facts = fact_sheet["facts"]
    as_of = facts["as_of"]
    generated_at = fact_sheet["run"]["generated_at"]
    roots = facts.get("roots", {}) or {}

    modules = {m: [] for m in MODULE_ORDER}
    decisions = []
    caveats = []
    sources_with_memory = 0

    # -- projects, in key order (SAR-05 §6 traversal step 1). ---------------
    projects = facts.get("projects", {}) or {}
    for key in sorted(projects.keys()):
        project = projects[key]
        if project.get("status") != "ok":
            # Acceptance criterion 8: a "failed" whole-entry project (a
            # configured child directory that vanished between discovery
            # and measurement) carries no "memory"/"decisions" key at all
            # — skip it without touching either, no KeyError, no crash.
            continue

        memory_sub = project.get("memory", {}) or {}
        entries = memory_sub.get("entries", []) or []
        if entries:
            sources_with_memory += 1
        for entry in entries:
            module_key = bucket_for_type(entry.get("type", "untyped"))
            modules[module_key].append(_entry_payload(entry, key, "project"))
        caveat = _memory_caveat(memory_sub.get("status"), memory_sub.get("reason"), key, "project")
        if caveat:
            caveats.append(caveat)

        decisions_sub = project.get("decisions", {}) or {}
        if decisions_sub.get("status") == "ok":
            for decision in decisions_sub.get("entries", []) or []:
                decisions.append(_decision_payload(decision, key, "project"))
        caveat = _decisions_caveat(decisions_sub, key, "project")
        if caveat:
            caveats.append(caveat)

    # -- orphans, in the fact sheet's own already-deterministic list order
    # (SAR-05 §6 traversal step 2). ------------------------------------------
    orphan_entries = (facts.get("orphans", {}) or {}).get("entries", []) or []
    for orphan in orphan_entries:
        raw_slug = orphan["slug"]
        source = _trim_orphan_slug(raw_slug, roots)

        entries = orphan.get("memory", []) or []
        if entries:
            sources_with_memory += 1
        for entry in entries:
            module_key = bucket_for_type(entry.get("type", "untyped"))
            modules[module_key].append(_entry_payload(entry, source, "orphan"))
        caveat = _memory_caveat(orphan.get("status"), orphan.get("reason"), source, "orphan")
        if caveat:
            caveats.append(caveat)

        decisions_sub = orphan.get("decisions", {}) or {}
        if decisions_sub.get("status") == "ok":
            for decision in decisions_sub.get("entries", []) or []:
                decisions.append(_decision_payload(decision, source, "orphan"))
        caveat = _decisions_caveat(decisions_sub, source, "orphan")
        if caveat:
            caveats.append(caveat)

        caveat = _root_caveat(raw_slug, roots, source, "orphan")
        if caveat:
            caveats.append(caveat)

    by_module = {m: len(modules[m]) for m in MODULE_ORDER}
    total_entries = sum(by_module.values())

    hh_mm = generated_at[11:16] if len(generated_at) >= 16 else ""
    version_label = "{0} · {1} UTC".format(as_of, hh_mm)

    return {
        "meta": {
            "as_of": as_of,
            "generated_at": generated_at,
            "version_label": version_label,
            "default_view": default_view,
        },
        "stats": {
            "total_entries": total_entries,
            "by_module": by_module,
            "sources_with_memory": sources_with_memory,
            "steering_decisions": len(decisions),
        },
        "modules": [
            {
                "key": m,
                "label": MODULE_LABELS[m],
                "native_type": MODULE_NATIVE_TYPE[m],
                "entries": modules[m],
            }
            for m in MODULE_ORDER
        ],
        "decisions": decisions,
        "caveats": caveats,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(prog="build_ledger_payload.py")
    parser.add_argument("--facts", required=True,
                         help="path to the fact sheet sarathi.py measure wrote")
    parser.add_argument("--default-view", choices=list(DEFAULT_VIEWS), default="simple",
                         help="initial display density the rendered page opens in "
                              "(SAR-06 §6/§8) -- an invalid value is a loud, non-zero-exit "
                              "argparse failure, never silently coerced (rule 2)")
    parser.add_argument("--out", default=None,
                         help="write the payload JSON to this path instead of stdout")
    args = parser.parse_args(argv)

    with open(args.facts, "r", encoding="utf-8") as fh:
        fact_sheet = json.load(fh)

    payload = build_payload(fact_sheet, default_view=args.default_view)
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.write("\n")
    else:
        sys.stdout.write(text)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
