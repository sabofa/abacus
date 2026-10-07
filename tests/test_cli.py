import json
import subprocess
import sys
from pathlib import Path

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


def test_mint_needs_a_subcommand(capsys):
    assert main(["mint"]) == 2
    assert "make" in capsys.readouterr().err


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


FIX = Path(__file__).parent / "fixtures" / "algos"
ALGO = str(FIX / "nt_power_mod.py")


def test_algo_new(tmp_path, capsys):
    assert main(["algo", "new", "demo.add", "--out", str(tmp_path)]) == 0
    f = tmp_path / "demo_add.py"
    assert f.is_file() and str(f) in capsys.readouterr().out
    assert main(["algo", "new", "demo.add", "--out", str(tmp_path)]) == 2  # no overwrite
    assert main(["algo", "new", "Bad Id", "--out", str(tmp_path)]) == 2
    from abacus.algo.lint import lint
    assert all(c["status"] == "ok" for c in lint(f, k=3).result["checks"])


def test_algo_lint(capsys):
    assert main(["algo", "lint", ALGO, "-k", "2"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["button"] == "algo_lint"
    assert [c["check"] for c in out["result"]["checks"]][0] == "header"


def test_algo_show(capsys):
    assert main(["algo", "show", ALGO]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["meta"]["id"] == "nt.power-mod" and len(out["hash"]) == 8
    assert main(["algo", "show", "no/such.py"]) == 2


def test_algo_list(capsys, tmp_path):
    assert main(["algo", "list", str(FIX)]) == 0
    out = capsys.readouterr().out
    assert "nt.power-mod	a to the b mod m	" in out
    assert main(["algo", "list", str(tmp_path / "missing")]) == 0
    assert "no algorithm directory" in capsys.readouterr().out


def test_algo_run(capsys):
    args = json.dumps({"params": {"a": 3, "b": 4, "m": 5}})
    assert main(["algo", "run", ALGO, "compute", "--args", args]) == 0
    assert json.loads(capsys.readouterr().out)["result"] == 1
    assert main(["algo", "run", ALGO, "generate", "--seed", "7", "--knobs", '{"m": 9}']) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["seed"] == 7 and out["result"]["params"]["m"] == 9
    assert main(["algo", "run", ALGO, "compute", "--args", "[1]"]) == 2


def test_algo_run_args_never_collide_with_run_role_keywords(capsys):
    # these used to be splatted into run_role(**args) and crash with a TypeError
    stray = {"seed": 1, "role": "x", "knobs": {}, "time_s": 3, "in_process": True, "args": {}}
    args = dict(stray, params={"a": 3, "b": 4, "m": 5})
    assert main(["algo", "run", ALGO, "compute", "--args", json.dumps(args)]) == 0
    assert json.loads(capsys.readouterr().out)["result"] == 1
    assert main(["algo", "run", ALGO, "generate", "--seed", "4", "--args", '{"seed": 1}']) == 0
    assert json.loads(capsys.readouterr().out)["seed"] == 4


def test_algo_run_generate_without_seed_records_one(capsys):
    assert main(["algo", "run", ALGO, "generate"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert isinstance(out["seed"], int) and out["result"]["seed"] == out["seed"]


def test_algo_files_that_exit_at_import_do_not_kill_show_list_or_lint(tmp_path, capsys):
    f = tmp_path / "quits.py"
    f.write_text("import sys\nsys.exit(4)\n", encoding="utf-8")
    assert main(["algo", "show", str(f)]) == 2
    assert "SystemExit" in capsys.readouterr().err
    assert main(["algo", "list", str(tmp_path)]) == 0
    assert "not loadable" in capsys.readouterr().out
    assert main(["algo", "lint", str(f)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["result"]["checks"][0]["status"] == "problem" and "SystemExit" in out["result"]["checks"][0]["detail"]


def test_algo_lint_runs_under_the_time_budget_so_a_hung_role_is_killed(capsys):
    assert main(["algo", "lint", str(FIX / "lint_hang.py"), "-k", "2", "--time", "2"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["complete"] is False and out["budget"]["stopped"] is True


def test_algo_lint_default_k_is_twenty(capsys):
    assert main(["algo", "lint", str(FIX / "one_off.py")]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["result"]["k"] == 20 and out["complete"] is True


def test_buttons_lists_algo_run_and_lint_but_not_algo_role(capsys):
    assert main(["buttons"]) == 0
    text = capsys.readouterr().out
    assert "algo_run\t" in text and "algo_lint\t" in text and "algo_role" not in text


# ---- output that is not cp1252, and an algorithm that prints at import ----------

def _env(library, **extra):
    import os
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONIOENCODING", "PYTHONUTF8")}
    env["ABACUS_LIBRARY"] = str(library)
    env.update(extra)
    return env


def _algo_source(algo_id, title, prelude=""):
    meta = {"id": algo_id, "title": title, "summary": "Sums two numbers.", "roles": ["compute"],
            "answer": {"format": "integer"}}
    return f"{prelude}META = {meta!r}\n\n\ndef compute(params):\n    return 42\n"


def test_cli_prints_utf8_when_stdout_is_a_pipe(tmp_path):
    lib = tmp_path / "lib"
    (lib / "zz").mkdir(parents=True)
    (lib / "zz" / "sigma.py").write_text(_algo_source("zz.sigma", "Σ ≤ →"), encoding="utf-8")
    # PYTHONIOENCODING and PYTHONUTF8 are unset (see _env), so a Windows pipe would default to cp1252.
    for argv in (["algo", "search"], ["algo", "show", "zz.sigma"]):
        r = subprocess.run([sys.executable, "-m", "abacus", *argv], capture_output=True, timeout=120,
                           env=_env(lib))
        assert r.returncode == 0, r.stderr.decode("utf-8", "replace")
        text = r.stdout.decode("utf-8")  # must be utf-8, not cp1252
        assert "Σ ≤ →" in text
        json.loads(text)


def test_main_survives_a_stdout_without_reconfigure(monkeypatch, capsys):
    import io
    monkeypatch.setattr(sys, "stdout", io.StringIO())  # a plain StringIO has no reconfigure()
    monkeypatch.setattr(sys, "stderr", io.StringIO())
    assert main(["buttons"]) == 0


def test_algo_run_keeps_stdout_clean_when_the_file_prints_at_import(tmp_path):
    lib = tmp_path / "lib"
    (lib / "zz").mkdir(parents=True)
    f = lib / "zz" / "chatty.py"
    f.write_text(_algo_source("zz.chatty", "Chatty", prelude="print('hello from import')\n"), encoding="utf-8")
    r = subprocess.run([sys.executable, "-m", "abacus", "algo", "run", str(f), "compute"],
                       capture_output=True, text=True, timeout=120, env=_env(lib))
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["result"] == 42  # stdout is the JSON and nothing else
    assert "hello from import" in r.stderr


@pytest.mark.parametrize("body, printed", [
    ("print('hello from compute')", "hello from compute"),
    ("sys.stdout.write('x-no-newline')", "x-no-newline"),  # glued onto the JSON if it reached fd 1
    ("os.write(1, b'raw fd one write')", "raw fd one write"),  # a C-level / subprocess style write
])
def test_algo_run_keeps_stdout_clean_when_a_role_prints_while_it_runs(tmp_path, body, printed):
    lib = tmp_path / "lib"
    (lib / "zz").mkdir(parents=True)
    f = lib / "zz" / "chatty_run.py"
    meta = {"id": "zz.chatty_run", "title": "Chatty run", "summary": "Prints while it runs.",
            "roles": ["compute"], "answer": {"format": "integer"}}
    f.write_text(f"import os\nimport sys\n\nMETA = {meta!r}\n\n\ndef compute(params):\n    {body}\n    return 42\n",
                 encoding="utf-8")
    r = subprocess.run([sys.executable, "-m", "abacus", "algo", "run", str(f), "compute"],
                       capture_output=True, text=True, timeout=120, env=_env(lib))
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["result"] == 42  # stdout is the JSON and nothing else
    assert printed in r.stderr
