"""Permanent guard: no personal user path in tracked source.

Two layers protect this. Here, a grep over tracked sources catches a
literal anyone pastes back in. In core/mode_json.py, a load-time check
rejects a bare /exp/mu2e/.../users/<name>/ in a mode spec, which covers
untracked specs this grep never sees.

wiki/ and docs/ are deliberately NOT scanned: they record what actually
happened, including who ran it, and rewriting that to hide a username would
be worse than leaving it.
"""
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCANNED = ("core", "graph", "tests", "mode_specs")

# Matches ANY operator's personal area, not one username: a guard keyed on a
# single name would wave through the next person who hardcodes their own path,
# which is exactly the failure it exists to catch.
PERSONAL_PATH = re.compile(r"/exp/mu2e/(?:app|data)/users/[^/\s\"'}]+")

# Files that legitimately carry the pattern because they DEFINE, ENFORCE, or
# TEST it -- every entry below was verified to carry a generic placeholder
# (<them>, $USER, somebody, testuser), never a real operator's username.
EXEMPT = {
    "core/mode_json.py":
        "carries the load-time regex that REFUSES personal paths in mode specs",
    "core/paths.py":
        "verify()'s error message names the remediation command with a "
        "generic <them> placeholder, not a specific operator",
    "mode_specs/README.md":
        "documents the ${ARTIFACT} token's default resolution via $USER, "
        "not a personal literal",
    "tests/test_mode_json.py":
        "fixture proving mode_json.py rejects ANY bare personal absolute "
        "path (uses the synthetic name 'somebody', not a real account)",
    "tests/test_paths.py":
        "fixture for paths.py's $USER-driven resolution (uses the synthetic "
        "name 'testuser', not a real account)",
    "tests/test_no_hardcoded_paths.py":
        "this guard has to name the pattern it forbids",
}


class TestNoHardcodedPaths(unittest.TestCase):
    def test_no_tracked_source_names_a_personal_user_area(self):
        tracked = subprocess.run(
            ["git", "ls-files", *SCANNED],
            cwd=str(ROOT), capture_output=True, text=True, check=True
        ).stdout.split()
        offenders = []
        for rel in tracked:
            if rel in EXEMPT:
                continue
            f = ROOT / rel
            if not f.is_file():
                continue
            try:
                text = f.read_text(errors="ignore")
            except OSError:
                continue
            for i, line in enumerate(text.splitlines(), start=1):
                if PERSONAL_PATH.search(line):
                    offenders.append(f"{rel}:{i}: {line.strip()[:100]}")
        self.assertEqual(
            offenders, [],
            msg="hardcoded personal path(s) reintroduced — route them "
                "through core/paths.py (REPO_ROOT / DATA_ROOT / "
                "ARTIFACT_ROOT / artifact()); see "
                "docs/superpowers/specs/2026-08-11-portable-paths-design.md"
                "\n  " + "\n  ".join(offenders))


if __name__ == "__main__":
    unittest.main()
