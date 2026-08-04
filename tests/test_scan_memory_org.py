"""Tests for skills/memory/scan_memory_org.py (SAR-10).

Each detector gets a positive, a negative, and where the story demands it
an edge fixture. Two fixtures exist specifically to pin owner bans:
signal-3 must stay dead (a body mentioning another project's *name* is
not contamination) and 3e must never read dates out of prose (the
domain-expiry false positive, measured live 2026-08-05).
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..",
                                "skills", "memory"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import scan_memory_org as scan  # noqa: E402
import sarathi  # noqa: E402


def entry(name="e", typ="project", desc="a description", body="",
          session=None):
    fm = ["---", "name: %s" % name, "description: %s" % desc,
          "metadata:", "  type: %s" % typ]
    if session:
        fm.append("  originSessionId: %s" % session)
    fm += ["---", "", body]
    return "\n".join(fm)


class Fixture(unittest.TestCase):
    """A temp config-dir + temp projects root the detectors run against."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.root = os.path.join(self.tmp, "Projects")
        self.config_dir = os.path.join(self.tmp, "claude")
        os.makedirs(self.root)
        os.makedirs(os.path.join(self.config_dir, "projects"))

    def add_project(self, name):
        p = os.path.join(self.root, name)
        os.makedirs(p, exist_ok=True)
        return p

    def mdir(self, project_path):
        s = scan.slug(project_path)
        d = os.path.join(self.config_dir, "projects", s, "memory")
        os.makedirs(d, exist_ok=True)
        return d, s

    def write(self, mdir, fname, text, mtime=None):
        path = os.path.join(mdir, fname)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        if mtime is not None:
            os.utime(path, (mtime, mtime))
        return path

    def run_scan(self, gap_days=60):
        return scan.scan(self.config_dir, [self.root], gap_days=gap_days)

    def by_detector(self, doc, name):
        return [f for f in doc["findings"] if f["detector"] == name]


class TestFamilyPlacement(Fixture):
    def test_foreign_path_fires_and_names_target(self):
        self.add_project("alpha")
        self.add_project("beta")
        d, _ = self.mdir(os.path.join(self.root, "alpha"))
        self.write(d, "note.md", entry(body="see %s/beta for the plugin"
                                       % self.root))
        hits = self.by_detector(self.run_scan(), "foreign_path")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["target"], "beta")
        self.assertEqual(hits[0]["basis"], "observation")
        self.assertTrue(hits[0]["evidence"]["cited_dir_exists"])

    def test_tilde_cited_paths_fire_and_repeats_dedupe(self):
        """Measured live 2026-08-05: entries cite ~/Projects/X while the
        config holds the expanded root — both forms must match, and five
        citations of the same project are ONE finding."""
        self.add_project("alpha")
        self.add_project("beta")
        d, _ = self.mdir(os.path.join(self.root, "alpha"))
        old_home = os.environ.get("HOME")
        os.environ["HOME"] = self.tmp  # so ~/Projects == self.root
        self.addCleanup(lambda: os.environ.update(HOME=old_home)
                        if old_home else os.environ.pop("HOME", None))
        self.write(d, "note.md", entry(
            body="see ~/Projects/beta and again ~/Projects/beta. and "
                 "also %s/beta a third time" % self.root))
        hits = self.by_detector(self.run_scan(), "foreign_path")
        self.assertEqual(len(hits), 1)  # tilde+expanded+dot forms: ONE finding
        self.assertEqual(hits[0]["target"], "beta")

    def test_own_path_is_not_contamination(self):
        self.add_project("alpha")
        d, _ = self.mdir(os.path.join(self.root, "alpha"))
        self.write(d, "note.md", entry(body="lives at %s/alpha"
                                       % self.root))
        self.assertEqual(self.by_detector(self.run_scan(),
                                          "foreign_path"), [])

    def test_signal3_stays_dead_name_mentions_are_not_findings(self):
        """Owner ban 2026-08-04: an entry that merely *names* another
        project (uses it as a tool) produces nothing."""
        self.add_project("alpha")
        self.add_project("beta")
        d, _ = self.mdir(os.path.join(self.root, "alpha"))
        self.write(d, "note.md", entry(
            body="beta beta beta beta — we use beta's tooling constantly"))
        doc = self.run_scan()
        self.assertEqual([f for f in doc["findings"]
                          if f["family"] == "placement"], [])

    def test_wikilink_demand_resolves_cross_folder(self):
        self.add_project("alpha")
        self.add_project("beta")
        da, _ = self.mdir(os.path.join(self.root, "alpha"))
        db, _ = self.mdir(os.path.join(self.root, "beta"))
        self.write(da, "note.md", entry(body="follow [[house-rule]]"))
        self.write(db, "house-rule.md", entry(name="house-rule"))
        doc = self.run_scan()
        demand = self.by_detector(doc, "wikilink_demand")
        self.assertEqual(len(demand), 1)
        self.assertEqual(demand[0]["evidence"]["resolves_in"], ["beta"])
        self.assertEqual(self.by_detector(doc, "dangling_wikilink"), [])

    def test_orphaned_folder_with_rename_candidates(self):
        self.add_project("renamed-project")  # exists, has no memory folder
        gone = os.path.join(self.root, "old-name")
        d, _ = self.mdir(gone)  # memory folder for a dir that doesn't exist
        self.write(d, "note.md", entry())
        hits = self.by_detector(self.run_scan(), "orphaned_folder")
        self.assertEqual(len(hits), 1)
        self.assertIn("renamed-project",
                      hits[0]["evidence"]["rename_candidates_without_memory"])


