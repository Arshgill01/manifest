"""Tool layer: path jail, manifest enforcement + warden.block, edits, pytest parsing."""

from pathlib import Path

import pytest

from harness.log import EventLog
from harness.smoke import FIX, ROOT_CAUSE, make_package
from harness.tools import FAKE_HOME, ToolError, Tools, WardenBlock, glob_to_regex, matches_any, parse_pytest

GROWN = {"read": ["**"], "write": ["src/**"], "commands": ["python -m pytest"], "network": False}


@pytest.fixture
def pkg(tmp_path):
    return make_package(tmp_path / "tinyledger-01")


def types(log):
    return [e["type"] for e in log.events]


def test_globs():
    assert matches_any("src/a/b.py", ["src/**"])
    assert not matches_any("tests/test_a.py", ["src/**"])
    assert matches_any("anything/at/all", ["**"])
    assert matches_any("a.py", ["**/*.py"]) and matches_any("x/y/a.py", ["**/*.py"])
    assert not glob_to_regex("src/*.py").match("src/sub/a.py")


def test_list_and_read(pkg):
    t = Tools(pkg)
    files = t.list_files()
    assert "src/tinyledger/money.py" in files and "TASK.md" in files
    assert not any("__pycache__" in f for f in files)
    whole = t.read_file("src/tinyledger/money.py")
    assert "def to_cents" in whole
    assert t.read_file("src/tinyledger/money.py", 4, 4).startswith("def to_cents")
    with pytest.raises(ToolError):
        t.read_file("src/nope.py")


@pytest.mark.parametrize("path", ["../outside.txt", "/etc/hosts", "~/.ssh/id_ed25519", "src/../../x"])
def test_path_jail_blocks_and_logs(pkg, path):
    log = EventLog()
    with pytest.raises(WardenBlock):
        Tools(pkg, None, log, skill="baseline").read_file(path)
    block = next(e for e in log.events if e["type"] == "warden.block")
    assert block["skill"] == "baseline" and "outside the task dir" in block["reason"]
    assert log.events[-1]["type"] == "tool.call" and log.events[-1]["ok"] is False


