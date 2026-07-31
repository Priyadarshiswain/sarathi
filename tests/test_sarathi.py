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
    make_decision_file,
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
        self.assertEqual(data["version"], "0.3.0")

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


if __name__ == "__main__":
    unittest.main()
