import json
import subprocess
import sys

import pytest

from abacus import registry
from abacus.cli import main


def test_unknown_button_exits_2(capsys):
    assert main(["no_such_button", "{}"]) == 2
    assert "unknown button" in capsys.readouterr().err


def test_bad_json_exits_2(capsys):
    capsys.readouterr()
    from abacus import sandbox  # noqa: F401
    # `run` is the file command, so use a registered non-command button for the JSON path
    from tests import _budget_buttons  # noqa: F401
    assert main(["t_seeded", "{not json"]) == 2
    assert "bad input" in capsys.readouterr().err
    assert main(["t_seeded", "[1]"]) == 2


def test_missing_input_file_exits_2(capsys):
    from tests import _budget_buttons  # noqa: F401
    assert main(["t_seeded", "--input", "no/such/file.json"]) == 2


@pytest.mark.parametrize("stub", ["algo", "link", "mint", "index"])
def test_stubs(stub, capsys):
    assert main([stub]) == 2
    assert "not built yet" in capsys.readouterr().out


def test_buttons_lists_run(capsys):
    assert main(["buttons"]) == 0
    assert "run\t" in capsys.readouterr().out
    assert "run" in [b.name for b in registry.all_buttons()]


def test_run_file_subprocess(tmp_path):
    f = tmp_path / "t.py"
    f.write_text("print(2+2)\n6*7\n", encoding="utf-8")
    r = subprocess.run([sys.executable, "-m", "abacus", "run", str(f)], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    ev = json.loads(r.stdout)
    assert ev["button"] == "run" and ev["method"] == "timed" and ev["complete"] is True
    assert ev["result"]["stdout"].strip() == "4" and ev["result"]["value"] == 42
    assert ev["scope"] == "ran the given code once"


def test_input_file_with_bom(tmp_path, capsys):
    from tests import _budget_buttons  # noqa: F401
    f = tmp_path / "in.json"
    f.write_bytes(b"\xef\xbb\xbf{}")
    assert main(["t_seeded", "--input", str(f)]) == 0


def test_input_and_run_file_invalid_bytes_exit_2(tmp_path, capsys):
    from tests import _budget_buttons  # noqa: F401
    f = tmp_path / "bad.bin"
    f.write_bytes(b"\xff\xfe\x00\xc3(")
    assert main(["t_seeded", "--input", str(f)]) == 2
    assert main(["run", str(f)]) == 2
    assert "abacus:" in capsys.readouterr().err
