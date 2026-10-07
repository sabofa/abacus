"""Load an algorithm file, validate its META, and hash it (spec 05 s2, s6)."""
from __future__ import annotations

import hashlib
import importlib.util
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

ROLES = ("compute", "check", "generate", "solution", "demo", "hand_space")
ANSWER_FORMATS = ("integer", "rational", "expression", "choice", "tuple", "set", "text")
KNOB_TYPES = ("int", "float", "choice", "bool")
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*(\.[a-z0-9][a-z0-9_-]*)*$")
_NONWORD = re.compile(r"\W")
_REQUIRED = ("id", "title", "summary", "roles", "answer")


class MetaError(ValueError):
    """A bad META. `.problems` lists every problem found, not just the first."""

    def __init__(self, problems: list[str], path: str | None = None):
        self.problems = list(problems)
        self.path = path
        head = f"bad META in {path}" if path else "bad META"
        super().__init__(head + ":\n" + "\n".join(f"  - {p}" for p in self.problems))


class AlgoImportError(Exception):
    """The file could not be imported. The message carries the Python error verbatim."""


@dataclass
class LoadedAlgo:
    meta: dict
    module: ModuleType
    path: Path
    hash: str


def algo_hash(path) -> str:
    data = Path(path).read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(data).hexdigest()[:8]


