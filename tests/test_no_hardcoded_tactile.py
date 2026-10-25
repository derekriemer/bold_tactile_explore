"""Invariant 1: no hard-coded tactile numbers in style, analyzer, describe and sampler code."""

import ast
import re
from pathlib import Path

SRC = Path(__file__).parent.parent / "src" / "tactile_terrain"
ALLOWLIST = Path(__file__).parent / "tactile_literal_allowlist.txt"
SCANNED = ["styles.py", "compose.py", "analyzers", "describe.py", "sampler.py"]
ALLOWED_INTS = {-1, 0, 1, 2}


def load_allowlist(path=ALLOWLIST):
    entries = []
    if not path.exists():
        return entries
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("  #")[0].strip()
        if line and not line.startswith("#"):
            module, _, pattern = line.partition(":")
            entries.append((module, re.compile(pattern)))
    return entries


def _files(root: Path, targets):
    for target in targets:
        p = root / target
        if p.is_dir():
            yield from sorted(p.rglob("*.py"))
        elif p.is_file():
            yield p


def scan(root: Path, targets=SCANNED, allowlist=()):
    """Return 'module:line: literal' for each disallowed numeric literal."""
    found = []
    for path in _files(root, targets):
        rel = path.relative_to(root).as_posix()
        source = path.read_text(encoding="utf-8")
        lines = source.splitlines()
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.Constant) or isinstance(node.value, bool):
                continue
            value = node.value
            bad = isinstance(value, float) or (isinstance(value, int) and value not in ALLOWED_INTS)
            if not bad:
                continue
            text = lines[node.lineno - 1]
            if any(m == rel and p.search(text) for m, p in allowlist):
                continue
            found.append(f"{rel}:{node.lineno}: {value!r}")
    return found


def test_tactile_modules_have_no_hardcoded_numbers():
    assert scan(SRC, allowlist=load_allowlist()) == []


def test_scan_passes_on_missing_or_empty_modules(tmp_path):
    assert scan(tmp_path) == []
    (tmp_path / "styles.py").write_text("")
    assert scan(tmp_path) == []


def test_scan_catches_a_planted_literal(tmp_path):
    (tmp_path / "styles.py").write_text("WIDTH = 1.6\nCOUNT = 7\nOK = 2\n")
    found = scan(tmp_path)
    assert len(found) == 2
    assert "1.6" in found[0] and "7" in found[1]


def test_allowlist_exempts_matching_line(tmp_path):
    (tmp_path / "styles.py").write_text("FLANK = 45\n")
    entry = [("styles.py", re.compile(r"FLANK"))]
    assert scan(tmp_path, allowlist=entry) == []
