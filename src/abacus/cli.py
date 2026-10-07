"""Command line: `abacus <button> '<json>'`, `abacus run FILE`, `abacus mcp`, `abacus buttons`."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys

from pathlib import Path

from . import budget, registry, sandbox  # noqa: F401  (sandbox registers the `run` button)
from .algo import roles as _roles, surface as _surface  # noqa: F401  (register the algo buttons)
from .algo.loader import AlgoImportError
from .library import surface as _library_surface  # noqa: F401  (register the library buttons)

STUBS = ("mint",)
COMMANDS = ("run", "mcp", "buttons", "algo", "link", "index") + STUBS


def button_names() -> list[str]:
    registry.load_all()
    return [b.name for b in registry.all_buttons()]


def _emit(ev, pretty: bool, full: bool) -> None:
    print(json.dumps(ev.to_dict(full=full), indent=2 if pretty else None, ensure_ascii=False))


# What a library command raises for bad input or a bad file: one line on stderr, exit 2, no traceback.
# (AlgoImportError is not a ValueError; MetaError is.)
_LIBRARY_ERRORS = (AlgoImportError, ValueError, OSError, sqlite3.Error)


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
            "       abacus algo new|lint|show|list|run ...\n"
            "       abacus mcp | buttons | link | mint | index\n\n"
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
            with open(a.input, encoding="utf-8-sig") as f:
                text = f.read()
        else:
            text = a.json if a.json is not None else "{}"
        inp = json.loads(text)
    except (OSError, ValueError) as e:
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
        with open(a.file, encoding="utf-8-sig") as f:
            code = f.read()
    except (OSError, ValueError) as e:
        return _err(f"cannot read {a.file}: {e}")
    _emit(budget.call("run", {"code": code}, time_s=a.time), a.pretty, a.full)
    return 0


_TEMPLATE = '''"""{id}: replace this with one line saying what the problem is."""
META = {{
    "id": "{id}",
    "title": "TITLE",
    "summary": "One sentence on what this family of problems asks.",
    "roles": ["generate", "compute", "check"],
    "tags": [],
    "techniques": [],
    "answer": {{"format": "integer", "range": [2, 198]}},
    "knobs": {{"hi": {{"int": [2, 99]}}}},
    "requires": [],
    "notes": "",
}}

from abacus.evidence import Evidence, make_compare


def compute(params):
    return params["a"] + params["b"]


def check(params, proposed):
    computed = compute(params)
    ev = Evidence(button="check", result=proposed == computed, method="exhaustive",
                  scope="a + b recomputed directly")
    ev.compare = make_compare(proposed, computed)
    return ev


def generate(rng, knobs):
    hi = knobs.get("hi", 99)
    p = {{"a": rng.randint(1, hi), "b": rng.randint(1, hi)}}
    return {{"params": p, "statement": f"Find ${{p['a']}} + {{p['b']}}$.", "answer": compute(p)}}
'''


def _json_arg(text, what):
    try:
        v = json.loads(text)
    except ValueError as e:
        raise ValueError(f"bad {what}: {e}") from None
    if not isinstance(v, dict):
        raise ValueError(f"bad {what}: the JSON must be an object")
    return v


def _oneline(e: BaseException) -> str:
    return " ".join(str(e).split()) or type(e).__name__


def _dump(obj, pretty: bool) -> None:
    print(json.dumps(obj, indent=2 if pretty else None, ensure_ascii=False))


def _looks_like_path(arg: str) -> bool:
    """`algo show` takes a file or a library id. A file is anything with a separator or a .py ending, or
    that exists; the rest is an id, so a typo gets the id error rather than "no such file"."""
    return arg.endswith(".py") or "/" in arg or "\\" in arg or Path(arg).is_file()


def _algo(rest: list[str]) -> int:
    from .algo.lint import DEFAULT_K
    from .algo.loader import AlgoImportError, MetaError, _ID_RE, algo_hash, load_algo
    from .algo.roles import RUN_ROLES, run_role
    from .library import index, surface

    p = argparse.ArgumentParser(prog="abacus algo")
    sub = p.add_subparsers(dest="sub", required=True)
    n = sub.add_parser("new", help="write a template algorithm file")
    n.add_argument("id")
    n.add_argument("--out", metavar="DIR_OR_FILE", default=None)
    li = sub.add_parser("lint", help="report what a file does")
    li.add_argument("file")
    li.add_argument("-k", type=int, default=DEFAULT_K)
    _common(li)
    sh = sub.add_parser("show", help="print META and hash; for a library id, also its links and usage count")
    sh.add_argument("file", metavar="ID_OR_FILE")
    _common(sh)
    se = sub.add_parser("search", help="search the library; prints a JSON list")
    se.add_argument("query", nargs="?", default="", help="words that must all match id, title, summary, tags, techniques")
    se.add_argument("--role")
    se.add_argument("--tag")
    se.add_argument("--technique")
    se.add_argument("--format", dest="answer_format", metavar="FORMAT", help="the answer format, such as integer")
    se.add_argument("--linked", metavar="SPEC", help="a consumer ('osmosis') or one full target")
    se.add_argument("--unlinked", action="store_true", help="only algorithms with no link at all")
    se.add_argument("--sort", choices=index.SORTS, default="id")
    se.add_argument("--limit", type=int, default=50)
    se.add_argument("--pretty", action="store_true", help="indent the JSON output")
    ls = sub.add_parser("list", help="list the algorithm files in a directory")
    ls.add_argument("dir", nargs="?", default=None)
    ru = sub.add_parser("run", help="run one role")
    ru.add_argument("file")
    ru.add_argument("role", choices=RUN_ROLES)
    ru.add_argument("--seed", type=int, default=None)
    ru.add_argument("--knobs", default="{}")
    ru.add_argument("--args", default="{}")
    _common(ru)
    try:
        a = p.parse_args(rest)
    except SystemExit as e:
        return int(e.code or 0)

    if a.sub == "new":
        if not _ID_RE.match(a.id):
            return _err(f"bad id {a.id!r}: use lowercase dotted slugs, such as 'nt.power-mod'")
        out = Path(a.out) if a.out else Path.cwd()
        if out.suffix != ".py":
            out = out / (a.id.replace(".", "_").replace("-", "_") + ".py")
        if out.exists():
            return _err(f"{out} already exists; not overwriting")
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(_TEMPLATE.format(id=a.id), encoding="utf-8", newline="\n")
        except OSError as e:
            return _err(f"cannot write {out}: {e}")
        print(str(out))
        return 0
    if a.sub == "lint":
        # Through the budget, so a role that hangs is killed in its child process instead of hanging the terminal.
        _emit(budget.call("algo_lint", {"path": str(Path(a.file).resolve()), "k": a.k}, time_s=a.time), a.pretty, True)
        return 0
    if a.sub == "show":
        if not _looks_like_path(a.file):
            try:
                _dump(surface.show_record(a.file), a.pretty)
            except _LIBRARY_ERRORS as e:
                return _err(_oneline(e))
            return 0
        try:
            algo = load_algo(a.file)
        except (AlgoImportError, MetaError) as e:
            return _err(str(e))
        print(json.dumps({"hash": algo.hash, "path": str(algo.path), "meta": algo.meta},
                         indent=2 if a.pretty else None, ensure_ascii=False))
        return 0
    if a.sub == "search":
        try:
            _dump(index.search(a.query, role=a.role, tag=a.tag, technique=a.technique,
                               answer_format=a.answer_format, linked=a.linked, unlinked=a.unlinked,
                               sort=a.sort, limit=a.limit), a.pretty)
        except _LIBRARY_ERRORS as e:
            return _err(_oneline(e))
        return 0
    if a.sub == "list":
        from .config import get_config
        d = Path(a.dir) if a.dir else get_config().library
        if not d.is_dir():
            print(f"(no algorithm directory at {d})")
            return 0
        for f in sorted(d.rglob("*.py")):
            if f.name.startswith("_"):
                continue
            try:
                m = load_algo(f).meta
                print("\t".join([m["id"], m["title"], algo_hash(f), str(f)]))
            except (AlgoImportError, MetaError) as e:
                print("\t".join(["?", f"(not loadable: {str(e).splitlines()[0]})", algo_hash(f), str(f)]))
        return 0
    try:  # run
        knobs, args = _json_arg(a.knobs, "--knobs"), _json_arg(a.args, "--args")
    except ValueError as e:
        return _err(str(e))
    _emit(run_role(a.file, a.role, args=args, seed=a.seed, knobs=knobs, time_s=a.time), a.pretty, a.full)
    return 0


def _parse(p: argparse.ArgumentParser, rest: list[str]):
    """Parse, turning argparse's exit into a return code; None (and the code) when it exited."""
    try:
        return p.parse_args(rest), None
    except SystemExit as e:
        return None, int(e.code or 0)


