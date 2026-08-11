"""Permanent guard: no personal user path in tracked source.

Two layers protect this. Here, a grep over tracked sources catches a
literal anyone pastes back in. In core/mode_json.py, a load-time check
rejects a bare /exp/mu2e/.../users/<name>/ in a mode spec, which covers
untracked specs this grep never sees.

wiki/ and docs/ are deliberately NOT scanned: they record what actually
happened, including who ran it, and rewriting that to hide a username would
be worse than leaving it.

A line that legitimately needs to name the pattern (a fixture using a
synthetic account name, a docstring describing the rule) opts out with the
`personal-path-ok:` pragma, in place, with a stated reason -- never a
file-level exemption. A file-level exemption blinds every other line in
that file, which is how a guard like this quietly stops guarding: it is
exactly what let a real, unexempted-by-pattern regex line in
core/mode_json.py go unchecked in an earlier version of this test.
"""
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCANNED = ("core", "graph", "tests", "mode_specs")

# `$` and `<` are excluded so `$USER` and `<them>` placeholders in docs and
# error messages do not match: a real account name can never start with them.
PERSONAL_PATH = re.compile(r"/exp/mu2e/(?:app|data)/users/[^/\s\"'}$<]+")

# A line may opt out only by SAYING SO, in place. File-level exemptions
# blind every other line in the file -- which is how a guard like this
# quietly stops guarding.
PRAGMA = "personal-path-ok:"


class TestNoHardcodedPaths(unittest.TestCase):
    def test_no_tracked_source_names_a_personal_user_area(self):
        tracked = subprocess.run(
            ["git", "ls-files", *SCANNED],
            cwd=str(ROOT), capture_output=True, text=True, check=True
        ).stdout.split()
        offenders = []
        for rel in tracked:
            f = ROOT / rel
            if not f.is_file():
                continue
            try:
                text = f.read_text(errors="ignore")
            except OSError:
                continue
            for i, line in enumerate(text.splitlines(), start=1):
                if PRAGMA in line:
                    continue
                if PERSONAL_PATH.search(line):
                    offenders.append(f"{rel}:{i}: {line.strip()[:100]}")
        self.assertEqual(
            offenders, [],
            msg="hardcoded personal path(s) reintroduced — route them "
                "through core/paths.py (REPO_ROOT / DATA_ROOT / "
                "ARTIFACT_ROOT / artifact()); a line that legitimately "
                "needs to name the pattern opts out with a "
                "'personal-path-ok: <reason>' pragma on that line, not a "
                "file-level exemption; see "
                "docs/superpowers/specs/2026-08-11-portable-paths-design.md"
                "\n  " + "\n  ".join(offenders))


if __name__ == "__main__":
    unittest.main()
