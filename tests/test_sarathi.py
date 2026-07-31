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
import json
import os
import re
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
    make_memory_file,
    make_session_file,
    run_sarathi,
    write_config,
    write_file,
)


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


if __name__ == "__main__":
    unittest.main()
