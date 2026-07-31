#!/usr/bin/env python3
"""sarathi.py — Sarathi stage 1: measure + doctor.

Pure Python 3, stdlib only. No network calls, ever.

Usage:
    python3 sarathi.py [measure] [--as-of YYYY-MM-DD]
    python3 sarathi.py doctor [--json]
    python3 sarathi.py --diagnose [--json]

`measure` is the default command when none is given. It reads
<config-dir>/sarathi/config.json (config-dir = $CLAUDE_CONFIG_DIR or
~/.claude). `config.json`'s `project_roots` are **parent directories**
(e.g. `~/Projects`) — each is auto-scanned for immediate child
directories, and each child is one measured project. There is no
hand-maintained per-project list: a new directory under a configured root
appears in the fact sheet on the next run with no config change. Output is
one JSON fact sheet written to the path named in config.json. See
docs/config-schema.md for the config file format.

`doctor` (alias `--diagnose`) self-diagnoses the tool's own environment —
Python version, git presence, config validity, root readability,
session-folder slug round-trip (against discovered child projects), memory
parseability, output writability — and prints a human-readable table
(default) or JSON (`--json`). It writes nothing; it is read-only.

"""
import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
from datetime import date, datetime, timezone

# --------------------------------------------------------------------------
# Thresholds & other behavior-affecting constants (design rule 6: rules
# ratchet up, model steps back — every machine-specific/behavior-affecting
# constant lives here, once, and nowhere else in this file).
# --------------------------------------------------------------------------
THRESHOLDS = {
    # git repo, >= this many uncommitted files, no commit in >= STALLED_DAYS
    # => "stalled mid-flight"
    "UNCOMMITTED_STALLED_COUNT": 5,
    "STALLED_DAYS": 14,
    # last Claude session > this many days after last commit => "thinking > shipping"
    "THINKING_SHIPPING_DAYS": 7,
    # no files/commits/sessions activity in >= this many days => "dormant"
    "DORMANT_DAYS": 60,
    # no .git and >= this many files => "unversioned build"
    "UNVERSIONED_BUILD_FILE_COUNT": 20,
    # stop walking a project tree after this many files (perf cap)
    "NEWEST_FILE_SCAN_CAP": 4000,
    # memory-text truncation lengths copied verbatim into the fact sheet
    "THREAD_LINE_TRUNCATE_CHARS": 160,
    "DESCRIPTION_TRUNCATE_CHARS": 200,
    # subprocess timeout for each git invocation
    "GIT_TIMEOUT_SECONDS": 20,
    # sentinel "days since" value used when a date is missing/unknown, so
    # missing dates sort as "very long ago" without special-casing every
    # comparison
    "UNREACHABLE_DAYS_SENTINEL": 10 ** 6,
    # minimum supported Python version, checked by `sarathi doctor`
    "MIN_PYTHON_VERSION": (3, 8),
}

# Directory names skipped while walking a project tree for file stats.
SKIP_DIRS = {"node_modules", ".venv", "venv", ".git", "bin", "obj", "dist", "__pycache__"}

# Keyword scan for "open thread" lines in memory files. Imperfect by design
# (keyword match, not semantic) — carried forward from the prototype.
OPEN_RE = re.compile(
    r"deferred|unresolved|not shipped|untested|undecided|blocked|TODO|NOT shipped",
    re.I,
)

# Fact-sheet output schema version (bumped on breaking output-shape changes).
SCHEMA_VERSION = 1
# config.json schema version this script expects (bumped on breaking config
# changes; `sarathi doctor` flags a stale config against this).
CONFIG_SCHEMA_VERSION = 1

REQUIRED_CONFIG_KEYS = {"schema_version", "project_roots", "output_path"}
ALLOWED_CONFIG_KEYS = set(REQUIRED_CONFIG_KEYS)  # no optional keys in schema v1


# --------------------------------------------------------------------------
# Config resolution & validation
# --------------------------------------------------------------------------
class ConfigError(Exception):
    """Raised for any config.json problem: missing file, bad JSON, missing
    required key, or unknown key. Callers turn this into a loud, specific
    failure (never a silent empty result — design rule 2)."""


