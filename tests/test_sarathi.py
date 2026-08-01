"""unittest suite for sarathi.py (story SAR-01, rev 3, section 8).

Every test builds its own tempfile.TemporaryDirectory() fixtures and points
CLAUDE_CONFIG_DIR (or calls internal functions directly) at those temp
paths. Nothing here ever reads or writes the real ~/.claude or ~/Projects.

rev 3: `project_roots` in config.json are PARENT directories, auto-scanned
for immediate child directories -- each child is one measured project.
`self.projects_root` (set up by TempDirCase) plays that parent-root role;
`build_project()` adds one auto-discovered child under it per call.

Run: python3 -m unittest discover -s tests -v
"""
import hashlib
import inspect
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import sarathi  # noqa: E402
from fixtures import (  # noqa: E402
    REPO_ROOT,
    SARATHI_PATH,
    git_commit_all,
    init_git_repo,
    make_decision_file,
    make_memory_file,
    make_session_file,
    run_sarathi,
    write_config,
    write_file,
)

# SAR-04: skills/report/render_report.py is a standalone script, not part of
# sarathi.py -- imported directly the same way sarathi.py itself is, via an
# explicit sys.path insert of its own directory (never copied or reimported
# through sarathi.py, which has zero diff in this story).
REPORT_SKILL_DIR = os.path.join(REPO_ROOT, "skills", "report")
if REPORT_SKILL_DIR not in sys.path:
    sys.path.insert(0, REPORT_SKILL_DIR)
import render_report  # noqa: E402


