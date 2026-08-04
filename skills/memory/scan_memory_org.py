#!/usr/bin/env python3
"""scan_memory_org.py — deterministic memory-organization detectors
(story SAR-10, the three families).

Pure Python 3, stdlib only. Git (already Sarathi's sole external tool) is
the ONLY subprocess, used solely for detector 3e's last-commit date. No
network calls, ever. No model in the loop: every finding is produced by a
fixed, restatable rule over the memory folders under
<config-dir>/projects/ and the project directories under the configured
roots — same rule-3 posture as build_ledger_payload.py, and like that
script the few sarathi.py helpers needed (slug, config resolution) are
copied verbatim rather than imported, keeping this a standalone CLI.

Detection ONLY (SAR-10 §3/§7): this script asks nothing and fixes
nothing. skills/memory/SKILL.md's scan mode (SAR-11) consumes the
findings JSON it writes.

Bans carried as code, not comments (SAR-10 §2):
- Signal 3 (body mention-counting of other project names) does not exist
  here and must never be added — an entry *using* another project is a
  cross-reference, not contamination (owner ruling 2026-08-04).
- Lifecycle classification (completed / in-progress / acted-on) does not
  exist here at any keyword budget (owner ruling 2026-08-04).
- Detector 3e reads file mtimes and git commit dates only — NEVER dates
  scraped from prose (measured false positive: a domain-expiry date in an
  entry body reads as "memory activity").

Output: one findings JSON document, schema-versioned, additive-only.
Findings are sorted (family, detector, home, entry, target) and carry a
deterministic id — byte-identical output for an unchanged corpus
(meta.corpus_hash makes "unchanged" itself checkable).

Every finding is labeled with its determinism basis (SAR-10 §2):
  basis: "observation" — filesystem/git fact, true no matter who wrote
         the entry (content hash, cited path, mtime, transcript file).
  basis: "convention"  — a read of a self-declared field (frontmatter
         type, declared supersession), only as good as writing discipline.
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys

FINDINGS_SCHEMA_VERSION = 1

# Known frontmatter types: the four documented in the memory instructions,
# plus the user-global `setup` convention (SAR-06) and Sarathi's own
# decision type (SAR-03).
KNOWN_TYPES = {"user", "feedback", "project", "reference", "setup",
               "sarathi-decision"}

# Decision filenames, both shapes: the SAR-03 original
# (sarathi-decision-<date>.md) and the SAR-09 slug-bearing form
# (sarathi-decision-<project-basename>-<date>.md), each with the optional
# collision suffix. Kept in sync with sarathi.py's DECISION_FILENAME_RE.
DECISION_FILENAME_RE = re.compile(
    r"^sarathi-decision-(?:[A-Za-z0-9._-]+-)?\d{4}-\d{2}-\d{2}(?:-\d+)?\.md$"
)

# Scan-mode bookkeeping files (SKILL.md §9.4). Not memory entries subject
# to organization — excluded from the corpus exactly like MEMORY.md, so
# the detectors never flag the scan's own records (same-basename would
# otherwise fire on every same-day ruling across folders — the very trap
# SAR-09's rename fixed for decision files).
ORGANIZE_FILENAME_RE = re.compile(r"^sarathi-organize-")

WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
MDLINK_RE = re.compile(r"\]\(([^)#?]+\.md)\)")
SESSION_ID_RE = re.compile(r"originSessionId:\s*([0-9a-fA-F-]{36})")
SUPERSEDE_RE = re.compile(r"^.*supersed.*$", re.I | re.M)

DEFAULT_GAP_DAYS = 60  # detector 3e threshold (SAR-10 §6 ruling default)


# -- helpers copied verbatim from sarathi.py (standalone-CLI posture) -------

def resolve_config_dir():
    override = os.environ.get("CLAUDE_CONFIG_DIR")
    if override:
        return override
    return os.path.join(os.path.expanduser("~"), ".claude")


def slug(path):
    return re.sub(r"[^A-Za-z0-9]", "-", path)


def _git_last_commit_date(project_dir, timeout=10):
    """ISO date (YYYY-MM-DD) of the last commit, or None. LC_ALL=C like
    every other Sarathi git call; any failure is a loud None, never a
    guess (design rule 2 — but a missing repo is legitimate, not an
    error)."""
    if not os.path.isdir(os.path.join(project_dir, ".git")):
        return None
    env = dict(os.environ, LC_ALL="C")
    try:
        out = subprocess.run(
            ["git", "-C", project_dir, "log", "-1", "--format=%cs"],
            capture_output=True, text=True, timeout=timeout, env=env,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    val = out.stdout.strip()
    return val if re.fullmatch(r"\d{4}-\d{2}-\d{2}", val) else None


# -- corpus loading ---------------------------------------------------------

def _read_text(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


def _frontmatter(text, keys):
    """Loose `key: value` reads from a leading --- block, mirroring
    sarathi.py's extract_frontmatter tolerance."""
    out = {k: None for k in keys}
    if not text.startswith("---"):
        return out
    end = text.find("\n---", 3)
    block = text[:end] if end != -1 else text[:2000]
    for k in keys:
        m = re.search(rf"^\s*{re.escape(k)}:\s*(.*)$", block, re.M)
        if m:
            out[k] = m.group(1).strip().strip('"').strip("'") or None
    return out