def _is_num(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _is_int(x: Any) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def _str_list(meta: dict, key: str, problems: list[str]) -> list[str]:
    v = meta.get(key, [])
    if not isinstance(v, list) or not all(isinstance(i, str) and i.strip() for i in v):
        problems.append(f"{key}: must be a list of non-empty strings")
        return []
    return list(v)


def _check_knob(name: str, spec: Any, problems: list[str]) -> None:
    if not isinstance(spec, dict):
        problems.append(f"knobs.{name}: must be a dict such as {{'int': [lo, hi]}}")
        return
    kinds = [k for k in spec if k in KNOB_TYPES]
    extra = [k for k in spec if k not in KNOB_TYPES and k != "pattern_knob"]
    if len(kinds) != 1:
        problems.append(f"knobs.{name}: needs exactly one of {list(KNOB_TYPES)}, found {kinds or 'none'}")
        return
    if extra:
        problems.append(f"knobs.{name}: unknown keys {extra}")
    kind, v = kinds[0], spec[kinds[0]]
    if kind in ("int", "float"):
        check = _is_int if kind == "int" else _is_num
        if not (isinstance(v, (list, tuple)) and len(v) == 2 and all(check(i) for i in v)):
            problems.append(f"knobs.{name}.{kind}: must be [lo, hi] of {kind}s")
        elif v[0] > v[1]:
            problems.append(f"knobs.{name}.{kind}: lo {v[0]} is above hi {v[1]}")
    elif kind == "choice":
        if not isinstance(v, (list, tuple)) or not v:
            problems.append(f"knobs.{name}.choice: must be a non-empty list")
    elif v is not True and v is not None:
        problems.append(f"knobs.{name}.bool: must be true or null (the value is ignored)")
    if "pattern_knob" in spec:
        if not isinstance(spec["pattern_knob"], bool):
            problems.append(f"knobs.{name}.pattern_knob: must be a boolean")
        elif spec["pattern_knob"] and kind != "int":
            problems.append(f"knobs.{name}.pattern_knob: only an int knob can be a pattern knob")


def validate_meta(meta: Any, path: str | None = None) -> dict:
    """Return a normalised copy of META (defaults filled) or raise MetaError listing every problem."""
    problems: list[str] = []
    if not isinstance(meta, dict):
        raise MetaError([f"META must be a dict, got {type(meta).__name__}"], path)
    for k in _REQUIRED:
        if k not in meta:
            problems.append(f"{k}: missing (required)")
    known = set(_REQUIRED) | {"tags", "techniques", "knobs", "requires", "notes"}
    unknown = sorted(k for k in meta if k not in known)
    if unknown:
        problems.append(f"unknown keys: {unknown}")

    if "id" in meta and not (isinstance(meta["id"], str) and _ID_RE.match(meta["id"])):
        problems.append("id: must be lowercase dotted slugs, such as 'nt.power-mod'")
    for k in ("title", "summary"):
        if k in meta and not (isinstance(meta[k], str) and meta[k].strip()):
            problems.append(f"{k}: must be a non-empty string")
    if "roles" in meta:
        r = meta["roles"]
        if not isinstance(r, list) or not r or not all(isinstance(i, str) for i in r):
            problems.append("roles: must be a non-empty list of role names")
        else:
            bad = [i for i in r if i not in ROLES]
            if bad:
                problems.append(f"roles: unknown {bad}; known: {list(ROLES)}")
            if len(set(r)) != len(r):
                problems.append("roles: duplicate entries")
    tags = _str_list(meta, "tags", problems)
    techniques = _str_list(meta, "techniques", problems)
    requires = _str_list(meta, "requires", problems)

    ans = meta.get("answer")
    if "answer" in meta:
        if not isinstance(ans, dict):
            problems.append("answer: must be a dict with a 'format' (and optional 'range')")
        else:
            if ans.get("format") not in ANSWER_FORMATS:
                problems.append(f"answer.format: must be one of {list(ANSWER_FORMATS)}, got {ans.get('format')!r}")
            if "range" in ans:
                rg = ans["range"]
                if not (isinstance(rg, (list, tuple)) and len(rg) == 2 and all(_is_num(i) for i in rg)):
                    problems.append("answer.range: must be [lo, hi] numbers")
                elif rg[0] > rg[1]:
                    problems.append(f"answer.range: lo {rg[0]} is above hi {rg[1]}")
            extra = sorted(k for k in ans if k not in ("format", "range"))
            if extra:
                problems.append(f"answer: unknown keys {extra}")

    knobs = meta.get("knobs") or {}
    if not isinstance(knobs, dict):
        problems.append("knobs: must be a dict (it may be empty)")
        knobs = {}
    else:
        for name, spec in knobs.items():
            if not (isinstance(name, str) and name.isidentifier()):
                problems.append(f"knobs: name {name!r} must be a Python identifier")
            else:
                _check_knob(name, spec, problems)
    notes = meta.get("notes", "")
    if not isinstance(notes, str):
        problems.append("notes: must be a string")
        notes = ""
    if problems:
        raise MetaError(problems, path)
    return {"id": meta["id"], "title": meta["title"], "summary": meta["summary"],
            "roles": list(meta["roles"]), "tags": tags, "techniques": techniques,
            "answer": dict(ans), "knobs": dict(knobs), "requires": requires, "notes": notes}


def validate_knobs(meta: dict, knobs: dict) -> list[str]:
    """Problems with the knob values a caller fixed (names, types, ranges). Empty when fine."""
    problems = []
    spec = meta.get("knobs") or {}
    for name, v in (knobs or {}).items():
        if name not in spec:
            problems.append(f"knob {name!r} is not declared; declared: {sorted(spec)}")
            continue
        s = spec[name]
        if "int" in s:
            lo, hi = s["int"]
            if not _is_int(v) or not lo <= v <= hi:
                problems.append(f"knob {name!r}: {v!r} is not an integer in [{lo}, {hi}]")
        elif "float" in s:
            lo, hi = s["float"]
            if not _is_num(v) or not lo <= v <= hi:
                problems.append(f"knob {name!r}: {v!r} is not a number in [{lo}, {hi}]")
        elif "choice" in s:
            if v not in s["choice"]:
                problems.append(f"knob {name!r}: {v!r} is not one of {list(s['choice'])}")
        elif not isinstance(v, bool):
            problems.append(f"knob {name!r}: {v!r} is not a boolean")
    return problems


def load_algo(path) -> LoadedAlgo:
    """Import the file at `path` and validate its META. Raises AlgoImportError or MetaError."""
    p = Path(path).resolve()
    if not p.is_file():
        raise AlgoImportError(f"no such algorithm file: {p}")
    h = algo_hash(p)
    modname = f"abacus_algo_{h}_{_NONWORD.sub('_', p.stem)}"
    spec = importlib.util.spec_from_file_location(modname, p)
    if spec is None or spec.loader is None:
        raise AlgoImportError(f"cannot import {p} as a Python module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[modname] = module
    try:
        spec.loader.exec_module(module)
    except Exception as e:  # noqa: BLE001
        sys.modules.pop(modname, None)
        raise AlgoImportError(f"{type(e).__name__}: {e}") from e
    if not hasattr(module, "META"):
        raise MetaError(["META: the file defines no META"], str(p))
    return LoadedAlgo(meta=validate_meta(module.META, str(p)), module=module, path=p, hash=h)