class TempDirCase(unittest.TestCase):
    """Base class: gives each test an isolated temp dir, never the real
    ~/.claude or ~/Projects. self.projects_root is a PARENT directory
    (config's project_roots entry); build_project() adds one
    auto-discovered child under it."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name
        self.config_dir = os.path.join(self.tmp, "claude-config")
        self.projects_root = os.path.join(self.tmp, "Projects")
        os.makedirs(self.config_dir, exist_ok=True)
        os.makedirs(self.projects_root, exist_ok=True)

    def tearDown(self):
        self._tmp.cleanup()

    # -- shared fixture builder -------------------------------------------------
    def build_project(self, name="alpha", n_files=3, commit_date=None,
                       n_uncommitted=0, with_git=True, add_session=True,
                       add_memory=True, parent=None):
        """Create one child directory (a discoverable project) under
        `parent` (defaults to self.projects_root)."""
        parent = parent or self.projects_root
        root = os.path.join(parent, name)
        os.makedirs(root, exist_ok=True)
        for i in range(n_files):
            write_file(os.path.join(root, f"file{i}.txt"), f"content {i}\n")
        if with_git:
            init_git_repo(root)
            git_commit_all(root, "initial", commit_date or date.today().isoformat())
            for i in range(n_uncommitted):
                write_file(os.path.join(root, f"dirty{i}.txt"), "uncommitted\n")
        if add_session:
            make_session_file(self.config_dir, root)
        if add_memory:
            make_memory_file(
                self.config_dir, root, "note.md",
                {"name": "a note", "description": "just a note", "type": "project"},
                body="Nothing deferred here.",
            )
        return root


class TestDeterminism(TempDirCase):
    def test_determinism_hash(self):
        self.build_project(commit_date=(date.today() - timedelta(days=5)).isoformat())
        out_path = os.path.join(self.tmp, "facts.json")
        write_config(self.config_dir, [self.projects_root], out_path)
        as_of = date.today().isoformat()

        r1 = run_sarathi(["measure", "--as-of", as_of], config_dir=self.config_dir)
        self.assertEqual(r1.returncode, 0, r1.stderr)
        with open(out_path) as fh:
            facts1 = json.load(fh)["facts"]

        r2 = run_sarathi(["measure", "--as-of", as_of], config_dir=self.config_dir)
        self.assertEqual(r2.returncode, 0, r2.stderr)
        with open(out_path) as fh:
            facts2 = json.load(fh)["facts"]

        h1 = hashlib.sha256(json.dumps(facts1, sort_keys=True).encode()).hexdigest()
        h2 = hashlib.sha256(json.dumps(facts2, sort_keys=True).encode()).hexdigest()
        self.assertEqual(h1, h2)
        self.assertEqual(facts1["as_of"], as_of)


class TestAsOfChangesFlags(TempDirCase):
    def test_as_of_changes_flags(self):
        commit_date = date.today() - timedelta(days=30)
        self.build_project(
            name="stalled-proj", commit_date=commit_date.isoformat(), n_uncommitted=5,
        )
        out_path = os.path.join(self.tmp, "facts.json")
        write_config(self.config_dir, [self.projects_root], out_path)

        # 13 days after last commit: below the 14-day STALLED_DAYS window.
        as_of_low = (commit_date + timedelta(days=13)).isoformat()
        # 15 days after last commit: straddles past the window.
        as_of_high = (commit_date + timedelta(days=15)).isoformat()

        r1 = run_sarathi(["measure", "--as-of", as_of_low], config_dir=self.config_dir)
        self.assertEqual(r1.returncode, 0, r1.stderr)
        with open(out_path) as fh:
            flags_low = json.load(fh)["facts"]["projects"]["stalled-proj"]["flags"]

        r2 = run_sarathi(["measure", "--as-of", as_of_high], config_dir=self.config_dir)
        self.assertEqual(r2.returncode, 0, r2.stderr)
        with open(out_path) as fh:
            flags_high = json.load(fh)["facts"]["projects"]["stalled-proj"]["flags"]

        self.assertNotIn("stalled mid-flight", flags_low)
        self.assertIn("stalled mid-flight", flags_high)
        self.assertNotEqual(flags_low, flags_high)

    def test_as_of_defaults_to_today(self):
        # omitting --as-of should not error, and should record today's date
        self.build_project(name="today-proj")
        out_path = os.path.join(self.tmp, "facts.json")
        write_config(self.config_dir, [self.projects_root], out_path)
        r = run_sarathi(["measure"], config_dir=self.config_dir)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(out_path) as fh:
            facts = json.load(fh)["facts"]
        self.assertEqual(facts["as_of"], date.today().isoformat())


class TestRootMissingShape(TempDirCase):
    def test_root_missing_shape(self):
        """Amended criterion 3: a configured PARENT root that has been
        deleted/renamed is reported under facts.roots (not facts.projects,
        since there is no child to report on)."""
        missing_root = os.path.join(self.tmp, "does-not-exist-parent")
        out_path = os.path.join(self.tmp, "facts.json")
        write_config(self.config_dir, [missing_root], out_path)

        r = run_sarathi(["measure"], config_dir=self.config_dir)
        self.assertEqual(r.returncode, 0, r.stderr)

        with open(out_path) as fh:
            output = json.load(fh)  # must be valid, complete JSON
        root_entry = output["facts"]["roots"][missing_root]
        self.assertEqual(root_entry["status"], "failed")
        self.assertTrue(root_entry.get("reason"))
        self.assertEqual(root_entry["projects"], 0)
        self.assertEqual(output["facts"]["projects"], {})

    def test_root_empty_shape(self):
        """A root that exists but has no child directories is 'empty', not
        'failed' or silently absent."""
        out_path = os.path.join(self.tmp, "facts.json")
        write_config(self.config_dir, [self.projects_root], out_path)  # no children yet

        r = run_sarathi(["measure"], config_dir=self.config_dir)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(out_path) as fh:
            output = json.load(fh)
        root_entry = output["facts"]["roots"][self.projects_root]
        self.assertEqual(root_entry["status"], "empty")
        self.assertEqual(root_entry["projects"], 0)


class TestFailedEntryShape(TempDirCase):
    def test_failed_entry_shape(self):
        """Amended criterion 3's tail clause: the whole-entry 'failed'
        shape on a *project* entry remains legal for a child directory
        that vanishes between discovery and measurement. Reproducing that
        race deterministically at the CLI level isn't practical, so this
        exercises measure_project() directly against a child path that
        doesn't exist -- the same code path a real vanishing-child race
        would hit."""
        missing_child = os.path.join(self.projects_root, "vanished-child")
        entry = sarathi.measure_project(missing_child, self.config_dir, date.today())
        self.assertEqual(entry["status"], "failed")
        self.assertTrue(entry.get("reason"))
        # Must embed cleanly into the full fact sheet as valid JSON.
        json.dumps({"facts": {"projects": {"vanished-child": entry}}}, sort_keys=True)


class TestDiscoversNewProject(TempDirCase):
    def test_discovers_new_project(self):
        """Criterion 1: a new directory under a configured root appears on
        the next run with no config change."""
        out_path = os.path.join(self.tmp, "facts.json")
        write_config(self.config_dir, [self.projects_root], out_path)

        r1 = run_sarathi(["measure"], config_dir=self.config_dir)
        self.assertEqual(r1.returncode, 0, r1.stderr)
        with open(out_path) as fh:
            facts1 = json.load(fh)["facts"]
        self.assertNotIn("newcomer", facts1["projects"])

        newcomer = os.path.join(self.projects_root, "newcomer")
        os.makedirs(newcomer, exist_ok=True)
        write_file(os.path.join(newcomer, "f.txt"))

        r2 = run_sarathi(["measure"], config_dir=self.config_dir)
        self.assertEqual(r2.returncode, 0, r2.stderr)
        with open(out_path) as fh:
            facts2 = json.load(fh)["facts"]
        self.assertIn("newcomer", facts2["projects"])
        self.assertEqual(facts2["projects"]["newcomer"]["status"], "ok")


class TestProjectKeyDisambiguation(TempDirCase):
    def test_same_basename_children_get_deterministic_distinct_keys(self):
        """MAJOR-1: two configured roots each containing a child of the
        same basename must never silently overwrite one another in
        facts.projects."""
        root_a = os.path.join(self.tmp, "team-a")
        root_b = os.path.join(self.tmp, "team-b")
        os.makedirs(root_a, exist_ok=True)
        os.makedirs(root_b, exist_ok=True)
        self.build_project(name="app", parent=root_a)
        self.build_project(name="app", parent=root_b)
        # An unambiguous sibling should keep its plain basename key.
        self.build_project(name="unique-proj", parent=root_a)

        out_path = os.path.join(self.tmp, "facts.json")
        write_config(self.config_dir, [root_a, root_b], out_path)

        r = run_sarathi(["measure"], config_dir=self.config_dir)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(out_path) as fh:
            projects = json.load(fh)["facts"]["projects"]

        self.assertIn("unique-proj", projects)
        self.assertNotIn("app", projects)  # bare "app" would be ambiguous
        qualified = [k for k in projects if k.startswith("app ")]
        self.assertEqual(len(qualified), 2)
        self.assertEqual(len(set(qualified)), 2)  # both keys distinct
        self.assertEqual(len(projects), 3)  # nothing silently overwritten

        # Re-running against the same, unchanged trees must assign the same
        # keys again (rule 1: deterministic given the config).
        r2 = run_sarathi(["measure"], config_dir=self.config_dir)
        self.assertEqual(r2.returncode, 0, r2.stderr)
        with open(out_path) as fh:
            projects2 = json.load(fh)["facts"]["projects"]
        self.assertEqual(set(projects.keys()), set(projects2.keys()))


class TestPartialFailureSubsectionShape(TempDirCase):
    def test_partial_failure_subsection_shape(self):
        self.build_project(name="git-missing-proj")
        out_path = os.path.join(self.tmp, "facts.json")
        write_config(self.config_dir, [self.projects_root], out_path)

        empty_path_dir = tempfile.mkdtemp()
        try:
            r = run_sarathi(
                ["measure"], config_dir=self.config_dir, path_override=empty_path_dir,
            )
        finally:
            os.rmdir(empty_path_dir)
        self.assertEqual(r.returncode, 0, r.stderr)

        with open(out_path) as fh:
            entry = json.load(fh)["facts"]["projects"]["git-missing-proj"]

        self.assertEqual(entry["status"], "ok")
        self.assertEqual(entry["git"]["status"], "failed")
        self.assertEqual(entry["git"]["reason"], "git not found on PATH")
        self.assertEqual(entry["files"]["status"], "ok")
        self.assertEqual(entry["sessions"]["status"], "ok")
        self.assertEqual(entry["memory"]["status"], "ok")


class TestOrphans(TempDirCase):
    def test_orphans_present_and_empty(self):
        # 'alpha' is a real, currently-discovered child of the configured
        # parent root.
        alpha = os.path.join(self.projects_root, "alpha")
        os.makedirs(alpha, exist_ok=True)
        write_file(os.path.join(alpha, "f.txt"))
        out_path = os.path.join(self.tmp, "facts.json")
        write_config(self.config_dir, [self.projects_root], out_path)

        # No orphan directories yet.
        r_empty = run_sarathi(["measure"], config_dir=self.config_dir)
        self.assertEqual(r_empty.returncode, 0, r_empty.stderr)
        with open(out_path) as fh:
            orphans_empty = json.load(fh)["facts"]["orphans"]
        self.assertEqual(orphans_empty["status"], "empty")
        self.assertEqual(orphans_empty["entries"], [])

        # Now add a memory dir for a sibling that does NOT exist on disk
        # under the same parent root (rev 3: orphan semantics are
        # exists-on-disk, reverted to the prototype's rule -- every child
        # that *does* exist is auto-discovered and measured, so absence
        # from facts.projects genuinely means gone from disk).
        deleted_child = os.path.join(self.projects_root, "beta-deleted")
        deleted_slug = sarathi.slug(deleted_child)
        make_memory_file(
            self.config_dir, deleted_slug, "old.md",
            {"name": "old note", "description": "from a deleted project", "type": "project"},
            is_slug=True,
        )

        r_present = run_sarathi(["measure"], config_dir=self.config_dir)
        self.assertEqual(r_present.returncode, 0, r_present.stderr)
        with open(out_path) as fh:
            orphans_present = json.load(fh)["facts"]["orphans"]
        self.assertEqual(orphans_present["status"], "ok")
        slugs = [e["slug"] for e in orphans_present["entries"]]
        self.assertIn(deleted_slug, slugs)
        matched = next(e for e in orphans_present["entries"] if e["slug"] == deleted_slug)
        self.assertEqual(matched["status"], "ok")
        self.assertEqual(len(matched["memory"]), 1)


class TestEmptySectionShape(TempDirCase):
    def test_empty_section_shape(self):
        root = os.path.join(self.projects_root, "empty-proj")
        os.makedirs(root, exist_ok=True)  # exists, but zero files
        out_path = os.path.join(self.tmp, "facts.json")
        write_config(self.config_dir, [self.projects_root], out_path)

        r = run_sarathi(["measure"], config_dir=self.config_dir)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(out_path) as fh:
            entry = json.load(fh)["facts"]["projects"]["empty-proj"]

        # Whole-entry status is "ok" (the directory itself is reachable and
        # was measured) -- amended criterion 4, rev 3 reviewer ruling:
        # "empty" is a per-source verdict (files subsection) plus a
        # derived flag, not a whole-entry status.
        self.assertEqual(entry["status"], "ok")
        self.assertEqual(entry["files"]["status"], "empty")
        self.assertNotEqual(entry["files"]["status"], "failed")
        self.assertIn("empty", entry["flags"])


class TestConfigValidation(TempDirCase):
    def test_config_rejects_unknown_key(self):
        write_config(self.config_dir, [], os.path.join(self.tmp, "facts.json"),
                      extra_keys={"foo": "bar"})
        with self.assertRaises(sarathi.ConfigError) as ctx:
            sarathi.load_config(self.config_dir)
        self.assertIn("unknown config key: 'foo'", str(ctx.exception))

    def test_config_rejects_missing_key(self):
        out_path = os.path.join(self.tmp, "facts.json")
        write_config(self.config_dir, [], out_path, omit_keys=["project_roots"])

        r = run_sarathi(["measure"], config_dir=self.config_dir)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("project_roots", r.stderr)
        self.assertFalse(os.path.exists(out_path))


class TestClaudeConfigDirEnv(unittest.TestCase):
    def test_claude_config_dir_env(self):
        original = os.environ.pop("CLAUDE_CONFIG_DIR", None)
        try:
            with tempfile.TemporaryDirectory() as tmp_fixture:
                os.environ["CLAUDE_CONFIG_DIR"] = tmp_fixture
                self.assertEqual(sarathi.resolve_config_dir(), tmp_fixture)
        finally:
            if original is None:
                os.environ.pop("CLAUDE_CONFIG_DIR", None)
            else:
                os.environ["CLAUDE_CONFIG_DIR"] = original

        # Unset -> reverts to ~/.claude, no leftover state from the fixture.
        self.assertNotIn("CLAUDE_CONFIG_DIR", os.environ)
        expected_default = os.path.join(os.path.expanduser("~"), ".claude")
        self.assertEqual(sarathi.resolve_config_dir(), expected_default)


class TestDoctor(TempDirCase):
    def _healthy_config(self):
        self.build_project(name="healthy-proj")
        out_path = os.path.join(self.tmp, "facts.json")
        write_config(self.config_dir, [self.projects_root], out_path)
        return out_path

    def test_doctor_json_shape(self):
        self._healthy_config()
        r = run_sarathi(["doctor", "--json"], config_dir=self.config_dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        payload = json.loads(r.stdout)
        self.assertIn("checks", payload)
        self.assertTrue(payload["checks"])
        for check in payload["checks"]:
            self.assertIn("name", check)
            self.assertIn("status", check)
            self.assertIn("detail", check)
            self.assertIn(check["status"], ("ok", "failed", "empty"))

    def test_doctor_git_missing(self):
        self._healthy_config()
        empty_path_dir = tempfile.mkdtemp()
        try:
            r = run_sarathi(
                ["doctor", "--json"], config_dir=self.config_dir,
                path_override=empty_path_dir,
            )
        finally:
            os.rmdir(empty_path_dir)
        payload = json.loads(r.stdout)
        git_check = next(c for c in payload["checks"] if c["name"] == "git_present")
        self.assertEqual(git_check["status"], "failed")
        self.assertEqual(
            git_check["detail"],
            "git not found on PATH — install it: https://git-scm.com/downloads "
            "(macOS: brew install git)",
        )

    def test_doctor_config_absent(self):
        # config_dir exists but has no sarathi/config.json at all.
        r = run_sarathi(["doctor", "--json"], config_dir=self.config_dir)
        payload = json.loads(r.stdout)
        by_name = {c["name"]: c for c in payload["checks"]}

        self.assertEqual(by_name["config"]["status"], "failed")
        self.assertIn("config.json not found at", by_name["config"]["detail"])
        self.assertIn("docs/config-schema.md", by_name["config"]["detail"])

        # Independent checks still run and report their own status.
        self.assertEqual(by_name["python_version"]["status"], "ok")
        self.assertEqual(by_name["git_present"]["status"], "ok")

    def test_doctor_healthy_exits_zero_table_mode(self):
        # Sanity check on the human-readable (default) table path too.
        self._healthy_config()
        r = run_sarathi(["doctor"], config_dir=self.config_dir)
        self.assertIn("sarathi doctor", r.stdout)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_diagnose_alias(self):
        self._healthy_config()
        r = run_sarathi(["--diagnose", "--json"], config_dir=self.config_dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        payload = json.loads(r.stdout)
        self.assertIn("checks", payload)

    def test_doctor_exit_nonzero_on_failure(self):
        """Inverse of criterion 9: any failed check -> non-zero exit, so
        doctor is usable as a gate."""
        self._healthy_config()
        empty_path_dir = tempfile.mkdtemp()
        try:
            r = run_sarathi(["doctor"], config_dir=self.config_dir, path_override=empty_path_dir)
        finally:
            os.rmdir(empty_path_dir)
        self.assertNotEqual(r.returncode, 0)


class TestSessionSlugRoundtrip(TempDirCase):
    def test_session_slug_roundtrip_empty(self):
        """No session folders exist for any discovered project -> 'empty',
        not a failure (criterion 13)."""
        self.build_project(name="proj-no-sessions", add_session=False)
        out_path = os.path.join(self.tmp, "facts.json")
        write_config(self.config_dir, [self.projects_root], out_path)

        r = run_sarathi(["doctor", "--json"], config_dir=self.config_dir)
        payload = json.loads(r.stdout)
        check = next(c for c in payload["checks"] if c["name"] == "session_slug_roundtrip")
        self.assertEqual(check["status"], "empty")

    @unittest.skipUnless(
        os.name == "posix" and (not hasattr(os, "geteuid") or os.geteuid() != 0),
        "chmod-based permission test needs POSIX and a non-root user",
    )
    def test_session_slug_roundtrip_unreadable(self):
        """projects/ itself unreadable -> 'failed' (criterion 13), not
        'empty' -- an unreadable directory is a real problem, distinct from
        "nothing to check against"."""
        self.build_project(name="proj-a")
        out_path = os.path.join(self.tmp, "facts.json")
        write_config(self.config_dir, [self.projects_root], out_path)

        projects_dir = os.path.join(self.config_dir, "projects")
        os.makedirs(projects_dir, exist_ok=True)
        original_mode = os.stat(projects_dir).st_mode
        os.chmod(projects_dir, 0o000)
        # Restore permissions before tearDown()'s TemporaryDirectory.cleanup()
        # runs -- addCleanup fires *after* tearDown, so registering the
        # chmod-restore there would try to chmod a path tearDown may have
        # already removed. A plain try/finally guarantees restoration
        # happens first, from inside the test method itself.
        try:
            r = run_sarathi(["doctor", "--json"], config_dir=self.config_dir)
            payload = json.loads(r.stdout)
            check = next(c for c in payload["checks"] if c["name"] == "session_slug_roundtrip")
            self.assertEqual(check["status"], "failed")
        finally:
            os.chmod(projects_dir, original_mode)


class TestDefaultCommand(TempDirCase):
    def test_default_command_accepts_as_of(self):
        """BUG-3 (rev 3 review finding): `python3 sarathi.py --as-of <date>`
        with no explicit `measure` must parse and behave identically to
        `measure --as-of <date>` -- the documented default-command form
        must actually work."""
        self.build_project(name="proj", commit_date=(date.today() - timedelta(days=5)).isoformat())
        out_path = os.path.join(self.tmp, "facts.json")
        write_config(self.config_dir, [self.projects_root], out_path)
        as_of = date.today().isoformat()

        r_default = run_sarathi(["--as-of", as_of], config_dir=self.config_dir)
        self.assertEqual(r_default.returncode, 0, r_default.stderr)
        with open(out_path) as fh:
            facts_default = json.load(fh)["facts"]

        r_explicit = run_sarathi(["measure", "--as-of", as_of], config_dir=self.config_dir)
        self.assertEqual(r_explicit.returncode, 0, r_explicit.stderr)
        with open(out_path) as fh:
            facts_explicit = json.load(fh)["facts"]

        self.assertEqual(facts_default, facts_explicit)

    def test_bare_invocation_defaults_to_measure(self):
        self.build_project(name="proj")
        out_path = os.path.join(self.tmp, "facts.json")
        write_config(self.config_dir, [self.projects_root], out_path)
        r = run_sarathi([], config_dir=self.config_dir)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.exists(out_path))


class TestGitHelper(TempDirCase):
    def test_git_helper_distinguishes_failure_from_empty(self):
        repo = os.path.join(self.tmp, "empty-repo")
        init_git_repo(repo)  # zero commits

        status_empty, last_commit, reason_empty = sarathi.git_log_last_commit(repo, git_bin="git")
        self.assertEqual(status_empty, "ok")
        self.assertIsNone(last_commit)
        self.assertIsNone(reason_empty)

        status_failed, last_commit_failed, reason_failed = sarathi.git_log_last_commit(
            repo, git_bin="/nonexistent/definitely-not-git-xyz"
        )
        self.assertEqual(status_failed, "failed")
        self.assertIsNone(last_commit_failed)
        self.assertIn("git not found on PATH", reason_failed)

        self.assertNotEqual(status_empty, status_failed)


class TestNoNetworkImports(unittest.TestCase):
    def test_no_network_imports(self):
        with open(SARATHI_PATH, encoding="utf-8") as fh:
            source = fh.read()
        forbidden = ["urllib", "http.client", "httplib", "socket", "requests",
                     "ftplib", "smtplib", "xmlrpc"]
        import_lines = [
            ln for ln in source.splitlines()
            if re.match(r"^\s*(import|from)\s+", ln)
        ]
        for ln in import_lines:
            for name in forbidden:
                self.assertNotIn(
                    name, ln,
                    f"network-capable import found: {ln!r} (contains {name!r})",
                )


# ----------------------------------------------------------------------------
# SAR-02 additions below: plugin manifests, the doctor `branch` classifier,
# and the config schema v1 -> v2 split. Everything above this line is
# SAR-01's original suite, re-run unmodified as regression coverage (§8).
# ----------------------------------------------------------------------------
class TestPluginManifests(unittest.TestCase):
    """Criterion 1: plugin.json / marketplace.json parse as valid JSON and
    agree on the plugin name. Structural correctness only -- whether Claude
    Code's own plugin loader actually installs them (criterion 2) is
    reviewer-verified, not code-tested (the coder does not own that loader)."""

    def test_plugin_json_valid(self):
        path = os.path.join(REPO_ROOT, ".claude-plugin", "plugin.json")
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data["name"], "sarathi")
        self.assertEqual(data["version"], "0.5.0")

    def test_marketplace_json_valid(self):
        plugin_path = os.path.join(REPO_ROOT, ".claude-plugin", "plugin.json")
        with open(plugin_path, encoding="utf-8") as fh:
            plugin_data = json.load(fh)
        marketplace_path = os.path.join(REPO_ROOT, ".claude-plugin", "marketplace.json")
        with open(marketplace_path, encoding="utf-8") as fh:
            marketplace_data = json.load(fh)
        self.assertTrue(marketplace_data["plugins"])
        names = [p["name"] for p in marketplace_data["plugins"]]
        self.assertIn(plugin_data["name"], names)


class TestDoctorBranchClassifier(unittest.TestCase):
    """Criteria 6-8: compute_doctor_branch() is a pure function of the
    per-check statuses, tested directly against synthetic check lists so
    the classifier's own logic is verified independent of the real
    environment (git/python availability on the machine running the
    suite)."""

    def _checks(self, **overrides):
        """A full 8-name synthetic check list, all "ok" unless overridden
        by name -> status."""
        names = [
            "python_version", "git_present", "config_dir", "config",
            "project_roots_readable", "session_slug_roundtrip",
            "memory_parseable", "output_writable",
        ]
        return [
            {"name": n, "status": overrides.get(n, "ok"), "detail": "synthetic"}
            for n in names
        ]

    def test_doctor_branch_all_ok(self):
        checks = self._checks(session_slug_roundtrip="empty", memory_parseable="empty")
        self.assertEqual(sarathi.compute_doctor_branch(checks), "proceed")

    def test_doctor_branch_config_only_missing(self):
        checks = self._checks(config="failed")
        self.assertEqual(sarathi.compute_doctor_branch(checks), "init")

    def test_doctor_branch_config_only_stale(self):
        # Same shape as "missing" from the classifier's point of view --
        # it only looks at check *names* and *statuses*, never reasons
        # (criterion 7: "not found," unparseable JSON, or stale schema
        # version all route to "init" identically).
        checks = self._checks(config="failed")
        self.assertEqual(sarathi.compute_doctor_branch(checks), "init")

    def test_doctor_branch_env_broken(self):
        checks = self._checks(git_present="failed")
        self.assertEqual(sarathi.compute_doctor_branch(checks), "stop")

    def test_doctor_branch_env_and_config_broken(self):
        checks = self._checks(git_present="failed", config="failed")
        self.assertEqual(sarathi.compute_doctor_branch(checks), "stop")


class TestDoctorBranchIntegration(TempDirCase):
    """Same criteria (6-8), exercised end to end through the real `sarathi
    doctor --json` CLI output rather than a synthetic check list -- proves
    the classifier is actually wired into cmd_doctor()'s output, not just
    correct in isolation."""

    def _config_with_invoker(self, **kw):
        out_path = os.path.join(self.tmp, "facts.json")
        write_config(self.config_dir, [self.projects_root], out_path, **kw)
        return out_path

    def test_healthy_config_yields_proceed(self):
        self.build_project(name="healthy-proj")
        self._config_with_invoker()  # default: current schema, voice+invoker set
        r = run_sarathi(["doctor", "--json"], config_dir=self.config_dir)
        payload = json.loads(r.stdout)
        self.assertEqual(payload["branch"], "proceed")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_stale_v1_config_yields_init(self):
        self.build_project(name="healthy-proj")
        self._config_with_invoker(schema_version=1)
        r = run_sarathi(["doctor", "--json"], config_dir=self.config_dir)
        payload = json.loads(r.stdout)
        self.assertEqual(payload["branch"], "init")

    def test_missing_config_yields_init(self):
        r = run_sarathi(["doctor", "--json"], config_dir=self.config_dir)
        payload = json.loads(r.stdout)
        self.assertEqual(payload["branch"], "init")

    def test_git_missing_yields_stop_even_with_healthy_config(self):
        self.build_project(name="healthy-proj")
        self._config_with_invoker()
        empty_path_dir = tempfile.mkdtemp()
        try:
            r = run_sarathi(
                ["doctor", "--json"], config_dir=self.config_dir,
                path_override=empty_path_dir,
            )
        finally:
            os.rmdir(empty_path_dir)
        payload = json.loads(r.stdout)
        self.assertEqual(payload["branch"], "stop")

    def test_git_missing_and_config_stale_yields_stop(self):
        self.build_project(name="healthy-proj")
        self._config_with_invoker(schema_version=1)
        empty_path_dir = tempfile.mkdtemp()
        try:
            r = run_sarathi(
                ["doctor", "--json"], config_dir=self.config_dir,
                path_override=empty_path_dir,
            )
        finally:
            os.rmdir(empty_path_dir)
        payload = json.loads(r.stdout)
        self.assertEqual(payload["branch"], "stop")


class TestConfigSchemaV1V2Split(TempDirCase):
    """Criteria 18-23: load_config()'s required set stays v0.1's three
    keys forever; doctor's `config` check is the stricter, separate,
    skill-facing notion of "current"."""

    def test_config_v1_still_loads_for_measure(self):
        self.build_project(name="proj")
        out_path = os.path.join(self.tmp, "facts.json")
        write_config(self.config_dir, [self.projects_root], out_path, schema_version=1)

        # Direct load_config(): no error, no voice/invoker present or required.
        cfg, _ = sarathi.load_config(self.config_dir)
        self.assertEqual(cfg["schema_version"], 1)
        self.assertNotIn("voice", cfg)
        self.assertNotIn("invoker", cfg)

        # And the CLI: bare `measure` exits 0 and writes a fact sheet, exactly
        # as v0.1 did.
        r = run_sarathi(["measure"], config_dir=self.config_dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(os.path.exists(out_path))

    def test_config_v1_reports_stale_not_missing_key(self):
        out_path = os.path.join(self.tmp, "facts.json")
        write_config(self.config_dir, [self.projects_root], out_path, schema_version=1)
        stale_check = sarathi.check_config(self.config_dir)
        self.assertEqual(stale_check["status"], "failed")
        self.assertIn("stale", stale_check["detail"])
        self.assertNotIn("missing required key", stale_check["detail"])

        # Contrast against a genuinely-missing-required-key config, which
        # must produce different wording -- both are "failed", but for
        # distinguishable reasons (criterion 20 asserts the text itself
        # differs, not just the status).
        other_dir = os.path.join(self.tmp, "other-config")
        os.makedirs(other_dir, exist_ok=True)
        write_config(other_dir, [], out_path, omit_keys=["project_roots"])
        missing_check = sarathi.check_config(other_dir)
        self.assertEqual(missing_check["status"], "failed")
        self.assertIn("missing required key", missing_check["detail"])
        self.assertNotIn("stale", missing_check["detail"])
        self.assertNotEqual(stale_check["detail"], missing_check["detail"])

    def test_config_v2_valid(self):
        out_path = os.path.join(self.tmp, "facts.json")
        write_config(self.config_dir, [self.projects_root], out_path)  # v2 by default
        cfg, _ = sarathi.load_config(self.config_dir)
        self.assertEqual(cfg["schema_version"], sarathi.CONFIG_SCHEMA_VERSION)
        self.assertIn("voice", cfg)
        self.assertIn("invoker", cfg)
        check = sarathi.check_config(self.config_dir)
        self.assertEqual(check["status"], "ok")

    def test_config_rejects_bad_voice_value(self):
        out_path = os.path.join(self.tmp, "facts.json")
        write_config(
            self.config_dir, [self.projects_root], out_path,
            extra_keys={"voice": "sarcastic"},
        )
        with self.assertRaises(sarathi.ConfigError) as ctx:
            sarathi.load_config(self.config_dir)
        self.assertIn("voice", str(ctx.exception))

        # Rejected at load_config() itself means bare `measure` breaks too
        # (reviewer ruling: deliberate rule-1 strictness).
        r = run_sarathi(["measure"], config_dir=self.config_dir)
        self.assertNotEqual(r.returncode, 0)

    def test_config_v2_missing_invoker_flagged_by_doctor_not_measure(self):
        self.build_project(name="proj")
        out_path = os.path.join(self.tmp, "facts.json")
        write_config(
            self.config_dir, [self.projects_root], out_path,
            omit_keys=["invoker"],
        )  # schema_version 2, voice present, invoker absent

        # measure still runs -- criterion 18's optionality applies even at
        # the current schema version.
        r = run_sarathi(["measure"], config_dir=self.config_dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

        # doctor's stricter config check flags the inconsistency, worded
        # distinctly from the "stale v1" case (criterion 22: malformed v2,
        # not stale v1 -- the detail says so explicitly, even though it
        # names "stale" only to rule it out, so this checks for the
        # "is stale" verdict phrase specifically, not bare presence of the
        # word "stale" anywhere in the text).
        check = sarathi.check_config(self.config_dir)
        self.assertEqual(check["status"], "failed")
        self.assertIn("invoker", check["detail"])
        self.assertIn("malformed", check["detail"])
        self.assertNotIn("is stale", check["detail"])


class TestInitReusableProofs(TempDirCase):
    """Criterion 13/14 regression: slug(), check_session_slug_roundtrip(),
    check_output_writable(), and their newly-extracted pure cores remain
    callable with v0.1-compatible signatures/behavior, since `init`'s
    proofs depend on reusing them as-is rather than reimplementing (rule
    3)."""

    def test_slug_and_doctor_checks_reusable_by_init(self):
        proj = self.build_project(name="proj-a")
        out_path = os.path.join(self.tmp, "facts.json")
        write_config(self.config_dir, [self.projects_root], out_path)

        # slug() -- unchanged pure function.
        self.assertEqual(sarathi.slug(proj), re.sub(r"[^A-Za-z0-9]", "-", proj))

        # check_session_slug_roundtrip(config_dir) -- v0.1 signature, same
        # dict shape (name/status/detail), matches the just-added session.
        roundtrip = sarathi.check_session_slug_roundtrip(self.config_dir)
        self.assertEqual(roundtrip["name"], "session_slug_roundtrip")
        self.assertEqual(roundtrip["status"], "ok")

        # check_output_writable(config_dir) -- v0.1 signature, same shape.
        writable = sarathi.check_output_writable(self.config_dir)
        self.assertEqual(writable["name"], "output_writable")
        self.assertEqual(writable["status"], "ok")

        # The new pure cores init calls pre-config, proven to agree with
        # the doctor-check wrappers built on top of them.
        self.assertTrue(sarathi.path_is_writable(out_path))
        proof = sarathi.slug_roundtrip_status(self.config_dir, [proj])
        self.assertEqual(proof["status"], "ok")


# ----------------------------------------------------------------------------
# SAR-03 additions below: decision-file parsing, ruled_flags/ruled,
# verdict-aware expiry, the `slug` field, and steer_candidates. Everything
# above this line is SAR-01's and SAR-02's original suite, re-run unmodified
# as regression coverage (§8/§12), with one necessary exception: the version
# literal in TestPluginManifests.test_plugin_json_valid, which this story's
# own mandated 0.2.0 -> 0.3.0 plugin.json bump requires updating (documented
# in the coder's handoff) -- the same kind of one-line bump SAR-02 itself
# introduced for the 0.1.0 -> 0.2.0 transition.
# ----------------------------------------------------------------------------
class TestDecisionParsing(TempDirCase):
    """Criteria 1-6: parse_decision_file() / the decisions subsection built
    by measure_project(), exercised via direct (non-subprocess) calls for
    speed and precise control over the fixture."""

    def test_decision_file_parses_valid(self):
        root = self.build_project(name="proj", add_memory=False)
        make_decision_file(
            self.config_dir, root, "sarathi-decision-2026-08-01.md",
            verdict="parked", decided="2026-08-01", description="waiting on X",
        )
        entry = sarathi.measure_project(root, self.config_dir, date.today())
        self.assertEqual(entry["decisions"]["status"], "ok")
        self.assertEqual(len(entry["decisions"]["entries"]), 1)
        d = entry["decisions"]["entries"][0]
        self.assertEqual(d["verdict"], "parked")
        self.assertEqual(d["decided"], "2026-08-01")
        self.assertEqual(d["source"], "sarathi-decision-2026-08-01.md")

    def test_decisions_empty_when_no_matching_files(self):
        root = self.build_project(name="proj")
        entry = sarathi.measure_project(root, self.config_dir, date.today())
        self.assertEqual(entry["decisions"], {"status": "empty", "reason": None, "entries": []})

    def test_decision_file_bad_verdict_fails(self):
        root = self.build_project(name="proj", add_memory=False)
        make_decision_file(
            self.config_dir, root, "sarathi-decision-2026-08-01.md",
            verdict="maybe-later", decided="2026-08-01",
        )
        entry = sarathi.measure_project(root, self.config_dir, date.today())
        self.assertEqual(entry["decisions"]["status"], "failed")
        self.assertIn("sarathi-decision-2026-08-01.md", entry["decisions"]["reason"])
        self.assertEqual(entry["decisions"]["entries"], [])

    def test_decision_file_bad_date_fails(self):
        root = self.build_project(name="proj", add_memory=False)
        make_decision_file(
            self.config_dir, root, "sarathi-decision-2026-08-01.md",
            verdict="parked", decided="not-a-real-date",
        )
        entry = sarathi.measure_project(root, self.config_dir, date.today())
        self.assertEqual(entry["decisions"]["status"], "failed")
        self.assertEqual(entry["decisions"]["entries"], [])

    def test_decision_file_missing_verdict_fails(self):
        root = self.build_project(name="proj", add_memory=False)
        make_decision_file(
            self.config_dir, root, "sarathi-decision-2026-08-01.md",
            verdict=None, decided="2026-08-01",
        )
        entry = sarathi.measure_project(root, self.config_dir, date.today())
        self.assertEqual(entry["decisions"]["status"], "failed")
        self.assertEqual(entry["decisions"]["entries"], [])

    def test_decision_partial_failure_shape(self):
        root = self.build_project(name="proj", add_memory=False)
        make_decision_file(
            self.config_dir, root, "sarathi-decision-2026-08-01.md",
            verdict="parked", decided="2026-08-01",
        )
        make_decision_file(
            self.config_dir, root, "sarathi-decision-2026-08-02.md",
            verdict="bogus-verdict", decided="2026-08-02",
        )
        entry = sarathi.measure_project(root, self.config_dir, date.today())
        self.assertEqual(entry["decisions"]["status"], "ok")
        self.assertIn("sarathi-decision-2026-08-02.md", entry["decisions"]["reason"])
        self.assertEqual(len(entry["decisions"]["entries"]), 1)
        self.assertEqual(entry["decisions"]["entries"][0]["verdict"], "parked")

    def test_non_matching_filename_stays_regular_memory(self):
        root = self.build_project(name="proj", add_memory=False)
        # Filename does NOT match the decision pattern, even though its
        # frontmatter content looks decision-like -- the filename pattern,
        # not frontmatter content, is what reserves a file as a decision.
        make_memory_file(
            self.config_dir, root, "not-a-decision.md",
            {"name": "not-a-decision", "type": "sarathi-decision",
             "verdict": "parked", "decided": "2026-08-01"},
        )
        entry = sarathi.measure_project(root, self.config_dir, date.today())
        self.assertEqual(entry["decisions"], {"status": "empty", "reason": None, "entries": []})
        self.assertEqual(entry["memory"]["status"], "ok")
        self.assertEqual(len(entry["memory"]["entries"]), 1)

    def test_decision_file_excluded_from_memory_entries(self):
        root = self.build_project(name="proj", add_memory=True)  # regular note.md
        make_decision_file(
            self.config_dir, root, "sarathi-decision-2026-08-01.md",
            verdict="parked", decided="2026-08-01",
        )
        entry = sarathi.measure_project(root, self.config_dir, date.today())
        memory_names = [e["name"] for e in entry["memory"]["entries"]]
        self.assertNotIn("sarathi-decision-2026-08-01", memory_names)
        self.assertEqual(len(entry["memory"]["entries"]), 1)
        self.assertEqual(len(entry["decisions"]["entries"]), 1)

    def test_decision_filename_collision_gets_suffix(self):
        root = self.build_project(name="proj", add_memory=False)
        make_decision_file(
            self.config_dir, root, "sarathi-decision-2026-08-01.md",
            verdict="parked", decided="2026-08-01", description="first",
        )
        make_decision_file(
            self.config_dir, root, "sarathi-decision-2026-08-01-2.md",
            verdict="dead", decided="2026-08-01", description="second",
        )
        entry = sarathi.measure_project(root, self.config_dir, date.today())
        self.assertEqual(entry["decisions"]["status"], "ok")
        sources = {d["source"] for d in entry["decisions"]["entries"]}
        self.assertEqual(
            sources, {"sarathi-decision-2026-08-01.md", "sarathi-decision-2026-08-01-2.md"},
        )
        self.assertEqual(len(entry["decisions"]["entries"]), 2)


class TestRuledFlagsAndStaleness(TempDirCase):
    """Criteria 7-10: ruled_flags computation and the strictly-after
    staleness semantics. Uses "stalled mid-flight" (git commit age + dirty
    count) rather than "dormant" to construct flags, since it doesn't
    depend on the actual filesystem mtimes build_project() writes at real
    "now" -- avoiding the need to backdate file mtimes for a deterministic
    fixture."""

    def test_ruled_flags_populated_for_unexpired_decision(self):
        as_of = date.today()
        commit_date = as_of - timedelta(days=20)
        root = self.build_project(
            name="stalled-proj", commit_date=commit_date.isoformat(), n_uncommitted=5,
            add_session=False,
        )
        make_decision_file(
            self.config_dir, root, f"sarathi-decision-{as_of.isoformat()}.md",
            verdict="parked", decided=as_of.isoformat(),
        )
        entry = sarathi.measure_project(root, self.config_dir, as_of)
        self.assertIn("stalled mid-flight", entry["flags"])
        self.assertEqual(len(entry["ruled_flags"]), 1)
        rf = entry["ruled_flags"][0]
        self.assertEqual(rf["flag"], "stalled mid-flight")
        self.assertEqual(rf["verdict"], "parked")
        self.assertEqual(rf["decided"], as_of.isoformat())
        # Raw flags is never mutated by ruling.
        self.assertEqual(entry["flags"], ["stalled mid-flight"])

    def test_ruled_flags_empty_when_decision_expired(self):
        as_of = date.today()
        commit_date = as_of - timedelta(days=20)
        decided = (as_of - timedelta(days=25)).isoformat()
        root = self.build_project(
            name="stalled-proj2", commit_date=commit_date.isoformat(), n_uncommitted=5,
        )
        make_decision_file(
            self.config_dir, root, f"sarathi-decision-{decided}.md",
            verdict="parked", decided=decided,
        )
        entry = sarathi.measure_project(root, self.config_dir, as_of)
        self.assertTrue(entry["decisions"]["entries"][0]["expired"])
        self.assertEqual(entry["ruled_flags"], [])
        self.assertIn("stalled mid-flight", entry["flags"])

    def test_decision_not_expired_by_same_day_session(self):
        as_of = date.today()
        root = self.build_project(name="session-proj", with_git=False, add_memory=False)
        make_decision_file(
            self.config_dir, root, f"sarathi-decision-{as_of.isoformat()}.md",
            verdict="keep-watching", decided=as_of.isoformat(),
        )
        entry = sarathi.measure_project(root, self.config_dir, as_of)
        self.assertFalse(entry["decisions"]["entries"][0]["expired"])

    def test_ruled_flags_empty_with_no_decisions(self):
        as_of = date.today()
        commit_date = as_of - timedelta(days=20)
        root = self.build_project(
            name="stalled-proj3", commit_date=commit_date.isoformat(), n_uncommitted=5,
        )
        entry = sarathi.measure_project(root, self.config_dir, as_of)
        self.assertEqual(entry["ruled_flags"], [])
        self.assertIn("stalled mid-flight", entry["flags"])


class TestOrphanDecisions(TempDirCase):
    """Criterion 11: orphan `decisions`/`ruled`, via collect_orphans()
    directly (same pattern as the existing TestOrphans class)."""

    def test_orphan_ruled_true_for_unexpired_decision(self):
        as_of = date.today()
        deleted_child = os.path.join(self.projects_root, "gone-project")
        deleted_slug = sarathi.slug(deleted_child)
        make_decision_file(
            self.config_dir, deleted_slug, f"sarathi-decision-{as_of.isoformat()}.md",
            verdict="dead", decided=as_of.isoformat(), is_slug=True,
        )
        _roots, root_children = sarathi.build_roots_section([self.projects_root])
        orphans = sarathi.collect_orphans(
            self.config_dir, [self.projects_root], root_children, as_of)
        entry = next(e for e in orphans["entries"] if e["slug"] == deleted_slug)
        self.assertTrue(entry["ruled"])
        self.assertEqual(len(entry["decisions"]["entries"]), 1)
        self.assertFalse(entry["decisions"]["entries"][0]["expired"])

    def test_orphan_ruled_false_after_new_memory_activity(self):
        as_of = date.today()
        decided = (as_of - timedelta(days=5)).isoformat()
        deleted_child = os.path.join(self.projects_root, "gone-project-2")
        deleted_slug = sarathi.slug(deleted_child)
        make_decision_file(
            self.config_dir, deleted_slug, f"sarathi-decision-{decided}.md",
            verdict="dead", decided=decided, is_slug=True,
        )
        # A later, non-decision memory note -- "someone came back to this."
        make_memory_file(
            self.config_dir, deleted_slug, "later-note.md",
            {"name": "later note", "description": "new info surfaced", "type": "project",
             "modified": as_of.isoformat()},
            is_slug=True,
        )
        _roots, root_children = sarathi.build_roots_section([self.projects_root])
        orphans = sarathi.collect_orphans(
            self.config_dir, [self.projects_root], root_children, as_of)
        entry = next(e for e in orphans["entries"] if e["slug"] == deleted_slug)
        self.assertFalse(entry["ruled"])
        self.assertTrue(entry["decisions"]["entries"][0]["expired"])


class TestProjectSlugField(TempDirCase):
    """Criterion 12: facts.projects.<key>.slug matches the internal
    slug(root) already used to resolve sessions/memory."""

    def test_project_entry_carries_slug(self):
        root = self.build_project(name="proj")
        entry = sarathi.measure_project(root, self.config_dir, date.today())
        self.assertEqual(entry["slug"], sarathi.slug(root))


class TestSteerCandidates(unittest.TestCase):
    """Criteria 13-16: compute_steer_candidates() as a pure function of
    already-built projects/orphans dicts -- avoids depending on real
    filesystem mtimes (which build_project() always sets to "now") to
    construct precise days_stalled values."""

    @staticmethod
    def _project(days_stalled, flags, ruled_flags=None, slug_val=None, status="ok"):
        return {
            "status": status,
            "slug": slug_val or f"slug-{days_stalled}",
            "flags": flags,
            "ruled_flags": ruled_flags or [],
            "git": {"last_commit": None},
            "files": {"newest": None},
            "sessions": {"last_session": None},
            # last_commit/newest/last_session all None -> compute_days_stalled
            # would return the sentinel; override days_stalled precisely by
            # setting last_commit to an as_of-relative date instead.
        }

    def test_steer_candidates_ranked_longest_stalled_first(self):
        as_of = date(2026, 8, 1)

        def proj(days):
            p = self._project(days, ["dormant"])
            p["git"]["last_commit"] = (as_of - timedelta(days=days)).isoformat()
            return p

        projects = {"near": proj(10), "far": proj(90)}
        candidates = sarathi.compute_steer_candidates(projects, [], as_of)
        self.assertEqual([c["key"] for c in candidates], ["far", "near"])
        self.assertEqual(candidates[0]["days_stalled"], 90)
        self.assertEqual(candidates[1]["days_stalled"], 10)

    def test_fully_ruled_project_excluded_from_candidates(self):
        as_of = date(2026, 8, 1)
        ruled_flags = [{"flag": "dormant", "verdict": "parked",
                         "decided": "2026-08-01", "source": "x.md"}]
        projects = {"ruled-proj": self._project(90, ["dormant"], ruled_flags=ruled_flags)}
        candidates = sarathi.compute_steer_candidates(projects, [], as_of)
        self.assertEqual(candidates, [])

    def test_orphan_candidate_uses_sentinel_days(self):
        as_of = date(2026, 8, 1)
        orphan_entries = [{"slug": "orphan-slug", "ruled": False}]
        candidates = sarathi.compute_steer_candidates({}, orphan_entries, as_of)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["kind"], "orphan")
        self.assertEqual(
            candidates[0]["days_stalled"], sarathi.THRESHOLDS["UNREACHABLE_DAYS_SENTINEL"],
        )

    def test_steer_candidates_empty_when_nothing_unruled(self):
        as_of = date(2026, 8, 1)
        projects = {"p": self._project(0, [])}
        orphan_entries = [{"slug": "o", "ruled": True}]
        candidates = sarathi.compute_steer_candidates(projects, orphan_entries, as_of)
        self.assertEqual(candidates, [])


class TestSchemaAndBackwardCompat(TempDirCase):
    """Criteria 17-19: determinism with the new fields, always-present
    empty-by-default shape, and the schema_version bump."""

    def test_determinism_hash_with_decision_fields(self):
        root = self.build_project(commit_date=(date.today() - timedelta(days=5)).isoformat())
        as_of_str = date.today().isoformat()
        make_decision_file(
            self.config_dir, root, f"sarathi-decision-{as_of_str}.md",
            verdict="parked", decided=as_of_str,
        )
        out_path = os.path.join(self.tmp, "facts.json")
        write_config(self.config_dir, [self.projects_root], out_path)

        r1 = run_sarathi(["measure", "--as-of", as_of_str], config_dir=self.config_dir)
        self.assertEqual(r1.returncode, 0, r1.stderr)
        with open(out_path) as fh:
            facts1 = json.load(fh)["facts"]

        r2 = run_sarathi(["measure", "--as-of", as_of_str], config_dir=self.config_dir)
        self.assertEqual(r2.returncode, 0, r2.stderr)
        with open(out_path) as fh:
            facts2 = json.load(fh)["facts"]

        h1 = hashlib.sha256(json.dumps(facts1, sort_keys=True).encode()).hexdigest()
        h2 = hashlib.sha256(json.dumps(facts2, sort_keys=True).encode()).hexdigest()
        self.assertEqual(h1, h2)
        # Sanity: the new fields are actually present in the hashed subtree.
        self.assertIn("steer_candidates", facts1)
        self.assertIn("decisions", facts1["projects"]["alpha"])
        self.assertIn("ruled_flags", facts1["projects"]["alpha"])

    def test_new_fields_always_present_and_empty_by_default(self):
        self.build_project(name="plain-proj")
        out_path = os.path.join(self.tmp, "facts.json")
        write_config(self.config_dir, [self.projects_root], out_path)
        r = run_sarathi(["measure"], config_dir=self.config_dir)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(out_path) as fh:
            facts = json.load(fh)["facts"]
        entry = facts["projects"]["plain-proj"]
        self.assertEqual(entry["decisions"], {"status": "empty", "reason": None, "entries": []})
        self.assertEqual(entry["ruled_flags"], [])
        self.assertIn("slug", entry)
        self.assertEqual(entry["slug"], sarathi.slug(
            os.path.join(self.projects_root, "plain-proj")))
        self.assertIn("steer_candidates", facts)
        self.assertEqual(facts["steer_candidates"], [])

    def test_fact_sheet_schema_version_is_2(self):
        self.build_project(name="p")
        out_path = os.path.join(self.tmp, "facts.json")
        write_config(self.config_dir, [self.projects_root], out_path)
        r = run_sarathi(["measure"], config_dir=self.config_dir)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(out_path) as fh:
            output = json.load(fh)
        self.assertEqual(output["schema_version"], 2)


class TestVerdictAwareExpiry(unittest.TestCase):
    """Criteria 34-36 (reviewer ruling, 2026-08-01): decision_is_expired()
    as a pure function, isolating the active-next grace-window rule from
    the ordinary activity-based staleness check."""

    def test_active_next_expires_after_grace_without_activity(self):
        as_of = date(2026, 8, 1)
        grace = sarathi.THRESHOLDS["ACTIVE_NEXT_GRACE_DAYS"]
        decided = (as_of - timedelta(days=grace + 1)).isoformat()
        decision = {"verdict": "active-next", "decided": decided}
        self.assertTrue(sarathi.decision_is_expired(decision, [], as_of))

    def test_active_next_fresh_within_grace_not_expired(self):
        as_of = date(2026, 8, 1)
        grace = sarathi.THRESHOLDS["ACTIVE_NEXT_GRACE_DAYS"]
        decided = (as_of - timedelta(days=grace - 1)).isoformat()
        decision = {"verdict": "active-next", "decided": decided}
        self.assertFalse(sarathi.decision_is_expired(decision, [], as_of))

    def test_active_next_activity_expiry_still_applies(self):
        as_of = date(2026, 8, 1)
        decided = (as_of - timedelta(days=3)).isoformat()  # well within the grace window
        activity_after = (as_of - timedelta(days=1)).isoformat()  # strictly after decided
        decision = {"verdict": "active-next", "decided": decided}
        self.assertTrue(sarathi.decision_is_expired(decision, [activity_after], as_of))

    def test_other_verdicts_never_time_expire(self):
        as_of = date(2026, 8, 1)
        decided = (as_of - timedelta(days=400)).isoformat()
        for verdict in ("parked", "dead", "keep-watching"):
            decision = {"verdict": verdict, "decided": decided}
            self.assertFalse(
                sarathi.decision_is_expired(decision, [], as_of),
                f"{verdict} should never time-expire",
            )


# ----------------------------------------------------------------------------
# SAR-04 additions below: render_report.py's deterministic injection, the
# shipped template's static structural properties, and the pinned payload
# schema shape (§12 of SAR-04). Everything above this line is SAR-01/02/03's
# original suite, re-run unmodified as regression coverage, with one
# necessary exception: the version literal in
# TestPluginManifests.test_plugin_json_valid, which this story's own mandated
# 0.3.0 -> 0.4.0 plugin.json bump requires updating (documented in the
# coder's handoff) -- the same kind of one-line bump SAR-02 and SAR-03 each
# already introduced for their own version transitions. sarathi.py itself has
# zero diff in this story (§3/§4), so nothing else above this line changed.
# ----------------------------------------------------------------------------
REPORT_TEMPLATE_PATH = os.path.join(REPO_ROOT, "skills", "report", "report-template.html")
RENDER_REPORT_PATH = os.path.join(REPO_ROOT, "skills", "report", "render_report.py")

# The §6-pinned payload example, copied verbatim as a fixture -- never live
# data (criterion 11 is validated against this, not against a real run).
PINNED_PAYLOAD_EXAMPLE = {
    "meta": {
        "as_of": "2026-08-01",
        "generated_at": "2026-08-01T14:32:07Z",
        "version_label": "2026-08-01 · 14:32 UTC",
        "voice": "plain",
    },
    "stats": {"projects": 30, "moving": 5, "losing_steam": 6, "forgotten": 4, "ruled": 3},
    "sections": {
        "moving": [
            {
                "key": "tokenomics",
                "kind": "project",
                "claims": [
                    {"text": "Shipped v1.0.0 this week — 37 commits, clean working tree.",
                     "citation": "facts.projects.tokenomics.git", "label": "measured"},
                    {"text": "One flip (repo to public) from announceable.",
                     "citation": "facts.projects.tokenomics.memory.entries[0]", "label": "derived"},
                ],
                "momentum_pct": 88,
            }
        ],
        "losing_steam": [
            {
                "key": "BankStatementReader",
                "kind": "project",
                "claims": [
                    {"text": "Last commit June 22, but 31 files sit uncommitted.",
                     "citation": "facts.projects.BankStatementReader.git", "label": "measured"},
                ],
                "momentum_pct": 35,
            }
        ],
        "forgotten": [
            {
                "key": "old-thing",
                "kind": "orphan",
                "claims": [
                    {"text": "No project directory on disk; memory trail only.",
                     "citation": "facts.orphans.entries[3]", "label": "measured"},
                ],
            }
        ],
        "ruled": [
            {
                "key": "EmailOrganiser",
                "kind": "orphan",
                "claims": [
                    {"text": "Declared dead.",
                     "citation": "facts.orphans.entries[1].decisions.entries[0]", "label": "measured"},
                ],
                "ruled_meta": {"verdict": "dead", "decided": "2026-08-01"},
            }
        ],
    },
    "steer_preview": [
        {"key": "Chitragupta", "kind": "project",
         "prompt": "Park it, say it's next, declare it dead, or keep watching?"},
    ],
}


def _read_template():
    with open(REPORT_TEMPLATE_PATH, encoding="utf-8") as fh:
        return fh.read()


def _extract_injected_json(fragment):
    """Pull the text between the pinned id="sarathi-payload" script tags out
    of a rendered fragment/standalone document and return it unparsed (the
    caller decides whether to json.loads() it)."""
    marker = 'id="sarathi-payload">'
    start = fragment.index(marker) + len(marker)
    end = fragment.index("</script>", start)
    return fragment[start:end].strip()


class TestRenderFragmentInjection(unittest.TestCase):
    """Criteria 1-4: render_fragment()'s deterministic marker injection,
    round-trip fidelity, and marker-count enforcement (design rule 2)."""

    def setUp(self):
        self.template = (
            "<div>before</div>\n"
            '<script type="application/json" id="sarathi-payload">\n'
            "__SARATHI_REPORT_PAYLOAD__\n"
            "</script>\n"
            "<div>after</div>\n"
        )
        self.payload = {"a": 1, "b": [1, 2, 3], "c": {"d": "e"}}

    def test_render_fragment_roundtrip(self):
        out1 = render_report.render_fragment(self.template, self.payload)
        out2 = render_report.render_fragment(self.template, self.payload)
        self.assertEqual(out1, out2)  # byte-identical given the same inputs, twice
        self.assertNotIn(render_report.MARKER, out1)
        self.assertEqual(json.loads(_extract_injected_json(out1)), self.payload)

    def test_render_fragment_marker_count_enforced(self):
        zero_marker = self.template.replace(render_report.MARKER, "")
        with self.assertRaises(render_report.TemplateError):
            render_report.render_fragment(zero_marker, self.payload)

        dup_marker = self.template + render_report.MARKER
        with self.assertRaises(render_report.TemplateError):
            render_report.render_fragment(dup_marker, self.payload)

    def test_render_fragment_escapes_closing_script_tag(self):
        payload = {"text": "a memory that says </script> and <!-- inline, verbatim"}
        out = render_report.render_fragment(self.template, payload)
        injected = _extract_injected_json(out)
        self.assertNotIn("<", injected)  # every '<' escaped to \u003c, reviewer ruling
        self.assertNotIn("</script>", injected)
        self.assertNotIn("<!--", injected)
        self.assertEqual(json.loads(injected), payload)  # round-trip still holds exactly

    def test_render_fragment_no_document_wrapper(self):
        out = render_report.render_fragment(self.template, self.payload)
        self.assertNotIn("<!DOCTYPE", out)
        self.assertNotIn("<html", out)
        self.assertNotIn("<head>", out)
        self.assertNotIn("<body>", out)


class TestRenderStandalone(unittest.TestCase):
    """Criterion 6: render_standalone() wraps the same injected content in a
    minimal document shell -- adds nothing but the shell itself."""

    def setUp(self):
        self.template = (
            '<script type="application/json" id="sarathi-payload">\n'
            "__SARATHI_REPORT_PAYLOAD__\n"
            "</script>\n"
        )
        self.payload = {"x": 1}
        self.title = "Sarathi — Direction Report"

    def test_render_standalone_wraps_with_title_and_fragment(self):
        out = render_report.render_standalone(self.template, self.payload, self.title)
        self.assertEqual(out.count("<!DOCTYPE html>"), 1)
        self.assertEqual(out.count("<html>"), 1)
        self.assertEqual(out.count("<head>"), 1)
        self.assertEqual(out.count("<body>"), 1)
        self.assertIn("<title>{}</title>".format(self.title), out)

    def test_render_standalone_and_fragment_share_injected_content(self):
        fragment = render_report.render_fragment(self.template, self.payload)
        standalone = render_report.render_standalone(self.template, self.payload, self.title)
        self.assertIn(fragment, standalone)  # shell wraps around it, changes nothing inside

    def test_render_standalone_marker_count_enforced(self):
        zero_marker = self.template.replace(render_report.MARKER, "")
        with self.assertRaises(render_report.TemplateError):
            render_report.render_standalone(zero_marker, self.payload, self.title)


class TestReportTemplateStaticStructure(unittest.TestCase):
    """Criteria 7-10, 28: the shipped template's static structural
    properties, scanned as plain text -- no browser/JS execution needed."""

    @classmethod
    def setUpClass(cls):
        cls.template = _read_template()

    def test_template_no_external_urls(self):
        self.assertNotIn("http://", self.template)
        self.assertNotIn("https://", self.template)

    def test_template_has_reduced_motion_media_query(self):
        self.assertIn("@media (prefers-reduced-motion: reduce)", self.template)

    def test_template_has_theme_aware_rules(self):
        self.assertIn("@media (prefers-color-scheme: dark)", self.template)
        self.assertIn('data-theme="dark"', self.template)

    def test_template_marker_present_exactly_once_in_id_script_block(self):
        self.assertEqual(self.template.count(render_report.MARKER), 1)
        marker_idx = self.template.index(render_report.MARKER)
        script_open = self.template.rindex(
            '<script type="application/json" id="sarathi-payload">', 0, marker_idx)
        script_close = self.template.index("</script>", marker_idx)
        self.assertLess(script_open, marker_idx)
        self.assertLess(marker_idx, script_close)

    def test_template_no_document_wrapper_tags(self):
        self.assertNotIn("<!DOCTYPE", self.template)
        self.assertNotIn("<html", self.template)
        self.assertNotIn("<head>", self.template)
        self.assertNotIn("<body>", self.template)

    def test_template_no_machine_specific_path(self):
        # criterion 28: environment neutrality -- no literal home dir, no
        # hardcoded /Users/... or C:\ path baked into the shipped template.
        self.assertNotIn("/Users/", self.template)
        self.assertNotIn("/home/", self.template)


class TestPayloadExampleSchemaShape(unittest.TestCase):
    """Criterion 11: the pinned §6 payload example validated against the
    schema shape -- keys present, every claim carries citation+label, every
    label is exactly 'measured' or 'derived'."""

    def test_payload_example_matches_pinned_schema_shape(self):
        payload = PINNED_PAYLOAD_EXAMPLE
        self.assertIn("meta", payload)
        self.assertIn("stats", payload)
        self.assertIn("sections", payload)
        self.assertIn("steer_preview", payload)
        for name in ("moving", "losing_steam", "forgotten", "ruled"):
            self.assertIn(name, payload["sections"])
            self.assertIsInstance(payload["sections"][name], list)
        for section in payload["sections"].values():
            for item in section:
                for claim in item["claims"]:
                    self.assertIn("citation", claim)
                    self.assertIn("label", claim)
                    self.assertIn(claim["label"], ("measured", "derived"))

    def test_payload_example_renders_without_error(self):
        # End-to-end sanity: the pinned example actually injects cleanly
        # into the shipped template and round-trips exactly.
        out = render_report.render_fragment(_read_template(), PINNED_PAYLOAD_EXAMPLE)
        self.assertEqual(json.loads(_extract_injected_json(out)), PINNED_PAYLOAD_EXAMPLE)


class TestRenderReportCLI(unittest.TestCase):
    """The --out CLI path produces the same content the function-level call
    would -- exercised via subprocess, the real CLI entry point, the same
    way tests/fixtures.py's run_sarathi() exercises sarathi.py's own CLI."""

    def test_render_report_cli_writes_expected_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload_path = os.path.join(tmp, "payload.json")
            with open(payload_path, "w", encoding="utf-8") as fh:
                json.dump(PINNED_PAYLOAD_EXAMPLE, fh)
            out_path = os.path.join(tmp, "fragment.html")
            r = subprocess.run(
                [sys.executable, RENDER_REPORT_PATH,
                 "--template", REPORT_TEMPLATE_PATH,
                 "--payload", payload_path,
                 "--out", out_path],
                capture_output=True, text=True,
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            with open(out_path, encoding="utf-8") as fh:
                cli_output = fh.read()

            direct_output = render_report.render_fragment(_read_template(), PINNED_PAYLOAD_EXAMPLE)
            self.assertEqual(cli_output, direct_output)

    def test_render_report_cli_standalone_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload_path = os.path.join(tmp, "payload.json")
            with open(payload_path, "w", encoding="utf-8") as fh:
                json.dump(PINNED_PAYLOAD_EXAMPLE, fh)
            out_path = os.path.join(tmp, "report-2026-08-01.html")
            r = subprocess.run(
                [sys.executable, RENDER_REPORT_PATH,
                 "--template", REPORT_TEMPLATE_PATH,
                 "--payload", payload_path,
                 "--standalone", "Sarathi — Direction Report",
                 "--out", out_path],
                capture_output=True, text=True,
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            with open(out_path, encoding="utf-8") as fh:
                content = fh.read()
            self.assertEqual(content.count("<!DOCTYPE html>"), 1)
            self.assertIn("<title>Sarathi — Direction Report</title>", content)

    def test_render_report_cli_marker_error_exits_nonzero(self):
        # rule 2: a broken template (marker missing) must fail loudly via
        # the CLI too, not just at the function level.
        with tempfile.TemporaryDirectory() as tmp:
            broken_template_path = os.path.join(tmp, "broken.html")
            with open(broken_template_path, "w", encoding="utf-8") as fh:
                fh.write("<div>no marker here</div>")
            payload_path = os.path.join(tmp, "payload.json")
            with open(payload_path, "w", encoding="utf-8") as fh:
                json.dump(PINNED_PAYLOAD_EXAMPLE, fh)
            r = subprocess.run(
                [sys.executable, RENDER_REPORT_PATH,
                 "--template", broken_template_path,
                 "--payload", payload_path],
                capture_output=True, text=True,
            )
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("marker", r.stderr.lower())


# ----------------------------------------------------------------------------
# SAR-05 additions below: the memory ledger's payload builder
# (skills/memory/build_ledger_payload.py) and its shipped template's static
# structural properties (§12 of SAR-05). Everything above this line is
# SAR-01-04's original suite, re-run unmodified as regression coverage, with
# one necessary exception: the version literal in
# TestPluginManifests.test_plugin_json_valid, updated above to "0.5.0" for
# this story's mandated 0.4.0 -> 0.5.0 plugin.json bump -- the same kind of
# one-line bump SAR-02/03/04 each already introduced for their own version
# transitions. sarathi.py and skills/report/render_report.py both have zero
# diff in this story (SAR-05 §3/§7), so nothing else above this line changed.
# ----------------------------------------------------------------------------
MEMORY_SKILL_DIR = os.path.join(REPO_ROOT, "skills", "memory")
if MEMORY_SKILL_DIR not in sys.path:
    sys.path.insert(0, MEMORY_SKILL_DIR)
import build_ledger_payload  # noqa: E402

LEDGER_TEMPLATE_PATH = os.path.join(REPO_ROOT, "skills", "memory", "ledger-template.html")

# render_report.py's exact content fingerprint, computed once from the
# SAR-04-shipped file on disk before this story touched anything else in the
# repo (this story never opens that file for writing -- criterion 21). A
# content hash is used instead of `git diff` because the coder for this
# story is barred from running any git command at all; any future edit to
# render_report.py -- accidental or not -- breaks this test immediately.
RENDER_REPORT_PY_SHA256 = "77350c1e50183868312bc108c051034e6fa94e42fac95f2851ad7b0ebbab4bc5"


def _read_ledger_template():
    with open(LEDGER_TEMPLATE_PATH, encoding="utf-8") as fh:
        return fh.read()


# The §6-pinned ledger payload example, copied verbatim as a fixture -- never
# live data (mirrors PINNED_PAYLOAD_EXAMPLE's role for the report above).
PINNED_LEDGER_PAYLOAD_EXAMPLE = {
    "meta": {
        "as_of": "2026-08-01",
        "generated_at": "2026-08-01T14:32:07Z",
        "version_label": "2026-08-01 · 14:32 UTC",
    },
    "stats": {
        "total_entries": 14,
        "by_group": {"user": 1, "feedback": 3, "project": 6, "reference": 2, "untyped": 2},
        "sources_with_memory": 5,
        "steering_decisions": 3,
    },
    "groups": [
        {"type": "user", "label": "about you", "entries": []},
        {
            "type": "feedback",
            "label": "working style",
            "entries": [
                {
                    "name": "git-publish-hands-off",
                    "desc": "For git/publish/release steps, give the user runnable commands "
                            "instead of executing them",
                    "date": "2026-07-28",
                    "type": "feedback",
                    "source": "tokenomics",
                    "source_kind": "project",
                    "threads": [],
                }
            ],
        },
        {
            "type": "project",
            "label": "project state",
            "entries": [
                {
                    "name": "tokenomics-release-refs",
                    "desc": "Install strings, update commands, test plan, and what's still open",
                    "date": "2026-07-29",
                    "type": "project",
                    "source": "tokenomics",
                    "source_kind": "project",
                    "threads": ["not shipped: public-repo flip still pending"],
                }
            ],
        },
        {"type": "reference", "label": "reference", "entries": []},
        {
            "type": "untyped",
            "label": "untyped",
            "entries": [
                {
                    "name": "old-thing-notes",
                    "desc": "Half-finished spike notes, no frontmatter type ever set",
                    "date": "2026-06-02",
                    "type": "untyped",
                    "source": "old-thing",
                    "source_kind": "orphan",
                    "threads": [],
                }
            ],
        },
    ],
    "decisions": [
        {
            "source": "EmailOrganiser",
            "source_kind": "orphan",
            "verdict": "dead",
            "decided": "2026-08-01",
            "reason": "declared dead — no longer relevant",
            "source_file": "sarathi-decision-2026-08-01.md",
            "expired": False,
        }
    ],
    "caveats": [
        {"source": "AiTools", "source_kind": "project", "kind": "memory",
         "status": "failed", "reason": "2 files unparseable: bad-frontmatter.md, empty.md"}
    ],
}


# -- fixture helpers: build fact-sheet-shaped dicts directly, precise control
# over every edge case without needing a real project tree on disk. Every
# shape mirrors exactly what sarathi.py's own measure_project()/
# collect_orphans() produce (cross-checked against TestDecisionParsing/
# TestOrphans above), so these fixtures are never a shape sarathi.py itself
# couldn't actually write. ----------------------------------------------------
def _memory_entry(name="note", desc="a note", date_val="2026-07-01", type_val="project",
                   threads=None):
    return {"name": name, "desc": desc, "date": date_val, "type": type_val,
            "threads": threads or []}


def _decision(verdict="parked", decided="2026-08-01", reason="", source_file=None,
              expired=False):
    return {
        "verdict": verdict, "decided": decided, "reason": reason,
        "source": source_file or "sarathi-decision-{0}.md".format(decided), "expired": expired,
    }


def _project_entry(status="ok", memory_entries=None, memory_status="ok", memory_reason=None,
                    decisions_entries=None, decisions_status=None, decisions_reason=None):
    memory_entries = memory_entries or []
    decisions_entries = decisions_entries or []
    if decisions_status is None:
        decisions_status = "ok" if decisions_entries else "empty"
    return {
        "status": status,
        "memory": {"status": memory_status, "reason": memory_reason, "entries": memory_entries},
        "decisions": {"status": decisions_status, "reason": decisions_reason,
                      "entries": decisions_entries},
    }


def _orphan_entry(slug_val, memory_entries=None, memory_status="ok", memory_reason=None,
                   decisions_entries=None, decisions_status=None, decisions_reason=None):
    memory_entries = memory_entries or []
    decisions_entries = decisions_entries or []
    if decisions_status is None:
        decisions_status = "ok" if decisions_entries else "empty"
    return {
        "slug": slug_val,
        "status": memory_status,
        "reason": memory_reason,
        "memory": memory_entries,
        "decisions": {"status": decisions_status, "reason": decisions_reason,
                      "entries": decisions_entries},
        "ruled": False,
    }


def _fact_sheet(as_of="2026-08-01", generated_at="2026-08-01T14:32:07Z",
                 roots=None, projects=None, orphans=None):
    orphans = orphans or []
    return {
        "schema_version": 2,
        "run": {"generated_at": generated_at},
        "facts": {
            "as_of": as_of,
            "roots": roots or {},
            "projects": projects or {},
            "orphans": {"status": "ok" if orphans else "empty", "entries": orphans},
            "steer_candidates": [],  # never read by build_ledger_payload (criterion 9)
        },
    }


class TestLedgerBucketing(unittest.TestCase):
    """Criteria 1-2: bucket_for_type()/build_payload() grouping."""

    def test_group_bucketing_known_types(self):
        projects = {
            "proj-a": _project_entry(memory_entries=[
                _memory_entry(name="u1", type_val="user"),
                _memory_entry(name="f1", type_val="feedback"),
                _memory_entry(name="p1", type_val="project"),
                _memory_entry(name="r1", type_val="reference"),
            ]),
        }
        payload = build_ledger_payload.build_payload(_fact_sheet(projects=projects))
        by_type = {g["type"]: [e["name"] for e in g["entries"]] for g in payload["groups"]}
        self.assertEqual(by_type["user"], ["u1"])
        self.assertEqual(by_type["feedback"], ["f1"])
        self.assertEqual(by_type["project"], ["p1"])
        self.assertEqual(by_type["reference"], ["r1"])
        self.assertEqual(by_type["untyped"], [])

    def test_group_bucketing_falls_through_to_untyped(self):
        projects = {
            "proj-a": _project_entry(memory_entries=[
                _memory_entry(name="def", type_val="untyped"),
                _memory_entry(name="scratch-note", type_val="scratch"),
            ]),
        }
        payload = build_ledger_payload.build_payload(_fact_sheet(projects=projects))
        untyped_group = next(g for g in payload["groups"] if g["type"] == "untyped")
        names = [e["name"] for e in untyped_group["entries"]]
        self.assertEqual(names, ["def", "scratch-note"])
        raw_types = {e["name"]: e["type"] for e in untyped_group["entries"]}
        # criterion 2: the raw type field is never rewritten to match the bucket.
        self.assertEqual(raw_types["scratch-note"], "scratch")
        self.assertEqual(raw_types["def"], "untyped")


class TestLedgerGroupsAlwaysPresent(unittest.TestCase):
    """Criterion 3."""

    def test_all_five_groups_always_present_in_fixed_order(self):
        payload = build_ledger_payload.build_payload(_fact_sheet())
        types = [g["type"] for g in payload["groups"]]
        self.assertEqual(types, ["user", "feedback", "project", "reference", "untyped"])
        labels = {g["type"]: g["label"] for g in payload["groups"]}
        self.assertEqual(labels, {
            "user": "about you", "feedback": "working style", "project": "project state",
            "reference": "reference", "untyped": "untyped",
        })
        for g in payload["groups"]:
            self.assertEqual(g["entries"], [])


class TestLedgerEntryFidelity(unittest.TestCase):
    """Criterion 4."""

    def test_entry_fields_copied_verbatim(self):
        entry = _memory_entry(
            name="git-publish-hands-off",
            desc='For git/publish steps <weird> chars & "quotes"',
            date_val="2026-07-28", type_val="feedback",
            threads=["not shipped: x"],
        )
        projects = {"tokenomics": _project_entry(memory_entries=[entry])}
        payload = build_ledger_payload.build_payload(_fact_sheet(projects=projects))
        out = next(g for g in payload["groups"] if g["type"] == "feedback")["entries"][0]
        self.assertEqual(out["name"], entry["name"])
        self.assertEqual(out["desc"], entry["desc"])
        self.assertEqual(out["date"], entry["date"])
        self.assertEqual(out["type"], entry["type"])
        self.assertEqual(out["threads"], entry["threads"])


class TestLedgerVoiceHasNoEffect(unittest.TestCase):
    """Criterion 5: build_payload() takes only a fact sheet -- config.json
    (and therefore `voice`) is never read, so it structurally cannot affect
    this payload."""

    def test_voice_has_no_effect_on_ledger_payload(self):
        sig = inspect.signature(build_ledger_payload.build_payload)
        self.assertEqual(list(sig.parameters), ["fact_sheet"])
        payload = build_ledger_payload.build_payload(_fact_sheet())
        self.assertNotIn("voice", payload["meta"])

        fs = _fact_sheet(projects={"p": _project_entry(memory_entries=[_memory_entry()])})
        p1 = build_ledger_payload.build_payload(fs)
        p2 = build_ledger_payload.build_payload(fs)
        self.assertEqual(p1, p2)


class TestLedgerSourceFields(unittest.TestCase):
    """Criteria 6-7."""

    def test_project_source_is_key_orphan_source_is_trimmed_slug(self):
        root = "/Users/alice/Projects"
        root_slug = build_ledger_payload.slug(os.path.normpath(root))
        orphan_slug = "{0}-old-thing".format(root_slug)
        projects = {"tokenomics": _project_entry(memory_entries=[_memory_entry(name="p1")])}
        orphans = [_orphan_entry(orphan_slug, memory_entries=[_memory_entry(name="o1")])]
        roots = {root: {"status": "ok", "reason": None, "projects": 1}}
        payload = build_ledger_payload.build_payload(
            _fact_sheet(projects=projects, orphans=orphans, roots=roots))
        all_entries = [e for g in payload["groups"] for e in g["entries"]]
        proj_entry = next(e for e in all_entries if e["name"] == "p1")
        orphan_entry = next(e for e in all_entries if e["name"] == "o1")
        self.assertEqual(proj_entry["source"], "tokenomics")
        self.assertEqual(proj_entry["source_kind"], "project")
        self.assertEqual(orphan_entry["source"], "old-thing")
        self.assertEqual(orphan_entry["source_kind"], "orphan")
        # raw slug (embeds the local OS username) never leaks into the payload
        self.assertNotIn(orphan_slug, json.dumps(payload))


class TestLedgerFailedProjectSkipped(TempDirCase):
    """Criterion 8, real sarathi.py fixture (mirrors TestFailedEntryShape's
    own technique above)."""

    def test_failed_project_entry_skipped_without_error(self):
        missing_child = os.path.join(self.projects_root, "vanished-child")
        failed_entry = sarathi.measure_project(missing_child, self.config_dir, date.today())
        self.assertEqual(failed_entry["status"], "failed")
        self.assertNotIn("memory", failed_entry)
        self.assertNotIn("decisions", failed_entry)

        projects = {
            "vanished-child": failed_entry,
            "ok-proj": _project_entry(memory_entries=[_memory_entry(name="still-here")]),
        }
        payload = build_ledger_payload.build_payload(_fact_sheet(projects=projects))
        all_names = [e["name"] for g in payload["groups"] for e in g["entries"]]
        self.assertEqual(all_names, ["still-here"])  # no crash, no contribution


class TestLedgerPayloadOnlyReadsDocumentedPaths(unittest.TestCase):
    """Criterion 9."""

    def test_payload_reads_only_documented_fact_sheet_paths(self):
        base_projects = {"p": _project_entry(memory_entries=[_memory_entry(name="n1")])}
        fs1 = _fact_sheet(projects=base_projects)
        fs2 = _fact_sheet(projects=base_projects)
        fs2["facts"]["steer_candidates"] = [
            {"kind": "project", "key": "p", "slug": "x", "days_stalled": 999,
             "unruled_flags": ["dormant"]}
        ]
        self.assertEqual(
            build_ledger_payload.build_payload(fs1),
            build_ledger_payload.build_payload(fs2),
        )

        # Removing the undocumented key entirely must not crash either.
        fs3 = _fact_sheet(projects=base_projects)
        del fs3["facts"]["steer_candidates"]
        build_ledger_payload.build_payload(fs3)  # no error

        # Undocumented per-project fields (flags/ruled_flags/git/files/
        # sessions/slug -- all real sarathi.py output, never read here) must
        # also be ignored.
        richer_project = dict(base_projects["p"])
        richer_project.update({
            "flags": ["dormant"],
            "ruled_flags": [{"flag": "dormant", "verdict": "parked", "decided": "2026-08-01",
                              "source": "x.md"}],
            "git": {"status": "ok", "last_commit": "2026-01-01", "dirty": 0},
            "files": {"status": "ok", "count": 3, "newest": "2026-01-01"},
            "sessions": {"status": "ok", "count": 1, "last_session": "2026-01-01"},
            "slug": "whatever",
        })
        fs4 = _fact_sheet(projects={"p": richer_project})
        self.assertEqual(
            build_ledger_payload.build_payload(fs1),
            build_ledger_payload.build_payload(fs4),
        )


class TestLedgerPayloadDeterminism(unittest.TestCase):
    """Criterion 10."""

    def test_payload_deterministic_same_input_same_output(self):
        projects = {
            "p": _project_entry(memory_entries=[
                _memory_entry(name="n1"), _memory_entry(name="n2", type_val="feedback"),
            ]),
        }
        fs = _fact_sheet(projects=projects)
        p1 = build_ledger_payload.build_payload(fs)
        p2 = build_ledger_payload.build_payload(fs)
        self.assertEqual(p1, p2)
        j1 = json.dumps(p1, sort_keys=True, ensure_ascii=False)
        j2 = json.dumps(p2, sort_keys=True, ensure_ascii=False)
        self.assertEqual(j1, j2)


class TestLedgerOrdering(unittest.TestCase):
    """Criteria 11-12."""

    def test_group_and_decision_ordering(self):
        projects = {
            "zeta": _project_entry(
                memory_entries=[_memory_entry(name="z1", type_val="project")],
                decisions_entries=[_decision(verdict="parked", decided="2026-07-01",
                                              source_file="d1.md")],
            ),
            "alpha": _project_entry(
                memory_entries=[_memory_entry(name="a1", type_val="project")],
                decisions_entries=[_decision(verdict="dead", decided="2026-07-15",
                                              source_file="d2.md")],
            ),
        }
        orphans = [
            _orphan_entry("slug-b", memory_entries=[_memory_entry(name="b1", type_val="project")]),
            _orphan_entry("slug-a", memory_entries=[_memory_entry(name="a-orphan",
                                                                    type_val="project")]),
        ]
        payload = build_ledger_payload.build_payload(
            _fact_sheet(projects=projects, orphans=orphans))

        project_group = next(g for g in payload["groups"] if g["type"] == "project")
        names = [e["name"] for e in project_group["entries"]]
        # project-key order (alpha before zeta), THEN orphan-list order as given (b before a)
        self.assertEqual(names, ["a1", "z1", "b1", "a-orphan"])

        decided_sources = [(d["source"], d["source_file"]) for d in payload["decisions"]]
        self.assertEqual(decided_sources, [("alpha", "d2.md"), ("zeta", "d1.md")])


class TestLedgerStats(unittest.TestCase):
    """Criterion 13."""

    def test_stats_counts_match_arrays(self):
        projects = {
            "p1": _project_entry(
                memory_entries=[_memory_entry(name="u", type_val="user"),
                                 _memory_entry(name="f", type_val="feedback")],
                decisions_entries=[_decision()],
            ),
            "p2": _project_entry(memory_entries=[_memory_entry(name="pr", type_val="project")]),
        }
        orphans = [_orphan_entry("s1", memory_entries=[_memory_entry(name="unt", type_val="weird")])]
        payload = build_ledger_payload.build_payload(
            _fact_sheet(projects=projects, orphans=orphans))

        total_from_groups = sum(len(g["entries"]) for g in payload["groups"])
        self.assertEqual(payload["stats"]["total_entries"], total_from_groups)
        for g in payload["groups"]:
            self.assertEqual(payload["stats"]["by_group"][g["type"]], len(g["entries"]))
        self.assertEqual(payload["stats"]["steering_decisions"], len(payload["decisions"]))


class TestLedgerCaveats(unittest.TestCase):
    """Criteria 14-15."""

    def test_caveat_added_for_failed_or_partial_source(self):
        projects = {
            "broken": _project_entry(memory_status="failed", memory_reason="2 files unparseable"),
            "partial": _project_entry(
                memory_entries=[_memory_entry(name="ok1")],
                memory_status="ok", memory_reason="partial: 1 unparseable",
            ),
            "clean": _project_entry(memory_entries=[_memory_entry(name="ok2")]),
        }
        payload = build_ledger_payload.build_payload(_fact_sheet(projects=projects))
        caveat_sources = {(c["source"], c["kind"], c["status"]) for c in payload["caveats"]}
        self.assertIn(("broken", "memory", "failed"), caveat_sources)
        self.assertIn(("partial", "memory", "ok"), caveat_sources)
        self.assertNotIn("clean", {c["source"] for c in payload["caveats"]})

    def test_caveat_added_for_unreadable_root(self):
        root = "/Users/alice/Projects"
        root_slug = build_ledger_payload.slug(os.path.normpath(root))
        orphan_slug = "{0}-gone".format(root_slug)
        roots_failed = {root: {"status": "failed", "reason": "permission denied", "projects": 0}}
        orphans = [_orphan_entry(orphan_slug, memory_entries=[_memory_entry(name="g1")])]
        payload = build_ledger_payload.build_payload(
            _fact_sheet(orphans=orphans, roots=roots_failed))
        root_caveats = [c for c in payload["caveats"] if c["kind"] == "root_unreadable"]
        self.assertEqual(len(root_caveats), 1)
        self.assertEqual(root_caveats[0]["source"], "gone")
        self.assertEqual(root_caveats[0]["source_kind"], "orphan")
        self.assertEqual(root_caveats[0]["status"], "failed")

        # An "empty" root is also unreadable-caveat-worthy; an "ok" root is not.
        roots_empty = {root: {"status": "empty", "reason": None, "projects": 0}}
        payload_empty = build_ledger_payload.build_payload(
            _fact_sheet(orphans=orphans, roots=roots_empty))
        self.assertEqual(
            len([c for c in payload_empty["caveats"] if c["kind"] == "root_unreadable"]), 1)

        roots_ok = {root: {"status": "ok", "reason": None, "projects": 1}}
        payload_ok = build_ledger_payload.build_payload(
            _fact_sheet(orphans=orphans, roots=roots_ok))
        self.assertEqual(
            len([c for c in payload_ok["caveats"] if c["kind"] == "root_unreadable"]), 0)


class TestLedgerTemplateStaticStructure(unittest.TestCase):
    """Criteria 16-20."""

    @classmethod
    def setUpClass(cls):
        cls.template = _read_ledger_template()

    def test_ledger_template_no_external_urls(self):
        self.assertNotIn("http://", self.template)
        self.assertNotIn("https://", self.template)

    def test_ledger_template_has_reduced_motion_media_query(self):
        self.assertIn("@media (prefers-reduced-motion: reduce)", self.template)

    def test_ledger_template_has_theme_aware_rules(self):
        self.assertIn("@media (prefers-color-scheme: dark)", self.template)
        self.assertIn('data-theme="dark"', self.template)

    def test_ledger_template_marker_present_exactly_once_in_id_script_block(self):
        self.assertEqual(self.template.count(render_report.MARKER), 1)
        marker_idx = self.template.index(render_report.MARKER)
        script_open = self.template.rindex(
            '<script type="application/json" id="sarathi-payload">', 0, marker_idx)
        script_close = self.template.index("</script>", marker_idx)
        self.assertLess(script_open, marker_idx)
        self.assertLess(marker_idx, script_close)

    def test_ledger_template_no_document_wrapper_tags(self):
        self.assertNotIn("<!DOCTYPE", self.template)
        self.assertNotIn("<html", self.template)
        self.assertNotIn("<head>", self.template)
        self.assertNotIn("<body>", self.template)

    def test_ledger_template_no_machine_specific_path(self):
        self.assertNotIn("/Users/", self.template)
        self.assertNotIn("/home/", self.template)


class TestRenderReportPyUnchanged(unittest.TestCase):
    """Criterion 21: render_report.py has zero diff in this story. Compared
    by content hash (not `git diff`, since this story's coder is barred from
    running any git command) against the fingerprint recorded above, taken
    from the SAR-04-shipped file before this story touched anything else."""

    def test_render_report_py_unchanged(self):
        with open(RENDER_REPORT_PATH, encoding="utf-8") as fh:
            source = fh.read()
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
        self.assertEqual(digest, RENDER_REPORT_PY_SHA256)


class TestLedgerPayloadExampleSchemaShape(unittest.TestCase):
    """Criterion 22, mirrors TestPayloadExampleSchemaShape's pattern exactly,
    pointed at the ledger template and this story's §6 pinned example."""

    def test_ledger_payload_example_matches_pinned_schema_shape(self):
        payload = PINNED_LEDGER_PAYLOAD_EXAMPLE
        self.assertIn("meta", payload)
        self.assertIn("stats", payload)
        self.assertIn("groups", payload)
        self.assertIn("decisions", payload)
        self.assertIn("caveats", payload)
        self.assertNotIn("voice", payload["meta"])
        types = [g["type"] for g in payload["groups"]]
        self.assertEqual(types, ["user", "feedback", "project", "reference", "untyped"])

    def test_ledger_payload_example_renders_without_error(self):
        out = render_report.render_fragment(_read_ledger_template(), PINNED_LEDGER_PAYLOAD_EXAMPLE)
        self.assertEqual(
            json.loads(_extract_injected_json(out)), PINNED_LEDGER_PAYLOAD_EXAMPLE)