def load_corpus(config_dir):
    """Every memory folder under <config-dir>/projects/, every .md entry
    in it (MEMORY.md held separately as the index). Sorted walk —
    determinism by construction."""
    projects_dir = os.path.join(config_dir, "projects")
    corpus = {}
    try:
        slugs = sorted(os.listdir(projects_dir))
    except OSError:
        return corpus
    for s in slugs:
        mdir = os.path.join(projects_dir, s, "memory")
        if not os.path.isdir(mdir):
            continue
        folder = {"slug": s, "mdir": mdir, "entries": {}, "index": None}
        for f in sorted(os.listdir(mdir)):
            if not f.endswith(".md"):
                continue
            text = _read_text(os.path.join(mdir, f))
            if text is None:
                continue
            if f == "MEMORY.md":
                folder["index"] = text
                continue
            if ORGANIZE_FILENAME_RE.match(f):
                continue
            folder["entries"][f] = {
                "text": text,
                "sha": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "mtime": os.path.getmtime(os.path.join(mdir, f)),
                "bytes": len(text.encode("utf-8")),
            }
        if folder["entries"] or folder["index"] is not None:
            corpus[s] = folder
    return corpus


def discover_projects(roots):
    """slug -> {name, path} for every immediate child dir of every
    configured root — the same auto-discovery premise as measure."""
    found = {}
    for root in sorted(roots):
        expanded = os.path.expanduser(root)
        try:
            children = sorted(os.listdir(expanded))
        except OSError:
            continue
        for c in children:
            p = os.path.join(expanded, c)
            if os.path.isdir(p):
                found[slug(p)] = {"name": c, "path": p, "root": root}
    return found


# -- findings assembly ------------------------------------------------------

def _finding(family, detector, basis, home, entry, fix_class, evidence,
             target=None):
    raw = "|".join([detector, home, entry or "", target or ""])
    return {
        "id": detector + ":" + hashlib.sha256(raw.encode()).hexdigest()[:10],
        "family": family,
        "detector": detector,
        "basis": basis,
        "home": home,
        "entry": entry,
        "target": target,
        "fix_class": fix_class,
        "evidence": evidence,
    }


def _home_name(folder_slug, projects_by_slug):
    hit = projects_by_slug.get(folder_slug)
    return hit["name"] if hit else None


def _root_variants(roots):
    """Every textual form an entry might cite a root in: as configured,
    fully expanded, and home-abbreviated with `~`. Measured live
    (2026-08-05): the corpus cites `~/Projects/X` while configs may hold
    the expanded path — searching only one form missed 3 of 7 known
    contaminated entries."""
    home = os.path.expanduser("~")
    variants = set()
    for r in roots:
        expanded = os.path.expanduser(r)
        variants.add(r)
        variants.add(expanded)
        if expanded.startswith(home):
            variants.add("~" + expanded[len(home):])
    return sorted(variants)