class TestFamilyDuplication(Fixture):
    def test_same_basename_identical_vs_drifted(self):
        self.add_project("alpha")
        self.add_project("beta")
        da, _ = self.mdir(os.path.join(self.root, "alpha"))
        db, _ = self.mdir(os.path.join(self.root, "beta"))
        self.write(da, "shared.md", entry(name="shared"))
        self.write(db, "shared.md", entry(name="shared"))
        self.write(da, "plan.md", entry(name="plan", body="v1"))
        self.write(db, "plan.md", entry(name="plan", body="v2"))
        hits = {f["entry"]: f["evidence"]["state"]
                for f in self.by_detector(self.run_scan(), "same_basename")}
        self.assertEqual(hits, {"shared.md": "identical",
                                "plan.md": "drifted"})

    def test_organize_bookkeeping_files_are_not_corpus(self):
        """§9.4 records are excluded like MEMORY.md — same-day organize
        files across folders must not fire same_basename (or anything)."""
        self.add_project("alpha")
        self.add_project("beta")
        da, _ = self.mdir(os.path.join(self.root, "alpha"))
        db, _ = self.mdir(os.path.join(self.root, "beta"))
        self.write(da, "sarathi-organize-2026-08-05.md", "no frontmatter")
        self.write(db, "sarathi-organize-2026-08-05.md", "different text")
        doc = self.run_scan()
        self.assertEqual(doc["findings"], [])
        self.assertEqual(doc["meta"]["entry_count"], 0)

    def test_unique_basenames_produce_nothing(self):
        self.add_project("alpha")
        d, _ = self.mdir(os.path.join(self.root, "alpha"))
        self.write(d, "only.md", entry())
        self.assertEqual(self.by_detector(self.run_scan(),
                                          "same_basename"), [])