def resolve_config_dir():
    """$CLAUDE_CONFIG_DIR if set (even to a relative/empty-ish value the
    caller chose), else ~/.claude. Never hardcodes ~/.claude when the env
    var is set (acceptance criterion 5)."""
    override = os.environ.get("CLAUDE_CONFIG_DIR")
    if override:
        return override
    return os.path.join(os.path.expanduser("~"), ".claude")


def config_file_path(config_dir):
    return os.path.join(config_dir, "sarathi", "config.json")


def load_config(config_dir):
    """Load and validate <config_dir>/sarathi/config.json.

    Returns (config_dict, path). Raises ConfigError naming exactly what is
    wrong: missing file, unparseable JSON, unknown key (by name), or
    missing required key (by name) — criteria 6 and 7.
    """
    path = config_file_path(config_dir)
    if not os.path.isfile(path):
        raise ConfigError(
            f"config.json not found at {path} — create it by hand per "
            f"docs/config-schema.md; automated init lands in v0.2"
        )
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, json.JSONDecodeError) as e:
        raise ConfigError(f"config.json at {path} could not be read/parsed: {e}") from e

    if not isinstance(raw, dict):
        raise ConfigError(f"config.json at {path} must contain a JSON object")

    unknown = sorted(set(raw) - ALLOWED_CONFIG_KEYS)
    if unknown:
        raise ConfigError(f"unknown config key: '{unknown[0]}'")

    missing = sorted(REQUIRED_CONFIG_KEYS - set(raw))
    if missing:
        raise ConfigError(f"config.json missing required key: '{missing[0]}'")

    if not isinstance(raw["project_roots"], list) or not all(
        isinstance(x, str) for x in raw["project_roots"]
    ):
        raise ConfigError("config key 'project_roots' must be a list of strings")
    if not isinstance(raw["output_path"], str) or not raw["output_path"]:
        raise ConfigError("config key 'output_path' must be a non-empty string")
    if not isinstance(raw["schema_version"], int):
        raise ConfigError("config key 'schema_version' must be an integer")

    return raw, path


# --------------------------------------------------------------------------
# Small pure helpers
# --------------------------------------------------------------------------
def slug(path):
    """Slugify an absolute path the same way Claude Code names session
    folders under <config-dir>/projects/."""
    return re.sub(r"[^A-Za-z0-9]", "-", path)


def day(ts):
    return date.fromtimestamp(ts).isoformat() if ts else ""


def now_utc_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def days_since(iso_date, as_of):
    """Days between as_of and an ISO date string. Missing dates are treated
    as arbitrarily long ago via the sentinel, so "no data" never masquerades
    as "recent"."""
    if not iso_date:
        return THRESHOLDS["UNREACHABLE_DAYS_SENTINEL"]
    return (as_of - date.fromisoformat(iso_date)).days


def list_dir_filtered(d, suffix):
    """List files under d ending in suffix. Distinguishes "directory
    doesn't exist" (empty, legitimate) from "directory exists but can't be
    read" (failed, a real problem) — design rule 2.

    Returns (matched_filenames, status, reason).
    """
    try:
        names = os.listdir(d)
    except FileNotFoundError:
        return [], "empty", None
    except NotADirectoryError:
        return [], "empty", None
    except OSError as e:
        return [], "failed", f"cannot read directory {d}: {e}"
    matched = sorted(n for n in names if n.endswith(suffix))
    if not matched:
        return [], "empty", None
    return matched, "ok", None