def _link(rest: list[str]) -> int:
    from .library import links

    p = argparse.ArgumentParser(prog="abacus link", description="Ties between algorithms and items in a consumer.")
    sub = p.add_subparsers(dest="sub", required=True)
    ad = sub.add_parser("add", help="tie an algorithm to a target")
    ad.add_argument("algo")
    ad.add_argument("target", help="<consumer>:<kind>:<id>, such as osmosis:q:6b1f0a")
    ad.add_argument("--kind", required=True, metavar="{" + ",".join(links.KINDS) + "}")
    ad.add_argument("--hash", dest="algo_hash", metavar="H", help="the algorithm hash the item was made from")
    ad.add_argument("--seed", type=int, default=None)
    ad.add_argument("--batch", default=None)
    rm = sub.add_parser("rm", help="remove every link between an algorithm and a target")
    rm.add_argument("algo")
    rm.add_argument("target")
    ls = sub.add_parser("list", help="list links, in file order")
    ls.add_argument("--algo", default=None)
    ls.add_argument("--consumer", default=None, help="a consumer prefix: osmosis, or osmosis:q")
    fi = sub.add_parser("find", help="every link to exactly this target")
    fi.add_argument("target")
    for q in (ad, rm, ls, fi):
        q.add_argument("--pretty", action="store_true", help="indent the JSON output")
    a, code = _parse(p, rest)
    if a is None:
        return code
    try:
        if a.sub == "add":
            out = links.add(a.algo, a.target, a.kind, algo_hash=a.algo_hash, seed=a.seed, batch=a.batch)
        elif a.sub == "rm":
            out = {"removed": links.rm(a.algo, a.target)}
        elif a.sub == "list":
            out = links.list_links(algo=a.algo, consumer=a.consumer)
        else:
            out = links.find(a.target)
    except _LIBRARY_ERRORS as e:
        return _err(_oneline(e))
    _dump(out, a.pretty)
    return 0


def _index(rest: list[str]) -> int:
    from .library import index

    p = argparse.ArgumentParser(prog="abacus index", description="The derived search index of the library.")
    sub = p.add_subparsers(dest="sub", required=True)
    rb = sub.add_parser("rebuild", help="rebuild the index from the files; prints the problems found, as JSON")
    rb.add_argument("--pretty", action="store_true", help="indent the JSON output")
    a, code = _parse(p, rest)
    if a is None:
        return code
    try:
        problems = index.rebuild()
    except _LIBRARY_ERRORS as e:
        return _err(_oneline(e))
    _dump(problems, a.pretty)
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
    if cmd == "algo":
        return _algo(rest)
    if cmd == "link":
        return _link(rest)
    if cmd == "index":
        return _index(rest)
    if cmd in STUBS:
        print(f"abacus {cmd}: not built yet")
        return 2
    if cmd == "run":
        return _run_file(rest)
    return _run_button(cmd, rest)


if __name__ == "__main__":
    raise SystemExit(main())
