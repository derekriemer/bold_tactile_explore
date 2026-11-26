"""Verify the dashed-lines integration and write a plain-text report.

    uv run python scripts/verify_dash.py             # writes plans/dash-trails-verification.txt
    uv run python scripts/verify_dash.py --baseline  # writes plans/dash-trails-baseline.txt

Runs ruff, the default test suite, and the golden tests (full Tilden builds compared with the
fingerprints in tests/fixtures/golden). Exits non-zero if anything fails.
"""

from __future__ import annotations

import argparse
import platform
import re
import subprocess
import sys
import time
from datetime import date
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGES = ["numpy", "scipy", "scikit-image", "skan", "trimesh", "manifold3d"]


def run(label: str, args: list[str]) -> dict:
    start = time.monotonic()
    proc = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=False)
    seconds = time.monotonic() - start
    out = (proc.stdout + proc.stderr).strip().splitlines()
    summary = next(
        (line for line in reversed(out) if re.search(r"\d+ (passed|failed|error)", line)),
        out[-1] if out else "",
    )
    return {
        "label": label,
        "ok": proc.returncode == 0,
        "seconds": seconds,
        "summary": summary.strip("= "),
        "failures": [line for line in out if line.startswith(("FAILED", "ERROR"))],
        "golden": _golden_reports(out),
    }


def _golden_reports(lines: list[str]) -> list[str]:
    """The comparison reports that golden assertion failures print."""
    keep, inside = [], False
    for line in lines:
        text = line.removeprefix("E").strip()
        if text.startswith("Golden comparison:"):
            inside = True
        if inside:
            if not text or text.startswith(("assert", "+", "tests/")):
                inside = False
                continue
            keep.append(text)
    return keep


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--baseline", action="store_true", help="write the baseline file")
    args = parser.parse_args()

    py = [sys.executable, "-m"]
    checks = [
        run("Lint (ruff check)", [*py, "ruff", "check"]),
        run("Default test suite", [*py, "pytest", "-q", "-p", "no:warnings"]),
        run(
            "Golden tests (Tilden builds and the dash-trails 1.0.0 oracle)",
            [*py, "pytest", "-q", "-p", "no:warnings", "-m", "golden", "-rA"],
        ),
    ]
    ok = all(c["ok"] for c in checks)
    kind = "baseline" if args.baseline else "verification"
    lines = [
        f"Dashed lines {kind} report, {date.today().isoformat()}",
        "",
        f"Result: {'all checks passed' if ok else 'FAILED'}",
        "",
        "Checks",
    ]
    for c in checks:
        lines.append(
            f"- {c['label']}: {'pass' if c['ok'] else 'FAIL'}, {c['seconds']:.0f} s. {c['summary']}"
        )
        lines += [f"  - {f}" for f in c["failures"]]
        lines += [f"  {g}" for g in c["golden"]]
    lines += ["", "Environment", f"- Python {platform.python_version()} on {platform.system()}"]
    lines += [f"- {name} {version(name)}" for name in PACKAGES]
    text = "\n".join(lines) + "\n"
    out = ROOT / "plans" / f"dash-trails-{kind}.txt"
    out.write_text(text, encoding="utf-8")
    print(text)
    print(f"Written to {out.relative_to(ROOT)}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