def scan_files(root):
    """Walk root (skipping SKIP_DIRS), capped at NEWEST_FILE_SCAN_CAP files.

    Returns (newest_mtime, count, had_error) — had_error distinguishes a
    permission problem from a legitimately empty tree.

    Traversal order is sorted (directories and files alike): os.walk's
    order is not guaranteed by the OS, so under the scan cap an unsorted
    walk would make *which* files get counted/scanned depend on filesystem
    traversal order — a hidden nondeterminism in the hash (criterion 2,
    rev 3). Sorting makes the cap always truncate at the same files.
    """
    newest = 0
    count = 0
    had_error = False

    def onerr(_exc):
        nonlocal had_error
        had_error = True

    cap = THRESHOLDS["NEWEST_FILE_SCAN_CAP"]
    for dirpath, dirs, files in os.walk(root, onerror=onerr):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for f in sorted(files):
            count += 1
            try:
                m = os.path.getmtime(os.path.join(dirpath, f))
                if m > newest:
                    newest = m
            except OSError:
                had_error = True
            if count >= cap:
                return newest, count, had_error
    return newest, count, had_error


def parse_memory_files(mdir, filenames):
    """Parse memory markdown files into fact-sheet entries. Truncation
    lengths and the open-thread regex come from the single constants block
    (THRESHOLDS / OPEN_RE) — no duplicate literals here."""
    entries = []
    trunc = THRESHOLDS["THREAD_LINE_TRUNCATE_CHARS"]
    desc_trunc = THRESHOLDS["DESCRIPTION_TRUNCATE_CHARS"]
    for fname in sorted(filenames):
        fpath = os.path.join(mdir, fname)
        try:
            with open(fpath, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        fm = {}
        m = re.match(r"^---\n(.*?)\n---", text, re.S)
        if m:
            for line in m.group(1).splitlines():
                kv = re.match(r'\s*(name|description|type|modified):\s*(.+)', line)
                if kv:
                    fm[kv.group(1)] = kv.group(2).strip().strip('"')
        threads = sorted(
            {ln.strip()[:trunc] for ln in text.splitlines()
             if OPEN_RE.search(ln) and not ln.startswith("---")}
        )
        try:
            mtime_date = day(os.path.getmtime(fpath))
        except OSError:
            mtime_date = ""
        entries.append({
            "name": fm.get("name", fname[:-3] if fname.endswith(".md") else fname),
            "desc": fm.get("description", "").replace('\\"', '"')[:desc_trunc],
            "type": fm.get("type", "untyped"),
            "date": (fm.get("modified") or mtime_date)[:10],
            "threads": threads,
        })
    return entries


# --------------------------------------------------------------------------
# git — the sole external tool, invoked defensively (design rule 2,
# acceptance criteria 10 and 14). A missing binary, non-zero exit, or
# timeout is always a reported "failed", never silently folded into "".
# --------------------------------------------------------------------------
def _git_env():
    """Force the C locale for git subprocess calls. We match specific
    English substrings in git's stderr (e.g. "does not have any commits
    yet") to distinguish a legitimate empty repo from a real failure —
    without pinning the locale, that match would silently break (every
    empty repo reported "failed") on any machine with LANG/LC_ALL set to a
    non-English locale."""
    env = dict(os.environ)
    env["LC_ALL"] = "C"
    env["LANG"] = "C"
    return env


def git_log_last_commit(root, git_bin="git", timeout=None):
    """Returns (status, last_commit_or_None, reason). A repo with zero
    commits yet is a legitimate "ok, no commits" result, not a failure —
    distinguished from a genuinely broken invocation by inspecting git's own
    error message."""
    timeout = timeout if timeout is not None else THRESHOLDS["GIT_TIMEOUT_SECONDS"]
    try:
        p = subprocess.run(
            [git_bin, "log", "-1", "--format=%cs"],
            cwd=root, capture_output=True, text=True, timeout=timeout, env=_git_env(),
        )
    except FileNotFoundError:
        return "failed", None, "git not found on PATH"
    except subprocess.TimeoutExpired:
        return "failed", None, f"git timed out after {timeout}s running 'git log'"
    if p.returncode != 0:
        stderr_l = (p.stderr or "").lower()
        if ("does not have any commits yet" in stderr_l
                or "unknown revision" in stderr_l
                or "bad default revision" in stderr_l):
            return "ok", None, None
        return "failed", None, (
            f"git exited {p.returncode} running 'git log': {(p.stderr or '').strip()[:200]}"
        )
    return "ok", (p.stdout.strip() or None), None


def git_dirty_count(root, git_bin="git", timeout=None):
    """Returns (status, count, reason)."""
    timeout = timeout if timeout is not None else THRESHOLDS["GIT_TIMEOUT_SECONDS"]
    try:
        p = subprocess.run(
            [git_bin, "status", "--porcelain"],
            cwd=root, capture_output=True, text=True, timeout=timeout, env=_git_env(),
        )
    except FileNotFoundError:
        return "failed", 0, "git not found on PATH"
    except subprocess.TimeoutExpired:
        return "failed", 0, f"git timed out after {timeout}s running 'git status'"
    if p.returncode != 0:
        return "failed", 0, (
            f"git exited {p.returncode} running 'git status': {(p.stderr or '').strip()[:200]}"
        )
    lines = [ln for ln in p.stdout.splitlines() if ln.strip()]
    return "ok", len(lines), None


def measure_git(root, git_bin="git"):
    git_dir = os.path.join(root, ".git")
    if not os.path.isdir(git_dir):
        return {"status": "empty", "reason": None, "last_commit": None, "dirty": 0}
    if shutil.which(git_bin) is None:
        return {"status": "failed", "reason": "git not found on PATH",
                 "last_commit": None, "dirty": 0}
    status, last_commit, reason = git_log_last_commit(root, git_bin)
    if status == "failed":
        return {"status": "failed", "reason": reason, "last_commit": None, "dirty": 0}
    dstatus, dirty, dreason = git_dirty_count(root, git_bin)
    if dstatus == "failed":
        return {"status": "failed", "reason": dreason, "last_commit": last_commit, "dirty": 0}
    return {"status": "ok", "reason": None, "last_commit": last_commit, "dirty": dirty}


# --------------------------------------------------------------------------
# Per-project subsections
# --------------------------------------------------------------------------
def measure_files(root):
    """had_error with zero files found is a real failure (couldn't look at
    all — rule 2). had_error with some files found is a partial scan: we
    still report what we found (status "ok"), but scan_complete=False plus
    a reason flags that the count may be an undercount, rather than
    silently swallowing the unreadable subtree."""
    newest_ts, count, had_error = scan_files(root)
    if count == 0 and had_error:
        return {"status": "failed", "reason": "permission denied while scanning files",
                 "count": 0, "newest": None, "scan_complete": False}
    if count == 0:
        return {"status": "empty", "reason": None, "count": 0, "newest": None,
                 "scan_complete": True}
    if had_error:
        return {"status": "ok",
                 "reason": "partial scan: some paths were unreadable during the walk",
                 "count": count, "newest": day(newest_ts), "scan_complete": False}
    return {"status": "ok", "reason": None, "count": count, "newest": day(newest_ts),
             "scan_complete": True}


def measure_sessions(config_dir, slug_val):
    sdir = os.path.join(config_dir, "projects", slug_val)
    files, status, reason = list_dir_filtered(sdir, ".jsonl")
    if status == "failed":
        return {"status": "failed", "reason": reason, "count": 0, "last_session": None}
    if status == "empty":
        return {"status": "empty", "reason": None, "count": 0, "last_session": None}
    mtimes = []
    for f in files:
        try:
            mtimes.append(os.path.getmtime(os.path.join(sdir, f)))
        except OSError:
            pass
    last_session = day(max(mtimes)) if mtimes else None
    return {"status": "ok", "reason": None, "count": len(files), "last_session": last_session}


def measure_memory(config_dir, slug_val):
    mdir = os.path.join(config_dir, "projects", slug_val, "memory")
    files, status, reason = list_dir_filtered(mdir, ".md")
    if status == "failed":
        return {"status": "failed", "reason": reason, "entries": []}
    files = [f for f in files if f != "MEMORY.md"]
    if not files:
        return {"status": "empty", "reason": None, "entries": []}
    entries = parse_memory_files(mdir, files)
    return {"status": "ok", "reason": None, "entries": entries}


def compute_flags(git_sub, files_sub, sessions_sub, as_of):
    """Rule-based flags, ported from the prototype but computed against the
    explicit --as-of date rather than datetime.date.today() (acceptance
    criterion 2)."""
    if files_sub["status"] == "empty":
        return ["empty"]

    flags = []
    nfiles = files_sub["count"]
    has_git = git_sub["status"] != "empty"
    last_commit = git_sub.get("last_commit")
    dirty = git_sub.get("dirty") or 0
    last_session = sessions_sub.get("last_session")
    newest = files_sub.get("newest")

    if (has_git and dirty >= THRESHOLDS["UNCOMMITTED_STALLED_COUNT"]
            and days_since(last_commit, as_of) >= THRESHOLDS["STALLED_DAYS"]):
        flags.append("stalled mid-flight")

    if (has_git and last_session and last_commit
            and days_since(last_commit, as_of) - days_since(last_session, as_of)
            > THRESHOLDS["THINKING_SHIPPING_DAYS"]):
        flags.append("thinking > shipping")

    if not has_git and nfiles >= THRESHOLDS["UNVERSIONED_BUILD_FILE_COUNT"]:
        flags.append("unversioned build")

    latest = min(
        days_since(last_commit, as_of),
        days_since(newest, as_of),
        days_since(last_session, as_of),
    )
    if latest >= THRESHOLDS["DORMANT_DAYS"]:
        flags.append("dormant")

    return flags


def measure_project(root, config_dir, as_of, git_bin="git"):
    """One facts.projects entry for a discovered child project directory.
    Whole-entry status is "failed" only when this specific directory can't
    be stat-ed — legal when a child vanishes between discovery and
    measurement (amended criterion 3) — otherwise "ok", with per-source
    status living one level down in git/files/sessions/memory (criterion
    10's finer granularity)."""
    if not os.path.isdir(root):
        return {"status": "failed", "reason": f"project root not found or not a directory: {root}"}

    slug_val = slug(root)
    git_sub = measure_git(root, git_bin)
    files_sub = measure_files(root)
    sessions_sub = measure_sessions(config_dir, slug_val)
    memory_sub = measure_memory(config_dir, slug_val)
    flags = compute_flags(git_sub, files_sub, sessions_sub, as_of)

    return {
        "status": "ok",
        "reason": None,
        "flags": flags,
        "git": git_sub,
        "files": files_sub,
        "sessions": sessions_sub,
        "memory": memory_sub,
    }


# --------------------------------------------------------------------------
# Root auto-discovery (rev 3: project_roots are parent directories; every
# child directory is a project, no hand-maintained per-project list).
# --------------------------------------------------------------------------
def discover_children(root):
    """One configured parent root -> (status, reason, sorted child paths).

    status "failed": the root itself can't be stat-ed/listed (criterion 3).
    status "empty": the root exists but has no child directories.
    status "ok": at least one child directory found.
    """
    if not os.path.isdir(root):
        return "failed", f"project root not found or not a directory: {root}", []
    try:
        names = os.listdir(root)
    except OSError as e:
        return "failed", f"cannot read directory {root}: {e}", []
    children = sorted(
        os.path.join(root, n) for n in names
        if os.path.isdir(os.path.join(root, n))
    )
    if not children:
        return "empty", None, []
    return "ok", None, children


def build_roots_section(project_roots):
    """facts.roots (criterion 3) plus a root -> [child paths] map the rest
    of measure() builds on. project_roots order is preserved so downstream
    project-key assignment stays deterministic given the same config."""
    roots_section = {}
    root_children = {}
    for root in project_roots:
        status, reason, children = discover_children(root)
        roots_section[root] = {"status": status, "reason": reason, "projects": len(children)}
        root_children[root] = children
    return roots_section, root_children


def assign_project_keys(root_children, project_roots):
    """facts.projects keys are child-dir basenames. Two roots each
    containing a child of the same basename would silently collide under a
    bare-basename scheme, so: a basename unique across all discovered
    children keeps its plain form; a colliding basename is qualified with
    its parent root's own basename, e.g. "app (work-projects)"; and in the
    (pathological) case that even the qualified form collides, a numeric
    suffix is appended — deterministically, in configured-root order, never
    a silent last-writer-wins overwrite. Documented in
    docs/config-schema.md.

    Returns an ordered dict: key -> (root, child_path).
    """
    ordered_pairs = [
        (root, child)
        for root in project_roots
        for child in root_children.get(root, [])
    ]
    basenames = [os.path.basename(os.path.normpath(c)) for _, c in ordered_pairs]
    counts = Counter(basenames)

    keys = {}
    used = set()
    for root, child in ordered_pairs:
        base = os.path.basename(os.path.normpath(child))
        if counts[base] == 1:
            key = base
        else:
            qualifier = os.path.basename(os.path.normpath(root)) or slug(root)
            key = f"{base} ({qualifier})"
        final_key = key
        n = 2
        while final_key in used:
            final_key = f"{key} #{n}"
            n += 1
        used.add(final_key)
        keys[final_key] = (root, child)
    return keys


def collect_orphans(config_dir, project_roots, root_children):
    """facts.orphans — memory directories whose slug starts with a
    configured root's slug prefix but whose corresponding child directory
    does not exist on disk (criterion 15, rev 3: reverted to the
    prototype's exists-on-disk semantics — under root auto-discovery every
    existing child is measured, so absence from facts.projects genuinely
    means gone from disk, never merely "not configured")."""
    projects_dir = os.path.join(config_dir, "projects")
    known_slugs = {
        slug(child) for children in root_children.values() for child in children
    }
    root_prefixes = {slug(os.path.normpath(r)) + "-" for r in project_roots}
    entries = []
    for mdir in sorted(glob.glob(os.path.join(projects_dir, "*", "memory"))):
        s = os.path.basename(os.path.dirname(mdir))
        if s in known_slugs:
            continue
        if not any(s.startswith(p) for p in root_prefixes):
            continue
        mem_sub = measure_memory(config_dir, s)
        entries.append({
            "slug": s,
            "status": mem_sub["status"],
            "reason": mem_sub["reason"],
            "memory": mem_sub["entries"],
        })
    return {"status": "ok" if entries else "empty", "entries": entries}


# --------------------------------------------------------------------------
# sarathi measure
# --------------------------------------------------------------------------
def cmd_measure(argv):
    parser = argparse.ArgumentParser(prog="sarathi.py measure")
    parser.add_argument("--as-of", dest="as_of", default=None,
                         help="reference date YYYY-MM-DD (default: today)")
    args = parser.parse_args(argv)

    if args.as_of is None:
        as_of = date.today()
    else:
        try:
            as_of = date.fromisoformat(args.as_of)
        except ValueError:
            print(f"error: invalid --as-of date '{args.as_of}', expected YYYY-MM-DD",
                  file=sys.stderr)
            return 2

    config_dir = resolve_config_dir()
    try:
        cfg, _ = load_config(config_dir)
    except ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    project_roots = cfg["project_roots"]
    roots_section, root_children = build_roots_section(project_roots)
    key_map = assign_project_keys(root_children, project_roots)

    projects = {}
    for key, (root, child) in key_map.items():
        projects[key] = measure_project(child, config_dir, as_of)

    orphans = collect_orphans(config_dir, project_roots, root_children)

    output = {
        "schema_version": SCHEMA_VERSION,
        "run": {"generated_at": now_utc_iso()},
        "facts": {
            "as_of": as_of.isoformat(),
            "roots": roots_section,
            "projects": projects,
            "orphans": orphans,
        },
    }

    out_path = cfg["output_path"]
    out_dir = os.path.dirname(os.path.abspath(out_path))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(output, fh, indent=2, sort_keys=True)
        fh.write("\n")

    n_failed = sum(1 for p in projects.values() if p["status"] == "failed")
    print(f"wrote {out_path}")
    print(f"{len(projects)} projects | failed: {n_failed}")
    return 0


# --------------------------------------------------------------------------
# sarathi doctor
# --------------------------------------------------------------------------
def check_python_version():
    ok = sys.version_info >= THRESHOLDS["MIN_PYTHON_VERSION"]
    detail = f"Python {sys.version.split()[0]}"
    if not ok:
        want = ".".join(str(x) for x in THRESHOLDS["MIN_PYTHON_VERSION"])
        detail += f" — minimum supported is {want}"
    return {"name": "python_version", "status": "ok" if ok else "failed", "detail": detail}


def check_git_present(git_bin="git"):
    path = shutil.which(git_bin)
    if path is None:
        return {
            "name": "git_present", "status": "failed",
            "detail": ("git not found on PATH — install it: "
                       "https://git-scm.com/downloads (macOS: brew install git)"),
        }
    return {"name": "git_present", "status": "ok", "detail": f"git found at {path}"}


def check_config_dir(config_dir):
    if os.path.isdir(config_dir):
        return {"name": "config_dir", "status": "ok",
                "detail": f"resolved config dir: {config_dir}"}
    return {"name": "config_dir", "status": "failed",
            "detail": f"config dir not found: {config_dir} — create it or set CLAUDE_CONFIG_DIR"}


def check_config(config_dir):
    try:
        cfg, path = load_config(config_dir)
    except ConfigError as e:
        return {"name": "config", "status": "failed", "detail": str(e)}
    if cfg["schema_version"] != CONFIG_SCHEMA_VERSION:
        return {
            "name": "config", "status": "failed",
            "detail": (f"config schema_version {cfg['schema_version']} is stale; "
                       f"expected {CONFIG_SCHEMA_VERSION} — update config.json per "
                       f"docs/config-schema.md"),
        }
    return {"name": "config", "status": "ok", "detail": f"config valid at {path}"}


def check_project_roots(config_dir):
    try:
        cfg, _ = load_config(config_dir)
    except ConfigError:
        return {"name": "project_roots_readable", "status": "empty",
                "detail": "config unavailable — cannot enumerate project roots"}
    roots = cfg["project_roots"]
    if not roots:
        return {"name": "project_roots_readable", "status": "empty",
                "detail": "no project_roots configured"}
    unreadable = [r for r in roots if not (os.path.isdir(r) and os.access(r, os.R_OK))]
    if unreadable:
        return {"name": "project_roots_readable", "status": "failed",
                "detail": f"{len(unreadable)}/{len(roots)} roots unreadable: {', '.join(unreadable)}"}
    return {"name": "project_roots_readable", "status": "ok",
            "detail": f"{len(roots)}/{len(roots)} roots readable"}


def _discover_all_children(project_roots):
    """Flat list of every auto-discovered child project directory across
    all configured (readable) roots, in deterministic root-then-basename
    order. Used by the doctor checks below, which reason about discovered
    projects rather than the configured parent roots directly (rev 3)."""
    children = []
    for root in project_roots:
        _status, _reason, root_children = discover_children(root)
        children.extend(root_children)
    return children


def check_session_slug_roundtrip(config_dir):
    try:
        cfg, _ = load_config(config_dir)
    except ConfigError:
        return {"name": "session_slug_roundtrip", "status": "empty",
                "detail": "config unavailable — cannot check session folders"}
    projects_dir = os.path.join(config_dir, "projects")
    try:
        os.listdir(projects_dir)  # readability probe, criterion 13's "failed" branch
    except FileNotFoundError:
        return {"name": "session_slug_roundtrip", "status": "empty",
                "detail": f"no session folders found under {projects_dir}"}
    except OSError as e:
        return {"name": "session_slug_roundtrip", "status": "failed",
                "detail": f"cannot read {projects_dir}: {e}"}
    # A bare slug directory can exist solely because Claude Code wrote a
    # *memory* subfolder there (<slug>/memory/) even with zero session
    # files. "Matching session folder" means actual session (*.jsonl)
    # files, so this reuses measure_sessions()'s own ok/empty distinction
    # rather than a directory-existence check.
    children = _discover_all_children(cfg["project_roots"])
    for child in children:
        sessions_sub = measure_sessions(config_dir, slug(child))
        if sessions_sub["status"] == "ok":
            return {"name": "session_slug_roundtrip", "status": "ok",
                    "detail": f"matched session folder for '{os.path.basename(child)}'"}
    return {"name": "session_slug_roundtrip", "status": "empty",
            "detail": "no session folders exist for any discovered project"}


def check_memory_parseable(config_dir):
    try:
        cfg, _ = load_config(config_dir)
    except ConfigError:
        return {"name": "memory_parseable", "status": "empty",
                "detail": "config unavailable — cannot check memory files"}
    children = _discover_all_children(cfg["project_roots"])
    total = 0
    errors = []
    for child in children:
        sub = measure_memory(config_dir, slug(child))
        if sub["status"] == "failed":
            errors.append(f"{os.path.basename(child)}: {sub['reason']}")
        else:
            total += len(sub["entries"])
    if errors:
        return {"name": "memory_parseable", "status": "failed", "detail": "; ".join(errors)}
    if total == 0:
        return {"name": "memory_parseable", "status": "empty", "detail": "no memory files found"}
    return {"name": "memory_parseable", "status": "ok", "detail": f"{total} memory entries parsed"}


def check_output_writable(config_dir):
    try:
        cfg, _ = load_config(config_dir)
    except ConfigError:
        return {"name": "output_writable", "status": "empty",
                "detail": "config unavailable — cannot check output path"}
    out_path = os.path.abspath(cfg["output_path"])
    probe = os.path.dirname(out_path) or "."
    while not os.path.exists(probe):
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    if os.access(probe, os.W_OK):
        return {"name": "output_writable", "status": "ok", "detail": f"{out_path} is writable"}
    return {"name": "output_writable", "status": "failed", "detail": f"{out_path} is not writable"}


DOCTOR_CHECKS = [
    lambda config_dir: check_python_version(),
    lambda config_dir: check_git_present(),
    check_config_dir,
    check_config,
    check_project_roots,
    check_session_slug_roundtrip,
    check_memory_parseable,
    check_output_writable,
]


def safe_check(fn, config_dir):
    try:
        return fn(config_dir)
    except Exception as e:  # doctor must never crash on a single bad check
        name = getattr(fn, "__name__", "check").replace("check_", "", 1)
        return {"name": name, "status": "failed", "detail": f"unexpected error: {e}"}


def print_doctor_table(checks, config_dir):
    print(f"sarathi doctor — config dir: {config_dir}")
    name_w = max((len(c["name"]) for c in checks), default=4)
    status_w = max((len(c["status"]) for c in checks), default=6)
    for c in checks:
        print(f"  {c['name']:<{name_w}}  {c['status']:<{status_w}}  {c['detail']}")


def cmd_doctor(argv):
    parser = argparse.ArgumentParser(prog="sarathi.py doctor")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    config_dir = resolve_config_dir()
    checks = [safe_check(fn, config_dir) for fn in DOCTOR_CHECKS]
    overall_ok = all(c["status"] != "failed" for c in checks)

    if args.json:
        print(json.dumps({"checks": checks}, indent=2, sort_keys=True))
    else:
        print_doctor_table(checks, config_dir)

    return 0 if overall_ok else 1


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------
def main(argv):
    """Dispatch to measure (default) or doctor.

    Deliberately NOT a single argparse parser with a positional
    subcommand: with `command` as an optional positional, argparse still
    tries to consume the first argv token as `command` even when it looks
    like a flag value belonging to a later option (e.g. `--as-of` followed
    by a date) once combined with parse_known_args — `sarathi.py --as-of
    2026-01-01` (the documented default-command form) failed with "invalid
    choice: '2026-01-01'" (bug found in review). Instead: peek at argv[0]
    directly. Only "measure"/"doctor" are ever treated as a subcommand
    name; anything else (including no args at all, or a flag like
    `--as-of`) falls through to measure with the full argv untouched.
    `--diagnose` is recognized anywhere in argv as a doctor alias.
    """
    argv = list(argv)
    if "--diagnose" in argv:
        argv = [a for a in argv if a != "--diagnose"]
        return cmd_doctor(argv)
    if argv and argv[0] == "doctor":
        return cmd_doctor(argv[1:])
    if argv and argv[0] == "measure":
        return cmd_measure(argv[1:])
    return cmd_measure(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
