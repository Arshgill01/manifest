"""A hand-made 2-module failing package for harness smoke runs and tests (not part of the task suite).

`tinyledger`: invoice.py calls money.py, and money.to_cents rounds down instead of half-up, so the
failures surface in test_invoice.py while the root cause is one call down (deep-call-chain shape).

    uv run python -m harness.smoke [--mode baseline|manifest]   # copies it to .manifest/work and runs it live
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

FILES = {
    "TASK.md": "The test suite is failing. Make it pass without editing tests.\n",
    "conftest.py": (
        "import sys\n"
        "from pathlib import Path\n\n"
        "sys.path.insert(0, str(Path(__file__).parent / \"src\"))\n"
    ),
    "src/tinyledger/__init__.py": "from .invoice import Invoice\n",
    "src/tinyledger/money.py": '''from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal


def to_cents(amount) -> int:
    """Convert a currency amount to integer cents, rounding half up."""
    scaled = Decimal(str(amount)) * 100
    return int(scaled.quantize(Decimal("1"), rounding=ROUND_DOWN))


def format_cents(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}${cents // 100}.{cents % 100:02d}"
''',
    "src/tinyledger/invoice.py": '''from .money import format_cents, to_cents


class Invoice:
    def __init__(self, tax_rate: float = 0.0):
        self.tax_rate = tax_rate
        self.lines: list[tuple[str, float, int]] = []

    def add(self, description: str, unit_price: float, qty: int = 1) -> "Invoice":
        self.lines.append((description, unit_price, qty))
        return self

    def subtotal_cents(self) -> int:
        return sum(to_cents(price * qty) for _, price, qty in self.lines)

    def tax_cents(self) -> int:
        return to_cents(self.subtotal_cents() / 100 * self.tax_rate)

    def total_cents(self) -> int:
        return self.subtotal_cents() + self.tax_cents()

    def total(self) -> str:
        return format_cents(self.total_cents())
''',
    "tests/test_money.py": '''from tinyledger.money import format_cents, to_cents


def test_whole_amounts():
    assert to_cents(12) == 1200


def test_format_cents():
    assert format_cents(1234) == "$12.34"
    assert format_cents(-5) == "-$0.05"
''',
    "tests/test_invoice.py": '''from tinyledger import Invoice


def test_subtotal_simple():
    assert Invoice().add("widget", 10.0, 2).subtotal_cents() == 2000


def test_subtotal_rounds_half_up():
    assert Invoice().add("pen", 2.675).subtotal_cents() == 268


def test_tax_rounds_half_up():
    assert Invoice(tax_rate=0.0825).add("book", 10.0).tax_cents() == 83


def test_total_formatted():
    assert Invoice(tax_rate=0.0825).add("book", 10.0).add("pen", 2.675).total() == "$13.73"
''',
}
ROOT_CAUSE = {"file": "src/tinyledger/money.py", "function": "to_cents", "line": 7}
FIX = ("rounding=ROUND_DOWN", "rounding=ROUND_HALF_UP")


def make_package(dest: Path) -> Path:
    dest = Path(dest)
    for rel, text in FILES.items():
        p = dest / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return dest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--mode", choices=["baseline", "manifest"], default="baseline")
    ap.add_argument("--max-steps", type=int, default=12)
    ap.add_argument("--max-seconds", type=int, default=120)
    a = ap.parse_args(argv)
    from harness.log import ROOT
    from harness.run import main as run_main
    src = make_package(ROOT / ".manifest" / "work" / "smoke-src" / "tinyledger-01")
    return run_main([str(src), "--mode", a.mode, "--label", f"smoke-{a.mode}",
                     "--max-steps", str(a.max_steps), "--max-seconds", str(a.max_seconds)])


if __name__ == "__main__":
    sys.exit(main())
