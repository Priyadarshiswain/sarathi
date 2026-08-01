#!/usr/bin/env python3
"""check_update.py -- deterministic tag-parsing and semver comparison for
Sarathi's update check (story SAR-07 §6). Pure Python 3, stdlib only. No
network calls of its own, ever: it never imports urllib/http.client/socket/
requests/ftplib/smtplib/xmlrpc, never shells out to git or anything else,
and never reads an environment variable naming a URL. Its only two inputs
are the file contents at `--plugin-json <path>` and the raw text of
`git ls-remote --tags <repo>` on stdin -- both handed to it by
skills/doctor/SKILL.md's new §5 step, never fetched by this script itself.

This is the reason the script exists at all (design rule 3, SAR-07 §2):
tag-line parsing (including peeled `^{}` duplicates) and semver comparison
are exactly the kind of fixed, restatable logic the LLM must never freehand
per run -- so, like SAR-05's build_ledger_payload.py, it becomes a small,
tested script under a skill's own directory, invoked by that skill's
SKILL.md exactly the way it already invokes sarathi.py.

Two pure functions do the real work:

    parse_tags(ls_remote_text)  -> sorted list of unique candidate version
                                    strings ("MAJOR.MINOR.PATCH", no "v")
    latest_semver_tag(versions) -> highest version string by numeric tuple
                                    comparison, or None if the list is empty
    build_result(installed, ls_remote_text) -> the pinned result dict

plus a CLI wrapping build_result(), reading the installed version from
`--plugin-json` and the ls-remote text from stdin (SAR-07 §6, stdin-only,
pinned).
"""
import argparse
import json
import re
import sys

# Strict release-tag shape (SAR-07 §6, pinned): an optional single leading
# "v", exactly three dot-separated non-negative integers, nothing else.
# Deliberately excludes prerelease/build-metadata suffixes and anything
# with a different number of components -- entirely, not merely
# deprioritized (a definitional choice, not an inevitability; see the
# story's own judgment-call note).
TAG_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


def _version_tuple(version):
    """Parse a strict "MAJOR.MINOR.PATCH" (optionally "vMAJOR.MINOR.PATCH")
    string into a (major, minor, patch) int tuple, or None if it doesn't
    match the strict shape at all."""
    m = TAG_RE.match(version)
    if not m:
        return None
    return tuple(int(g) for g in m.groups())


def parse_tags(ls_remote_text):
    """Parse `git ls-remote --tags <repo>` output into a sorted, deduped
    list of candidate release-version strings (bare "MAJOR.MINOR.PATCH",
    no leading "v", matching plugin.json's own convention).

    Each line is "<sha>\\trefs/tags/<name>"; annotated tags additionally
    emit a second "<sha>\\trefs/tags/<name>^{}" line (the peeled commit the
    tag object points at) -- a trailing "^{}" is stripped from the ref name
    before matching so both lines for the same annotated tag collapse to
    one candidate, never two (SAR-07 §6/criterion 1). Non-tag refs, refs
    that don't match the strict shape, and duplicate candidates are all
    silently excluded here -- this function's only job is "what candidates
    exist," never "which one is latest" (that's latest_semver_tag()).
    """
    candidates = set()
    for line in ls_remote_text.splitlines():
        line = line.strip()
        if not line or "\t" not in line:
            continue
        _sha, ref = line.split("\t", 1)
        prefix = "refs/tags/"
        if not ref.startswith(prefix):
            continue
        name = ref[len(prefix):]
        if name.endswith("^{}"):
            name = name[: -len("^{}")]
        parsed = _version_tuple(name)
        if parsed is None:
            continue
        candidates.add("{0}.{1}.{2}".format(*parsed))
    return sorted(candidates)


def latest_semver_tag(versions):
    """Highest version string among `versions` by numeric (major, minor,
    patch) tuple comparison -- never lexicographic (SAR-07 §6/criterion 3:
    "0.10.0" must beat "0.7.0", which a string comparison would get wrong).
    Independent of input order, independent of wall-clock time (rule 1).
    Returns None if `versions` is empty."""
    if not versions:
        return None
    return max(versions, key=_version_tuple)


def build_result(installed, ls_remote_text):
    """The one pure function build_result(installed, ls_remote_text) ->
    result dict, pinned exactly by SAR-07 §6:

        {"installed": installed, "latest": <str>|None,
         "update_available": <bool>}

    Deterministic given its two inputs (rule 1): same `installed` string +
    same `ls_remote_text` -> byte-identical result, every time.

    `update_available` is True exactly when `latest` is not None and is
    numerically greater than `installed` -- tuple comparison, never string
    comparison. False when `latest` is None, when `latest == installed`,
    and when `installed` is ahead of every candidate found (a dev
    checkout) -- no third state (SAR-07 §6, criteria 4-6).

    Raises ValueError if `installed` itself does not match the strict
    release-tag shape -- a script-level failure the CLI turns into a loud,
    non-zero exit (SAR-07 §6, "malformed installed version").
    """
    installed_tuple = _version_tuple(installed)
    if installed_tuple is None:
        raise ValueError(
            "installed version {0!r} does not match the strict "
            "MAJOR.MINOR.PATCH shape".format(installed)
        )

    versions = parse_tags(ls_remote_text)
    latest = latest_semver_tag(versions)

    update_available = False
    if latest is not None:
        latest_tuple = _version_tuple(latest)
        update_available = latest_tuple > installed_tuple

    return {
        "installed": installed,
        "latest": latest,
        "update_available": update_available,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(prog="check_update.py")
    parser.add_argument(
        "--plugin-json", required=True,
        help="path to plugin.json; its \"version\" field is the installed version"
             " (never a hardcoded relative path -- the skill points this at"
             " ${CLAUDE_PLUGIN_ROOT}/.claude-plugin/plugin.json)",
    )
    args = parser.parse_args(argv)

    ls_remote_text = sys.stdin.read()
    if not ls_remote_text.strip():
        # Rule 2 -- fail loudly: genuinely empty/whitespace-only stdin is a
        # misuse of this script (the doctor skill's own network step is
        # supposed to short-circuit before ever calling this script on a
        # failed/empty `git ls-remote`), never a legitimate "no tags"
        # result. Exit 1, stderr only, no JSON on stdout at all.
        print("check_update.py: empty stdin -- expected `git ls-remote --tags` "
              "output, got nothing", file=sys.stderr)
        return 1

    try:
        with open(args.plugin_json, "r", encoding="utf-8") as fh:
            plugin_data = json.load(fh)
    except (OSError, json.JSONDecodeError) as e:
        print("check_update.py: couldn't read --plugin-json {0!r}: {1}".format(
            args.plugin_json, e), file=sys.stderr)
        return 1

    installed = plugin_data.get("version")
    if not isinstance(installed, str):
        print("check_update.py: --plugin-json {0!r} has no string \"version\" "
              "field".format(args.plugin_json), file=sys.stderr)
        return 1

    try:
        result = build_result(installed, ls_remote_text)
    except ValueError as e:
        print("check_update.py: {0}".format(e), file=sys.stderr)
        return 1

    sys.stdout.write(json.dumps(result, sort_keys=True))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