class TestRenderStandaloneLedger(unittest.TestCase):
    """Criterion 23, mirrors test_render_report_cli_standalone_mode."""

    def test_render_standalone_ledger_title_and_wrapper(self):
        out = render_report.render_standalone(
            _read_ledger_template(), PINNED_LEDGER_PAYLOAD_EXAMPLE, "Sarathi — Memory Ledger")
        self.assertEqual(out.count("<!DOCTYPE html>"), 1)
        self.assertEqual(out.count("<head>"), 1)
        self.assertIn("<title>Sarathi — Memory Ledger</title>", out)
        fragment = render_report.render_fragment(
            _read_ledger_template(), PINNED_LEDGER_PAYLOAD_EXAMPLE)
        self.assertIn(fragment, out)


class TestRenderReportCliLedgerFile(unittest.TestCase):
    """CLI path parity, mirroring test_render_report_cli_writes_expected_file,
    pointed at the ledger template/payload."""

    def test_render_report_cli_writes_expected_ledger_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload_path = os.path.join(tmp, "payload.json")
            with open(payload_path, "w", encoding="utf-8") as fh:
                json.dump(PINNED_LEDGER_PAYLOAD_EXAMPLE, fh)
            out_path = os.path.join(tmp, "fragment.html")
            r = subprocess.run(
                [sys.executable, RENDER_REPORT_PATH,
                 "--template", LEDGER_TEMPLATE_PATH,
                 "--payload", payload_path,
                 "--out", out_path],
                capture_output=True, text=True,
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            with open(out_path, encoding="utf-8") as fh:
                cli_output = fh.read()
            direct_output = render_report.render_fragment(
                _read_ledger_template(), PINNED_LEDGER_PAYLOAD_EXAMPLE)
            self.assertEqual(cli_output, direct_output)


class TestBuildLedgerPayloadCLI(unittest.TestCase):
    """The build_ledger_payload.py CLI path -- --facts/--out mirror
    render_report.py's own --template/--payload/--out conventions."""

    def test_build_ledger_payload_cli_writes_expected_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            projects = {"p": _project_entry(memory_entries=[_memory_entry(name="n1")])}
            fs = _fact_sheet(projects=projects)
            facts_path = os.path.join(tmp, "facts.json")
            with open(facts_path, "w", encoding="utf-8") as fh:
                json.dump(fs, fh)
            out_path = os.path.join(tmp, "payload.json")
            r = subprocess.run(
                [sys.executable, os.path.join(MEMORY_SKILL_DIR, "build_ledger_payload.py"),
                 "--facts", facts_path, "--out", out_path],
                capture_output=True, text=True,
            )
            self.assertEqual(r.returncode, 0, r.stderr)
            with open(out_path, encoding="utf-8") as fh:
                cli_payload = json.load(fh)
            direct_payload = build_ledger_payload.build_payload(fs)
            self.assertEqual(cli_payload, direct_payload)


class TestMemorySkillFrontmatter(unittest.TestCase):
    """Criterion 32."""

    def test_skill_frontmatter_omits_ask_user_question(self):
        skill_path = os.path.join(REPO_ROOT, "skills", "memory", "SKILL.md")
        with open(skill_path, encoding="utf-8") as fh:
            text = fh.read()
        m = re.search(r"^allowed-tools:\s*(.+)$", text, re.MULTILINE)
        self.assertIsNotNone(m)
        tools = [t.strip() for t in m.group(1).split(",")]
        self.assertNotIn("AskUserQuestion", tools)
        self.assertIn("Bash", tools)
        self.assertIn("Read", tools)
        self.assertIn("Write", tools)
        self.assertIn("Artifact", tools)


class TestMemorySkillEnvironmentNeutral(unittest.TestCase):
    """Criterion 37: no machine-specific path in either shipped memory file."""

    def test_no_machine_specific_path_in_shipped_memory_files(self):
        for rel in ("skills/memory/SKILL.md", "skills/memory/ledger-template.html"):
            path = os.path.join(REPO_ROOT, rel)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            self.assertNotIn("/Users/", text, rel)
            self.assertNotIn("/home/", text, rel)


class TestLedgerPluginJsonVersionBump(unittest.TestCase):
    """Criterion 36, parallel to TestPluginManifests.test_plugin_json_valid
    above (already updated to 0.5.0 for this story)."""

    def test_plugin_json_version_bump(self):
        path = os.path.join(REPO_ROOT, ".claude-plugin", "plugin.json")
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data["version"], "0.5.0")


if __name__ == "__main__":
    unittest.main()
