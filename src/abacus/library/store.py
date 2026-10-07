"""The library on disk: algorithm ids, their paths, and reading and writing the files (kit/06 s1).

Files are the truth. An id is dot-separated segments, `nt.last-three-digits-of-tower`, and the dots
are directories: `<library>/nt/last-three-digits-of-tower.py`. The library is `ABACUS_LIBRARY`.
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
from pathlib import Path

from ..algo.loader import AlgoImportError, LoadedAlgo, load_algo
from ..config import get_config

_SEGMENT = re.compile(r"[a-z0-9][a-z0-9-]*")
# Reserved: `batches/` is not algorithms (it is skipped). The Windows device names would turn a file
# such as `nul.py` into a sink that silently discards what is written to it.
_RESERVED_AREAS = frozenset({"batches"})
_DEVICE_NAMES = frozenset({"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
                           *(f"lpt{i}" for i in range(1, 10))})


class NoSuchAlgo(AlgoImportError, FileNotFoundError):
    """No file in the library has this id."""


def library_dir() -> Path:
    return get_config().library


def _segments(parts, what: str) -> list[str]:
    parts = list(parts)
    if len(parts) < 2:
        raise ValueError(f"{what} must have an area and a name, such as 'nt.power-mod'")
    for seg in parts:
        if not _SEGMENT.fullmatch(seg):
            raise ValueError(f"{what}: segment {seg!r} must be lowercase letters, digits and '-', "
                             "starting with a letter or digit")
        if seg in _DEVICE_NAMES:
            raise ValueError(f"{what}: {seg!r} is a reserved device name on Windows")
    if parts[0] in _RESERVED_AREAS:
        raise ValueError(f"{what}: {parts[0]!r} is not an algorithm area")
    return parts


def _id_segments(algo_id) -> list[str]:
    if not isinstance(algo_id, str):
        raise ValueError(f"an algorithm id is a string such as 'nt.power-mod', got {algo_id!r}")
    return _segments(algo_id.split("."), f"bad id {algo_id!r}")


def id_to_path(algo_id: str) -> Path:
    """`nt.power-mod` becomes `<library>/nt/power-mod.py`. Raises ValueError on a bad id."""
    *area, name = _id_segments(algo_id)
    return library_dir().joinpath(*area, name + ".py")


def _rel_to_id(rel: Path) -> str:
    if rel.suffix != ".py":
        raise ValueError(f"{rel.as_posix()}: an algorithm file ends in .py")
    return ".".join(_segments([*rel.parent.parts, rel.stem], f"bad path {rel.as_posix()!r}"))


def path_to_id(path) -> str:
    """The id of an algorithm file. A relative path is taken from the library. ValueError if the
    path is outside the library or does not name an id."""
    lib = library_dir()
    p = Path(path)
    if not p.is_absolute():
        p = lib / p
    try:
        rel = p.relative_to(lib)
    except ValueError:
        try:
            rel = p.resolve().relative_to(lib.resolve())
        except ValueError:
            raise ValueError(f"{p} is not inside the library {lib}") from None
    if ".." in rel.parts:
        raise ValueError(f"{p} is not inside the library {lib}")
    return _rel_to_id(rel)


def list_files() -> list[Path]:
    """Every candidate algorithm file under the library, in path order. This skips `batches/` at the
    top, and any file or directory whose name starts with `_` or `.`. It does not check names or META."""
    lib = library_dir()
    if not lib.is_dir():
        return []
    found: list[Path] = []
    top = True
    for root, dirs, files in os.walk(lib):
        dirs[:] = [d for d in dirs if not d.startswith(("_", ".")) and not (top and d in _RESERVED_AREAS)]
        top = False
        found += [Path(root) / f for f in files if f.endswith(".py") and not f.startswith(("_", "."))]
    return sorted(found, key=lambda p: p.relative_to(lib).as_posix())


def list_ids() -> list[str]:
    """The ids of the library's algorithm files, sorted. A file whose name is not a valid id is left out."""
    lib = library_dir()
    out = []
    for p in list_files():
        try:
            out.append(_rel_to_id(p.relative_to(lib)))
        except ValueError:
            pass
    return sorted(out)


def read(algo_id: str) -> LoadedAlgo:
    """Load an algorithm by id. NoSuchAlgo if there is no file; the loader's errors if it is broken."""
    p = id_to_path(algo_id)
    if not p.is_file():
        raise NoSuchAlgo(f"no algorithm {algo_id!r} in the library {library_dir()} (expected {p})")
    return load_algo(p)


def write(algo_id: str, source: str, overwrite: bool = False) -> Path:
    """Write the source as the file for `algo_id`, creating directories. FileExistsError if there is
    already a file and `overwrite` is false. Bytes are kept exactly (UTF-8, no newline translation)."""
    p = id_to_path(algo_id)
    data = source.encode("utf-8")
    p.parent.mkdir(parents=True, exist_ok=True)
    if not overwrite:
        try:
            with open(p, "xb") as f:
                f.write(data)
        except FileExistsError:
            raise FileExistsError(f"{p} already exists; pass overwrite=True to replace it") from None
        except BaseException:
            p.unlink(missing_ok=True)
            raise
        return p
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".write-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        try:
            shutil.copymode(p, tmp)
        except OSError:
            pass
        os.replace(tmp, p)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return p
