"""Shared temp-dir fixture helpers for the sarathi.py test suite.

Nothing here ever touches the real ~/.claude or ~/Projects — every helper
takes an explicit path (always inside a tempfile.TemporaryDirectory in the
calling test) and operates only on that path.
"""
import json
import os
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SARATHI_PATH = os.path.join(REPO_ROOT, "sarathi.py")

# Ensure `import sarathi` works for tests that need direct (non-subprocess)
# access to internal functions.
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import sarathi  # noqa: E402  (import after sys.path fix, by design)


def write_config(config_dir, project_roots, output_path, schema_version=None,
                  extra_keys=None, omit_keys=None):
    """Write <config_dir>/sarathi/config.json.

    `schema_version` defaults to `sarathi.CONFIG_SCHEMA_VERSION` (the
    current version) — and whenever the resolved version equals the
    current one, `voice="plain"` and `invoker=sys.executable` are filled in
    automatically, so a bare call produces a config `doctor` considers
    fully healthy end-to-end (config check "ok", not just `measure`
    working). This is what most of SAR-01's existing suite implicitly
    wants: "give me a working config, I only care what's downstream of it."

    Pass `schema_version=1` explicitly for a genuinely v0.1-shaped config
    (exactly the original three keys, no `voice`/`invoker` — the
    auto-added v2 keys are skipped whenever the resolved version isn't
    current, since a stale config shouldn't silently carry current-version
    keys it never asked for). Use `omit_keys` to still drop `voice`/
    `invoker` from an otherwise-current config (e.g. to build a "malformed
    v2" fixture, config missing just `invoker`); `extra_keys` to add an
    unknown key or override any key by name (extra_keys always wins, so it
    can also be used to force an intentionally-invalid value, e.g. a bad
    `voice`).
    """
    resolved_schema = (
        schema_version if schema_version is not None else sarathi.CONFIG_SCHEMA_VERSION
    )
    cfg = {
        "schema_version": resolved_schema,
        "project_roots": project_roots,
        "output_path": output_path,
    }
    if resolved_schema == sarathi.CONFIG_SCHEMA_VERSION:
        cfg["voice"] = "plain"
        cfg["invoker"] = sys.executable
    if omit_keys:
        for k in omit_keys:
            cfg.pop(k, None)
    if extra_keys:
        cfg.update(extra_keys)
    sarathi_dir = os.path.join(config_dir, "sarathi")
    os.makedirs(sarathi_dir, exist_ok=True)
    path = os.path.join(sarathi_dir, "config.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh)
    return path


def init_git_repo(path):
    os.makedirs(path, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True,
                    capture_output=True)


def git_commit_all(path, message, when_date):
    """Stage everything and commit with an explicit author/committer date
    (YYYY-MM-DD) so tests can control days_since() precisely."""
    ts = f"{when_date}T12:00:00"
    env = dict(os.environ)
    env["GIT_AUTHOR_DATE"] = ts
    env["GIT_COMMITTER_DATE"] = ts
    subprocess.run(["git", "add", "-A"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=sarathi-tests@example.com",
         "-c", "user.name=Sarathi Tests", "commit", "-q", "-m", message],
        cwd=path, check=True, capture_output=True, env=env,
    )


def write_file(path, content="hello\n"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
    return path


def make_session_file(config_dir, project_root, name="session-1.jsonl", content="{}\n"):
    sdir = os.path.join(config_dir, "projects", sarathi.slug(project_root))
    os.makedirs(sdir, exist_ok=True)
    path = os.path.join(sdir, name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
    return path


def make_memory_file(config_dir, project_root_or_slug, filename, frontmatter,
                      body="", is_slug=False):
    slug_val = project_root_or_slug if is_slug else sarathi.slug(project_root_or_slug)
    mdir = os.path.join(config_dir, "projects", slug_val, "memory")
    os.makedirs(mdir, exist_ok=True)
    fm_lines = "\n".join(f'{k}: "{v}"' for k, v in frontmatter.items())
    text = f"---\n{fm_lines}\n---\n{body}\n"
    path = os.path.join(mdir, filename)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def run_sarathi(args, config_dir=None, path_override=None, extra_env=None, cwd=None):
    """Invoke sarathi.py as a subprocess (the real CLI entry point), with a
    fully-controlled environment. config_dir sets CLAUDE_CONFIG_DIR;
    path_override replaces PATH entirely (used to simulate "git missing")."""
    env = os.environ.copy()
    if config_dir is not None:
        env["CLAUDE_CONFIG_DIR"] = config_dir
    if path_override is not None:
        env["PATH"] = path_override
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, SARATHI_PATH, *args],
        capture_output=True, text=True, env=env, cwd=cwd,
    )
