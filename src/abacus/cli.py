"""Command line: `abacus <button> '<json>'`, `abacus run FILE`, `abacus mcp`, `abacus buttons`."""
from __future__ import annotations

import argparse
import json
import sys

from . import budget, registry, sandbox  # noqa: F401  (sandbox registers the `run` button)

STUBS = ("algo", "link", "mint", "index")
COMMANDS = ("run", "mcp", "buttons") + STUBS


def button_names() -> list[str]:
    registry.load_all()
    return [b.name for b in registry.all_buttons()]


def _emit(ev, pretty: bool, full: bool) -> None:
    print(json.dumps(ev.to_dict(full=full), indent=2 if pretty else None, ensure_ascii=False))


def _err(msg: str) -> int:
    print(f"abacus: {msg}", file=sys.stderr)
    return 2


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--pretty", action="store_true", help="indent the JSON output")
    p.add_argument("--full", action="store_true", help="do not cap the examples")
    p.add_argument("--time", type=float, default=None, metavar="SECONDS", help="time budget")


def _top_help() -> str:
    return ("usage: abacus <button> '<json>' [--input FILE] [--pretty] [--full] [--time S]\n"
            "       abacus run FILE [--time S]\n"
            "       abacus mcp | buttons | algo | link | mint | index\n\n"
            "Buttons: " + (", ".join(n for n in button_names()) or "(none)") + "\n")


def _run_button(name: str, rest: list[str]) -> int:
    p = argparse.ArgumentParser(prog=f"abacus {name}")
    p.add_argument("json", nargs="?", help="the input, as a JSON object")
    p.add_argument("--input", metavar="FILE", help="read the JSON input from FILE")
    _common(p)
    a = p.parse_args(rest)
    try:
        registry.get(name)
    except KeyError as e:
        return _err(e.args[0])
    try:
        if a.input:
            with open(a.input, encoding="utf-8") as f:
                text = f.read()
        else:
            text = a.json if a.json is not None else "{}"
        inp = json.loads(text)
    except (OSError, json.JSONDecodeError) as e:
        return _err(f"bad input: {e}")
    if not isinstance(inp, dict):
        return _err("bad input: the JSON must be an object")
    _emit(budget.call(name, inp, time_s=a.time), a.pretty, a.full)
    return 0


def _run_file(rest: list[str]) -> int:
    p = argparse.ArgumentParser(prog="abacus run")
    p.add_argument("file")
    _common(p)
    a = p.parse_args(rest)
    try:
        with open(a.file, encoding="utf-8") as f:
            code = f.read()
    except OSError as e:
        return _err(f"cannot read {a.file}: {e}")
    _emit(budget.call("run", {"code": code}, time_s=a.time), a.pretty, a.full)
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(_top_help())
        return 0 if argv else 2
    cmd, rest = argv[0], argv[1:]
    if cmd == "buttons":
        button_names()
        for b in registry.all_buttons():
            print(f"{b.name}\t{b.description}")
        return 0
    if cmd == "mcp":
        from .mcp_server import serve
        serve()
        return 0
    if cmd in STUBS:
        print(f"abacus {cmd}: not built yet")
        return 2
    if cmd == "run":
        return _run_file(rest)
    return _run_button(cmd, rest)


if __name__ == "__main__":
    raise SystemExit(main())