def test_symlink_escape_blocked(pkg, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("s3cret")
    (pkg / "src" / "link.txt").symlink_to(secret)
    with pytest.raises(WardenBlock):
        Tools(pkg).read_file("src/link.txt")


def test_manifest_blocks_test_writes(pkg):
    log = EventLog()
    t = Tools(pkg, GROWN, log, skill="trace-to-source")
    with pytest.raises(WardenBlock):
        t.edit_file("tests/test_money.py", "1200", "1")
    assert "1200" in (pkg / "tests/test_money.py").read_text()
    b = [e for e in log.events if e["type"] == "warden.block"][0]
    assert b["skill"] == "trace-to-source" and b["attempted"] == "write tests/test_money.py"
    assert t.edit_file("src/tinyledger/money.py", *FIX)["ok"]


def test_manifest_read_globs(pkg):
    t = Tools(pkg, {"read": ["src/**"], "write": [], "commands": []})
    assert all(f.startswith("src/") for f in t.list_files())
    with pytest.raises(WardenBlock):
        t.read_file("TASK.md")


def test_manifest_command_prefixes(pkg):
    log = EventLog()
    t = Tools(pkg, GROWN, log)
    assert t.bash("python -m pytest -q -p no:cacheprovider")["exitCode"] == 1  # suite fails, but it ran
    for cmd in ["ls", "python -m pytest; cat /etc/passwd", "python -m pytest | head", "curl http://x"]:
        with pytest.raises(WardenBlock):
            t.bash(cmd)
    with pytest.raises(WardenBlock):
        Tools(pkg, {"read": ["**"], "write": [], "commands": []}).run_tests()
    assert types(log).count("warden.block") == 4


def test_bash_baseline_is_jailed(pkg):
    t = Tools(pkg)
    out = t.bash("echo hi && pwd")
    assert out["ok"] and "hi" in out["output"] and str(pkg.resolve()) in out["output"]
    assert t.bash("python -c 'import os; print(os.environ[\"HOME\"])'")["output"].strip() == str(FAKE_HOME)
    for cmd in ["cat ~/.ssh/id_ed25519", "cat /etc/passwd", "cat ../x", "wget http://x", "echo $HOME"]:
        with pytest.raises(WardenBlock):
            t.bash(cmd)


def test_edit_file_semantics(pkg):
    t = Tools(pkg)
    miss = t.edit_file("src/tinyledger/money.py", "rounding=ROUND_SIDEWAYS", "x")
    assert not miss["ok"] and "not found" in miss["error"]
    dup = t.edit_file("src/tinyledger/money.py", "cents", "x")
    assert not dup["ok"] and "matches" in dup["error"]
    ok = t.edit_file("src/tinyledger/money.py", *FIX)
    assert ok == {"ok": True, "path": "src/tinyledger/money.py", "error": None, "replacements": 1}
    assert t.edit_file("src/tinyledger/new.py", "", "X = 1\n")["ok"]
    assert (pkg / "src/tinyledger/new.py").read_text() == "X = 1\n"


def test_run_tests_parses_failures(pkg):
    log = EventLog()
    t = Tools(pkg, None, log)
    r = t.run_tests()
    assert (r["passed"], r["failed"], r["ok"]) == (3, 3, False)
    tests = {f["test"] for f in r["failures"]}
    assert tests == {"tests/test_invoice.py::test_subtotal_rounds_half_up",
                     "tests/test_invoice.py::test_tax_rounds_half_up",
                     "tests/test_invoice.py::test_total_formatted"}
    f = next(f for f in r["failures"] if f["test"].endswith("half_up") and "subtotal" in f["test"])
    assert f["error"].startswith("AssertionError: assert 267 == 268")
    assert f["frames"] == [{"file": "tests/test_invoice.py", "line": 9, "function": "test_subtotal_rounds_half_up"}]
    assert str(pkg.resolve()) not in r["output"]
    assert log.events[-1]["summary"] == "3 failed, 3 passed"

    sel = t.run_tests("tests/test_money.py")
    assert (sel["passed"], sel["failed"], sel["ok"]) == (2, 0, True)
    with pytest.raises(ToolError):
        t.run_tests("--rootdir=/")

    t.edit_file(ROOT_CAUSE["file"], *FIX)
    assert t.run_tests()["ok"]
    assert not list(pkg.rglob("__pycache__")), "tool runs must not litter the task dir (tests/ is compared byte-for-byte)"


def test_run_tests_deep_frames_and_syntax_errors(pkg):
    t = Tools(pkg)
    money = pkg / "src/tinyledger/money.py"
    money.write_text(money.read_text().replace("scaled = Decimal", "scaled = 1 / 0 * Decimal"))
    r = t.run_tests()
    frames = next(f for f in r["failures"] if "subtotal_rounds" in f["test"])["frames"]
    assert [fr["function"] for fr in frames] == ["test_subtotal_rounds_half_up", "subtotal_cents", "<genexpr>", "to_cents"]
    assert frames[-1]["file"] == "src/tinyledger/money.py"

    money.write_text(money.read_text().replace("def to_cents(amount)", "def to_cents(amount"))
    r = t.run_tests()
    assert r["errors"] == 2 and r["failed"] == 2 and r["passed"] == 0
    inner = r["failures"][0]["frames"][-1]
    assert inner == {"file": "src/tinyledger/money.py", "line": 4, "function": "<syntax>"}
    assert all(not fr["file"].startswith(("/", "<")) for f in r["failures"] for fr in f["frames"])


def test_parse_pytest_handles_class_and_param_ids(tmp_path):
    out = "\n".join([
        "F.F",
        "=================================== FAILURES ===================================",
        "___________________________ TestBucket.test_refill[3] ___________________________",
        "tests/test_b.py:8: in test_refill",
        "    assert b.take(3)",
        "src/rk/bucket.py:12: in take",
        "    return self._ok(n)",
        "E   ValueError: bad",
        "________________________________ test_other _________________________________",
        "tests/test_c.py:2: in test_other",
        "E   assert 1 == 2",
        "=========================== short test summary info ============================",
        "FAILED tests/test_b.py::TestBucket::test_refill[3] - ValueError: bad",
        "FAILED tests/test_c.py::test_other - assert 1 == 2",
        "2 failed, 1 passed in 0.02s",
    ])
    r = parse_pytest(out, tmp_path)
    assert (r["passed"], r["failed"]) == (1, 2)
    assert r["failures"][0]["test"] == "tests/test_b.py::TestBucket::test_refill[3]"
    assert r["failures"][0]["frames"][-1] == {"file": "src/rk/bucket.py", "line": 12, "function": "take"}
    assert r["failures"][1]["error"] == "assert 1 == 2"