def detect(corpus, projects_by_slug, roots, gap_days):
    findings = []
    root_variants = _root_variants(roots)

    # Cross-folder entry-name universe (1b, 2a, 3c).
    name_locations = {}
    for s, folder in corpus.items():
        for f in folder["entries"]:
            name_locations.setdefault(f, []).append(s)

    for s in sorted(corpus):
        folder = corpus[s]
        home = _home_name(s, projects_by_slug)

        # -- 1c: orphaned memory folder ---------------------------------
        if home is None:
            unmatched = sorted(
                info["name"] for ps, info in projects_by_slug.items()
                if ps not in corpus
            )
            findings.append(_finding(
                "placement", "orphaned_folder", "observation", s, None,
                "record-only",
                {"entry_count": len(folder["entries"]),
                 "note": "project dir gone from every configured root; "
                         "renamed-vs-deleted is a ruling",
                 "rename_candidates_without_memory": unmatched}))

        for f in sorted(folder["entries"]):
            info = folder["entries"][f]
            text = info["text"]

            # -- 1a: foreign-path contamination --------------------------
            # One finding per (entry, cited project), however many times
            # and in whichever textual form the entry cites it.
            cited_projects = {}
            for root in root_variants:
                for m in re.finditer(
                        re.escape(root) + r"/([A-Za-z0-9._-]+)", text):
                    # A sentence-ending dot after the name is prose
                    # punctuation, not part of the directory name.
                    cited = m.group(1).rstrip(".")
                    if not cited or (home is not None and cited == home):
                        continue
                    cited_projects.setdefault(
                        cited, os.path.join(os.path.expanduser(root), cited))
            for cited in sorted(cited_projects):
                cited_path = cited_projects[cited]
                findings.append(_finding(
                    "placement", "foreign_path", "observation", s, f,
                    "move+reindex",
                    {"cited": cited_path,
                     "cited_dir_exists": os.path.isdir(cited_path),
                     "cited_memory_folder_exists": slug(cited_path) in corpus,
                     "home_project": home},
                    target=cited))

            # -- wikilinks: 1b demand vs 3c rot --------------------------
            for m in WIKILINK_RE.finditer(text):
                link = m.group(1).strip()
                fname = link + ".md"
                if fname in folder["entries"]:
                    continue
                elsewhere = sorted(x for x in name_locations.get(fname, [])
                                   if x != s)
                if elsewhere:
                    findings.append(_finding(
                        "placement", "wikilink_demand", "observation", s, f,
                        "record-only",
                        {"link": link,
                         "resolves_in": [
                             _home_name(x, projects_by_slug) or x
                             for x in elsewhere]},
                        target=link))
                else:
                    findings.append(_finding(
                        "hygiene", "dangling_wikilink", "observation", s, f,
                        "remove-link", {"link": link}, target=link))

            # -- 3b: frontmatter lint ------------------------------------
            fm = _frontmatter(text, ("name", "description", "type"))
            problems = []
            if not fm["name"]:
                problems.append("missing name")
            # Ruling B (SAR-09): decision files may have empty descriptions.
            if not fm["description"] and fm["type"] != "sarathi-decision":
                problems.append("missing description")
            if not fm["type"]:
                problems.append("missing type")
            elif fm["type"] not in KNOWN_TYPES:
                problems.append("unknown type '%s'" % fm["type"])
            if problems:
                findings.append(_finding(
                    "hygiene", "frontmatter_lint", "convention", s, f,
                    "fill-frontmatter", {"problems": problems}))

            # -- 3d: provenance integrity --------------------------------
            m = SESSION_ID_RE.search(text)
            if m:
                transcript = os.path.join(
                    os.path.dirname(folder["mdir"]), m.group(1) + ".jsonl")
                if not os.path.exists(transcript):
                    findings.append(_finding(
                        "hygiene", "lost_provenance", "observation", s, f,
                        "record-only", {"originSessionId": m.group(1)}))

            # -- 3f: declared supersession -------------------------------
            m = SUPERSEDE_RE.search(text)
            if m:
                line = m.group(0).strip()
                linked = WIKILINK_RE.search(line)
                findings.append(_finding(
                    "hygiene", "declared_supersession", "convention", s, f,
                    "record-only",
                    {"line": line[:200],
                     "names_other_entry": bool(linked),
                     "linked_target": linked.group(1) if linked else None}))

        # -- 3a: index drift --------------------------------------------
        if folder["entries"] and folder["index"] is None:
            findings.append(_finding(
                "hygiene", "no_index", "observation", s, None,
                "add-index-line",
                {"unindexed": sorted(folder["entries"])}))
        elif folder["index"] is not None:
            linked = set(MDLINK_RE.findall(folder["index"]))
            missing = sorted(f for f in folder["entries"] if f not in linked)
            dangling = sorted(l for l in linked
                              if l != "MEMORY.md"
                              and l not in folder["entries"]
                              and not os.path.exists(
                                  os.path.join(folder["mdir"], l)))
            if missing:
                findings.append(_finding(
                    "hygiene", "unindexed_entries", "observation", s, None,
                    "add-index-line", {"unindexed": missing}))
            if dangling:
                findings.append(_finding(
                    "hygiene", "dangling_index_lines", "observation", s,
                    None, "remove-link", {"dangling": dangling}))

        # -- 3e: hot code / silent memory -------------------------------
        proj = projects_by_slug.get(s)
        if proj and folder["entries"]:
            commit = _git_last_commit_date(proj["path"])
            if commit:
                from datetime import date
                newest = max(e["mtime"] for e in folder["entries"].values())
                mem_date = date.fromtimestamp(newest)
                gap = (date.fromisoformat(commit) - mem_date).days
                if gap > gap_days:
                    findings.append(_finding(
                        "hygiene", "silent_memory", "observation", s, None,
                        "record-only",
                        {"last_commit": commit,
                         "newest_memory_mtime": mem_date.isoformat(),
                         "gap_days": gap, "threshold_days": gap_days}))

    # -- 2a: same-basename cross-folder compare -------------------------
    for fname in sorted(name_locations):
        locs = sorted(name_locations[fname])
        if len(locs) < 2:
            continue
        shas = {corpus[s]["entries"][fname]["sha"] for s in locs}
        findings.append(_finding(
            "duplication", "same_basename", "observation",
            ",".join(locs), fname, "merge-or-pick",
            {"state": "identical" if len(shas) == 1 else "drifted",
             "folders": [_home_name(s, projects_by_slug) or s for s in locs],
             "distinct_hashes": len(shas)}))

    # -- 3g: rent table (arithmetic, not per-entry findings) -------------
    rent = []
    total = 0
    for s in sorted(corpus):
        b = sum(e["bytes"] for e in corpus[s]["entries"].values())
        total += b
        rent.append({"folder": _home_name(s, projects_by_slug) or s,
                     "slug": s,
                     "entries": len(corpus[s]["entries"]),
                     "bytes": b, "approx_tokens": b // 4})
    for row in rent:
        row["share_pct"] = round(100.0 * row["bytes"] / total, 1) if total else 0.0

    findings.sort(key=lambda x: (x["family"], x["detector"], x["home"],
                                 x["entry"] or "", x["target"] or ""))
    return findings, {"folders": rent, "total_bytes": total,
                      "total_approx_tokens": total // 4}


def corpus_hash(corpus):
    h = hashlib.sha256()
    for s in sorted(corpus):
        for f in sorted(corpus[s]["entries"]):
            h.update(("%s/%s:%s\n" % (
                s, f, corpus[s]["entries"][f]["sha"])).encode())
        if corpus[s]["index"] is not None:
            h.update(("%s/MEMORY.md:%s\n" % (
                s, hashlib.sha256(
                    corpus[s]["index"].encode()).hexdigest())).encode())
    return h.hexdigest()


def scan(config_dir, roots, gap_days=DEFAULT_GAP_DAYS, as_of=None):
    corpus = load_corpus(config_dir)
    projects_by_slug = discover_projects(roots)
    findings, rent = detect(corpus, projects_by_slug, roots, gap_days)
    return {
        "meta": {
            "schema": FINDINGS_SCHEMA_VERSION,
            "as_of": as_of,
            "corpus_hash": corpus_hash(corpus),
            "gap_days": gap_days,
            "folder_count": len(corpus),
            "entry_count": sum(len(c["entries"]) for c in corpus.values()),
        },
        "findings": findings,
        "rent": rent,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config-dir", default=None)
    ap.add_argument("--roots", nargs="+", required=True,
                    help="project_roots from config.json, passed explicitly "
                         "so this script never re-implements config "
                         "validation (SKILL.md reads the config and hands "
                         "the values over)")
    ap.add_argument("--gap-days", type=int, default=DEFAULT_GAP_DAYS)
    ap.add_argument("--as-of", default=None)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    config_dir = args.config_dir or resolve_config_dir()
    doc = scan(config_dir, args.roots, args.gap_days, args.as_of)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print("findings: %d  folders: %d  entries: %d  corpus: %s" % (
        len(doc["findings"]), doc["meta"]["folder_count"],
        doc["meta"]["entry_count"], doc["meta"]["corpus_hash"][:12]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
