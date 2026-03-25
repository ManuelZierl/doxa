"""
End-to-end CLI fixture tests.

Each subdirectory under fixtures/ contains:
  input.doxa   - piped line-by-line into the doxa CLI
  expected.txt - expected stdout output (banner stripped, \r\n normalised)

The test discovers all fixture directories automatically, so adding a new
fixture requires only dropping two files in a new folder.
"""

from __future__ import annotations

import sys
from io import StringIO
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# Import the CLI main function directly instead of relying on installed package
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from doxa.cli.main import main  # noqa: E402


def _strip_banner(text: str) -> str:
    """Remove the decorative header block printed on every CLI start.

    The banner occupies the first 4 lines (box-top, title, box-bottom,
    blank line).  Everything from the first ``doxa>`` prompt onward is
    kept verbatim.
    """
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.startswith("doxa>"):
            return "".join(lines[i:])
    return text


def _normalise(text: str) -> str:
    """Normalise CR+LF to LF and strip a trailing newline so comparisons
    are not sensitive to a final blank line in the expected file."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    return text.rstrip("\n")


def _collect_fixtures() -> list[tuple[str, Path]]:
    if not FIXTURES_DIR.exists():
        return []
    results = []
    for category in sorted(p for p in FIXTURES_DIR.iterdir() if p.is_dir()):
        for fixture in sorted(p for p in category.iterdir() if p.is_dir()):
            if (fixture / "input.doxa").exists() and (
                fixture / "expected.txt"
            ).exists():
                label = f"{category.name}/{fixture.name}"
                results.append((label, fixture))
    return results


@pytest.mark.parametrize(
    "name,fixture_dir", _collect_fixtures(), ids=[n for n, _ in _collect_fixtures()]
)
def test_fixture(name: str, fixture_dir: Path, monkeypatch, capsys) -> None:
    # utf-8-sig strips the UTF-8 BOM (0xEF 0xBB 0xBF) if present, so both
    # BOM and non-BOM files are handled transparently.
    input_text = (fixture_dir / "input.doxa").read_text(encoding="utf-8-sig")
    expected_raw = (fixture_dir / "expected.txt").read_text(encoding="utf-8-sig")

    # Mock stdin with the input text
    monkeypatch.setattr("sys.stdin", StringIO(input_text))

    # Mock sys.argv to pass --tmp flag
    monkeypatch.setattr("sys.argv", ["doxa", "--tmp"])

    # Run the CLI main function
    try:
        main()
    except SystemExit:
        # CLI may call sys.exit(), which is expected
        pass

    # Capture the output
    captured = capsys.readouterr()
    actual = _normalise(_strip_banner(captured.out))
    expected = _normalise(expected_raw)

    assert actual == expected, (
        f"\n--- fixture: {name} ---\nEXPECTED:\n{expected}\n\nACTUAL:\n{actual}\n"
    )