class TestFamilyHygiene(Fixture):
    def test_index_drift_all_three_shapes(self):
        self.add_project("alpha")
        d, _ = self.mdir(os.path.join(self.root, "alpha"))
        self.write(d, "listed.md", entry(name="listed"))
        self.write(d, "unlisted.md", entry(name="unlisted"))
        self.write(d, "MEMORY.md",
                   "# Memory index\n\n- [L](listed.md) — x\n"
                   "- [Ghost](ghost.md) — gone\n")
        doc = self.run_scan()
        self.assertEqual(
            self.by_detector(doc, "unindexed_entries")[0]["evidence"],
            {"unindexed": ["unlisted.md"]})
        self.assertEqual(
            self.by_detector(doc, "dangling_index_lines")[0]["evidence"],
            {"dangling": ["ghost.md"]})

        self.add_project("beta")
        d2, _ = self.mdir(os.path.join(self.root, "beta"))
        self.write(d2, "solo.md", entry(name="solo"))
        self.assertEqual(
            self.by_detector(self.run_scan(), "no_index")[0]["evidence"],
            {"unindexed": ["solo.md"]})

    def test_frontmatter_lint_and_decision_description_exemption(self):
        self.add_project("alpha")
        d, _ = self.mdir(os.path.join(self.root, "alpha"))
        self.write(d, "bare.md", "just prose, no frontmatter\n")
        self.write(d, "weird.md", entry(typ="banana"))
        self.write(d, "sarathi-decision-alpha-2026-08-05.md",
                   "---\nname: sarathi-decision-alpha-2026-08-05\n"
                   "description: \"\"\ntype: sarathi-decision\n"
                   "verdict: dead\ndecided: 2026-08-05\n---\n")
        hits = {f["entry"]: f["evidence"]["problems"]
                for f in self.by_detector(self.run_scan(),
                                          "frontmatter_lint")}
        self.assertIn("bare.md", hits)
        self.assertEqual(hits["weird.md"], ["unknown type 'banana'"])
        # Ruling B: decision files may have empty descriptions.
        self.assertNotIn("sarathi-decision-alpha-2026-08-05.md", hits)

    def test_provenance_lost_vs_present(self):
        self.add_project("alpha")
        d, s = self.mdir(os.path.join(self.root, "alpha"))
        sid = "0123abcd-0123-abcd-0123-abcdef012345"
        self.write(d, "lost.md", entry(session=sid))
        sid2 = "9999abcd-0123-abcd-0123-abcdef012345"
        self.write(d, "kept.md", entry(session=sid2))
        open(os.path.join(self.config_dir, "projects", s,
                          sid2 + ".jsonl"), "w").close()
        hits = self.by_detector(self.run_scan(), "lost_provenance")
        self.assertEqual([f["entry"] for f in hits], ["lost.md"])

    def test_silent_memory_uses_mtime_never_prose_dates(self):
        """The measured 3e false positive, pinned: a future date in prose
        (domain expiry) must not count as memory activity."""
        p = self.add_project("alpha")
        subprocess.run(["git", "-C", p, "init", "-q"], check=True)
        open(os.path.join(p, "f"), "w").close()
        env = dict(os.environ, GIT_AUTHOR_DATE="2026-07-01T00:00:00",
                   GIT_COMMITTER_DATE="2026-07-01T00:00:00",
                   GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        subprocess.run(["git", "-C", p, "add", "."], check=True, env=env)
        subprocess.run(["git", "-C", p, "commit", "-q", "-m", "x"],
                       check=True, env=env)
        d, _ = self.mdir(p)
        import calendar
        old = calendar.timegm((2026, 1, 1, 0, 0, 0))
        self.write(d, "note.md",
                   entry(body="domain expires 2027-06-28, watch out"),
                   mtime=old)
        hits = self.by_detector(self.run_scan(gap_days=60), "silent_memory")
        self.assertEqual(len(hits), 1)  # commit July, mtime January: fires
        self.assertGreater(hits[0]["evidence"]["gap_days"], 60)
        # Sanity: prose date 2027 did NOT suppress the finding.

    def test_silent_memory_quiet_when_within_threshold(self):
        p = self.add_project("alpha")
        subprocess.run(["git", "-C", p, "init", "-q"], check=True)
        # No commits at all -> no commit date -> no finding.
        d, _ = self.mdir(p)
        self.write(d, "note.md", entry())
        self.assertEqual(self.by_detector(self.run_scan(),
                                          "silent_memory"), [])

    def test_declared_supersession_flags_linked_target(self):
        self.add_project("alpha")
        d, _ = self.mdir(os.path.join(self.root, "alpha"))
        self.write(d, "old.md", entry(
            body="Superseded as live state by [[new-plan]]."))
        self.write(d, "self.md", entry(
            body="v9 supersedes the v8 flow below."))
        hits = {f["entry"]: f["evidence"]
                for f in self.by_detector(self.run_scan(),
                                          "declared_supersession")}
        self.assertTrue(hits["old.md"]["names_other_entry"])
        self.assertEqual(hits["old.md"]["linked_target"], "new-plan")
        self.assertFalse(hits["self.md"]["names_other_entry"])

    def test_rent_table_arithmetic(self):
        self.add_project("alpha")
        d, _ = self.mdir(os.path.join(self.root, "alpha"))
        self.write(d, "a.md", "x" * 400)
        doc = self.run_scan()
        row = doc["rent"]["folders"][0]
        self.assertEqual(row["bytes"], 400)
        self.assertEqual(row["approx_tokens"], 100)
        self.assertEqual(row["share_pct"], 100.0)


class TestDeterminismAndContract(Fixture):
    def _populate(self):
        self.add_project("alpha")
        self.add_project("beta")
        da, _ = self.mdir(os.path.join(self.root, "alpha"))
        db, _ = self.mdir(os.path.join(self.root, "beta"))
        self.write(da, "plan.md", entry(name="plan", body="v1"), mtime=1e9)
        self.write(db, "plan.md", entry(name="plan", body="v2"), mtime=1e9)
        self.write(da, "note.md", entry(
            body="see %s/beta and [[nowhere]]" % self.root), mtime=1e9)

    def test_byte_identical_output_on_unchanged_corpus(self):
        self._populate()
        a = json.dumps(self.run_scan(), sort_keys=True)
        b = json.dumps(self.run_scan(), sort_keys=True)
        self.assertEqual(a, b)

    def test_corpus_hash_changes_when_corpus_changes(self):
        self._populate()
        h1 = self.run_scan()["meta"]["corpus_hash"]
        da, _ = self.mdir(os.path.join(self.root, "alpha"))
        self.write(da, "new.md", entry(name="new"))
        self.assertNotEqual(h1, self.run_scan()["meta"]["corpus_hash"])

    def test_every_finding_carries_the_contract_fields(self):
        self._populate()
        for f in self.run_scan()["findings"]:
            for key in ("id", "family", "detector", "basis", "home",
                        "fix_class", "evidence"):
                self.assertIn(key, f)
            self.assertIn(f["basis"], {"observation", "convention"})
            self.assertIn(f["family"],
                          {"placement", "duplication", "hygiene"})

    def test_banned_detectors_do_not_exist(self):
        """Lifecycle classification and mention-counting are owner-banned
        (2026-08-04). Nothing in the module may reintroduce them."""
        src = open(scan.__file__.rstrip("c")).read()
        for banned in ("completed", "in_progress", "in-progress",
                       "acted_on", "mention_count"):
            self.assertNotIn("detector\", \"%s" % banned, src)


class TestDecisionFilenameCompat(unittest.TestCase):
    """SAR-09 C: both filename shapes are decision files, forever."""

    def test_both_shapes_match(self):
        for name in ("sarathi-decision-2026-08-01.md",
                     "sarathi-decision-2026-08-01-2.md",
                     "sarathi-decision-EmailOrganiser-2026-08-05.md",
                     "sarathi-decision-ai-103-labs-2026-08-05.md",
                     "sarathi-decision-ai-103-labs-2026-08-05-2.md"):
            self.assertTrue(sarathi.DECISION_FILENAME_RE.match(name), name)
            self.assertTrue(scan.DECISION_FILENAME_RE.match(name), name)

    def test_non_decision_names_do_not_match(self):
        for name in ("sarathi-decision.md", "decision-2026-08-01.md",
                     "sarathi-decision-2026-08.md", "note.md"):
            self.assertFalse(sarathi.DECISION_FILENAME_RE.match(name), name)
            self.assertFalse(scan.DECISION_FILENAME_RE.match(name), name)

    def test_regexes_stay_in_sync(self):
        self.assertEqual(sarathi.DECISION_FILENAME_RE.pattern,
                         scan.DECISION_FILENAME_RE.pattern)


if __name__ == "__main__":
    unittest.main()
