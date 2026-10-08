"""diff_test: run two implementations on generated inputs and report where they disagree (kit/04 s13).

Agreement on the inputs that ran is not proof of agreement anywhere else. Each kind of disagreement is shrunk
with Hypothesis to a minimal input. Hypothesis is imported lazily: the other buttons never pay for it.
"""
from __future__ import annotations

import ast
import contextlib
import copy
import fractions
import itertools
import math
import random
import secrets
import time
from typing import Any, Callable

from .. import registry
from ..config import get_config
from ..evidence import Evidence, jsonable, make_compare
from . import _discrete as D
from ._cs import binding, compile_callable
from ._discrete import BadInput

NAME = "diff_test"
DEFAULT_EXAMPLES = 500
EDGE_CAP = 200          # boundary inputs tried before the generated ones
COMBO_CAP = 64          # boundary combinations kept per tuple / dict of strategies
SHOWN_CHARS = 2000      # an output or input longer than this is cut when shown
REPORT_EVERY = 10       # progress is also sent every this many inputs (and at least every 0.2 s) ...
REPORT_FIRST = 50       # ... and before each of the first inputs, so a function that hangs early is named
DIFF_TYPES = "both_raised_different_types"

DESCRIPTION = (
    "Run two implementations on generated inputs and report where they disagree. fast and reference are code: a "
    "lambda, a source with a def (the last def, or the one named fast/reference), or an expression in the input "
    "names. inputs is a Hypothesis strategy spec such as integers(1, 100) or lists(integers(0, 9), max_size=8); a "
    "tuple of strategies passes several positional arguments and a dict {'a': integers(), 'b': integers()} passes "
    "named ones (an expression then sees a and b; for a single strategy the expression sees x). The namespace holds "
    "hypothesis.strategies (integers, floats, booleans, text, lists, sets, tuples, dictionaries, fixed_dictionaries, "
    "one_of, just, none, sampled_from, builds, composite, ...) and math, Fraction. inputs can instead be a generator "
    "function def gen(rng): yield ... (yield a tuple for several arguments); those inputs are not shrunk. "
    "examples is how many inputs to run (default 500). edge (default true) first tries boundary values: 0, 1, -1, "
    "the ends of bounded ranges, empty lists, and so on. Seeded. Each kind of disagreement (the values differ; one "
    "side raised) is shrunk to a minimal input and shown with both outputs, at most max_examples kinds. Outputs are "
    "compared as make_compare does (1/2 and 0.5, tuple and list, set order), except that numbers are compared "
    "exactly: 0.1+0.2 and 0.3 disagree unless rtol or atol (default 0, applied to floats, also inside lists, tuples "
    "and dicts but not sets) says otherwise; the scope states the rule used. If only one raises, that is a "
    "disagreement; if both raise, the exception types are compared: the same type is agreement (counted as "
    "both_raised), different types a disagreement (kind both_raised_different_types). Hypothesis shrinks and the "
    "time budget may cut shrinking short: the scope says which kinds are shown shrunk. Agreement on the inputs that "
    "ran is not proof. The inputs spec and fast and reference are Python code that is executed, not sandboxed: the "
    "trimmed builtins in the inputs namespace keep it tidy, they are not a security boundary."
)

SCHEMA = {
    "type": "object",
    "properties": {
        "fast": {"type": "string"},
        "reference": {"type": "string"},
        "inputs": {"type": "string"},
        "examples": {"type": "integer"},
        "edge": {"type": "boolean"},
        "rtol": {"type": "number", "minimum": 0},
        "atol": {"type": "number", "minimum": 0},
    },
    "required": ["fast", "reference", "inputs"],
}


# ------------------------------------------------------------------------------------------------ boundary values

def _uniq(xs) -> list:
    seen, out = set(), []
    for x in xs:
        try:
            key = (type(x).__name__, repr(x))
        except Exception:  # noqa: BLE001
            continue
        if key not in seen:
            seen.add(key)
            out.append(x)
    return out


def _combos(lists: list[list], cap: int = COMBO_CAP) -> list[tuple]:
    """Boundary combinations: all-first, then each position varied alone, then the rest of the product."""
    if not lists or any(not l for l in lists):
        return []
    base = tuple(l[0] for l in lists)
    out: list[tuple] = [base]
    for i, l in enumerate(lists):
        for e in l[1:]:
            out.append(base[:i] + (e,) + base[i + 1:])
    out.extend(itertools.islice(itertools.product(*lists), cap * 4))
    return _uniq(out)[:cap]


def _interleave(lists: list[list]) -> list:
    out = []
    for row in itertools.zip_longest(*lists, fillvalue=_MISSING):
        out.extend(x for x in row if x is not _MISSING)
    return _uniq(out)


_MISSING = object()


class _Edges:
    """Boundary values per strategy, filled in as the caller's strategy code builds them."""

    def __init__(self):
        self._by_id: dict[int, tuple[Any, list]] = {}

    def of(self, strategy: Any) -> list:
        hit = self._by_id.get(id(strategy))
        return list(hit[1]) if hit else []

    def add(self, strategy: Any, edges: list) -> Any:
        self._by_id[id(strategy)] = (strategy, edges)
        return strategy

    # one method per strategy factory; each returns a list of boundary values (may be empty)

    def compute(self, name: str, a: tuple, k: dict) -> list:
        fn = getattr(self, f"_e_{name}", None)
        if fn is None:
            return []
        try:
            return _uniq(fn(a, k))[:COMBO_CAP]
        except Exception:  # noqa: BLE001  (an odd argument just means no boundary values)
            return []

    @staticmethod
    def _arg(a: tuple, k: dict, i: int, key: str, default=None):
        return a[i] if len(a) > i else k.get(key, default)

    def _e_integers(self, a, k):
        lo, hi = self._arg(a, k, 0, "min_value"), self._arg(a, k, 1, "max_value")
        cand = [x for x in (lo, hi) if x is not None] + [0, 1, -1]
        if lo is not None:
            cand.append(lo + 1)
        if hi is not None:
            cand.append(hi - 1)
        return [c for c in cand if (lo is None or c >= lo) and (hi is None or c <= hi)]

    def _e_floats(self, a, k):
        lo, hi = self._arg(a, k, 0, "min_value"), self._arg(a, k, 1, "max_value")
        cand = [x for x in (lo, hi) if x is not None] + [0.0, 1.0, -1.0]
        out = [float(c) for c in cand if (lo is None or c >= lo) and (hi is None or c <= hi)]
        if (lo is None or lo < 0 or math.copysign(1, lo) < 0) and (hi is None or hi >= 0):
            out.append(-0.0)                      # Hypothesis draws -0.0 only where the range reaches below +0.0
        if k.get("allow_infinity", lo is None or hi is None):
            out += [x for x in (math.inf, -math.inf) if (lo is None or x >= lo) and (hi is None or x <= hi)]
        if k.get("allow_nan", lo is None and hi is None):
            out.append(math.nan)
        return out

    def _e_booleans(self, a, k):
        return [False, True]

    def _e_none(self, a, k):
        return [None]

    def _e_just(self, a, k):
        return [a[0]] if a else [k["value"]]

    def _e_sampled_from(self, a, k):
        xs = list(self._arg(a, k, 0, "elements"))
        return xs if len(xs) <= 4 else [xs[0], xs[1], xs[-2], xs[-1]]

    def _e_text(self, a, k):
        alphabet, min_size, max_size = self._arg(a, k, 0, "alphabet"), k.get("min_size", 0), k.get("max_size")
        if alphabet is not None and not isinstance(alphabet, str):
            return [""] if min_size == 0 else []
        ch = alphabet[0] if alphabet else "a"
        out = [""] if min_size == 0 else []
        out += [ch * n for n in (1, 2) if n >= min_size and (max_size is None or n <= max_size)]
        if max_size is not None and 2 < max_size <= 10:
            out.append(ch * max_size)
        return out

    def _e_binary(self, a, k):
        return [b""] if k.get("min_size", 0) == 0 else []

    def _e_permutations(self, a, k):
        xs = list(self._arg(a, k, 0, "values"))
        return [xs, xs[::-1]]

    def _sized(self, a, k, build):
        elem = self._arg(a, k, 0, "elements")
        min_size, max_size = self._arg(a, k, 1, "min_size", 0), self._arg(a, k, 2, "max_size")
        ee = self.of(elem)[:4]
        if not ee:
            return []
        unique = bool(k.get("unique", False))
        out: list = []
        if min_size == 0:
            out.append(build([]))
        sizes = [1] + [s for s in (min_size, max_size) if s is not None and s <= 10]
        for size in _uniq(sizes):
            if size < min_size or (max_size is not None and size > max_size) or size < 1:
                continue
            if unique and size > len(ee):
                continue
            if size == 1:
                out.extend(build([e]) for e in ee)
            else:
                out.append(build([ee[i % len(ee)] for i in range(size)] if not unique else ee[:size]))
                if not unique:
                    out.append(build([ee[0]] * size))
        return out

    def _e_lists(self, a, k):
        return self._sized(a, k, list)

    def _e_sets(self, a, k):
        return [s for s in self._sized(a, k, set) if len(s) >= self._arg(a, k, 1, "min_size", 0)]

    def _e_frozensets(self, a, k):
        return [s for s in self._sized(a, k, frozenset) if len(s) >= self._arg(a, k, 1, "min_size", 0)]

    def _e_tuples(self, a, k):
        return [tuple(c) for c in _combos([self.of(s) for s in a])]

    def _e_fixed_dictionaries(self, a, k):
        mapping = self._arg(a, k, 0, "mapping")
        keys = list(mapping)
        return [dict(zip(keys, c)) for c in _combos([self.of(mapping[key]) for key in keys])]

    def _e_dictionaries(self, a, k):
        keys, values = self._arg(a, k, 0, "keys"), self._arg(a, k, 1, "values")
        ke, ve = self.of(keys)[:3], self.of(values)[:3]
        out = [{}] if k.get("min_size", 0) == 0 else []
        out += [{x: y} for x in ke for y in ve]
        return out

    def _e_one_of(self, a, k):
        args = a[0] if len(a) == 1 and not hasattr(a[0], "example") else a
        return _interleave([self.of(s) for s in args])


_FACTORIES = ("integers", "floats", "booleans", "none", "just", "sampled_from", "text", "binary", "permutations",
              "lists", "sets", "frozensets", "tuples", "fixed_dictionaries", "dictionaries", "one_of")
_PLAIN = ("characters", "fractions", "decimals", "complex_numbers", "builds", "composite", "from_regex", "deferred",
          "recursive", "dates", "times", "datetimes", "timedeltas", "uuids", "emails", "nothing", "iterables",
          "shared", "data", "SearchStrategy")
_SAFE_BUILTINS = ("abs all any bool bytes chr dict divmod enumerate filter float frozenset int isinstance len list map "
                  "max min ord pow range reversed round set sorted str sum tuple zip True False None").split()


def _namespace(edges: _Edges) -> dict:
    """The names an inputs spec can use: the strategies, math and Fraction, and a short list of builtins.
    The spec is code and runs as the caller's Python (by design); this keeps the namespace clear, not sealed."""
    import builtins
    import hypothesis.strategies as st

    def wrap(name):
        factory = getattr(st, name)

        def make(*a, **k):
            s = factory(*a, **k)
            return edges.add(s, edges.compute(name, a, k))
        make.__name__ = name
        return make

    ns: dict[str, Any] = {name: wrap(name) for name in _FACTORIES}
    ns.update({name: getattr(st, name) for name in _PLAIN if hasattr(st, name)})
    ns.update({"math": math, "Fraction": fractions.Fraction, "st": st})
    ns["__builtins__"] = {n: getattr(builtins, n) for n in _SAFE_BUILTINS}
    return ns


# ------------------------------------------------------------------------------------------------ the inputs spec

class Spec:
    """What the ``inputs`` code made: a strategy (form single, tuple or dict) or a generator function."""

    def __init__(self):
        self.form: str = "single"          # single | tuple | dict
        self.strategy: Any = None          # Hypothesis strategy of the packed argument
        self.names: list[str] = []         # dict keys
        self.arity = 1
        self.edge_inputs: list = []        # packed boundary arguments
        self.edgeless: list = []           # arguments (1-based positions, or names) with no boundary values
        self.gen: Callable | None = None   # generator function, when the inputs are code


def _is_strategy(x: Any) -> bool:
    from hypothesis.strategies import SearchStrategy
    return isinstance(x, SearchStrategy)


def parse_inputs(src: str) -> Spec:
    import hypothesis.strategies as st
    if not isinstance(src, str) or not src.strip():
        raise BadInput("inputs must be a non-empty string: a Hypothesis strategy spec or a generator")
    edges = _Edges()
    ns = _namespace(edges)
    text = src.strip()
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError:
        tree = None
    try:
        if tree is not None:
            value = eval(compile(tree, "<inputs>", "eval"), ns)
        else:
            exec(compile(text + "\n", "<inputs>", "exec"), ns)
            defs = [n.name for n in ast.parse(text + "\n").body if isinstance(n, (ast.FunctionDef,))]
            if "inputs" in ns:
                value = ns["inputs"]
            elif defs:
                value = ns[defs[-1]]
            else:
                raise BadInput("inputs: the code must define inputs, or a function that yields them")
    except BadInput:
        raise
    except SyntaxError as e:
        raise BadInput(f"inputs: {e.msg} (line {e.lineno})") from None
    except Exception as e:  # noqa: BLE001
        raise BadInput(f"inputs: {type(e).__name__}: {e}") from None

    spec = Spec()
    if _is_strategy(value):
        spec.strategy = st.tuples(value)
        spec.edge_inputs = [(e,) for e in edges.of(value)]
        return spec
    if isinstance(value, tuple) and value and all(_is_strategy(s) for s in value):
        spec.form, spec.arity = "tuple", len(value)
        spec.strategy = st.tuples(*value)
        spec.edge_inputs = _combos([edges.of(s) for s in value])
        spec.edgeless = [i + 1 for i, s in enumerate(value) if not edges.of(s)]
        return spec
    if isinstance(value, dict) and value and all(_is_strategy(s) for s in value.values()):
        if not all(D.is_name(k) for k in value):
            raise BadInput("inputs: the dict keys must be valid input names")
        spec.form, spec.names, spec.arity = "dict", list(value), len(value)
        spec.strategy = st.fixed_dictionaries(dict(value))
        spec.edge_inputs = [dict(zip(spec.names, c)) for c in _combos([edges.of(value[n]) for n in spec.names])]
        spec.edgeless = [n for n in spec.names if not edges.of(value[n])]
        return spec
    if callable(value) and not _is_strategy(value):
        spec.gen = value
        return spec
    raise BadInput("inputs must evaluate to a Hypothesis strategy, a tuple or dict of them, or be a generator "
                   f"function; it gave {D.short(value, 40)}")


# ------------------------------------------------------------------------------------------------ one input

def _clip(x: Any) -> Any:
    j = jsonable(x)
    s = repr(j)
    return j if len(s) <= SHOWN_CHARS else f"{s[:SHOWN_CHARS]}... ({len(s)} characters)"


def _raised(e: BaseException) -> str:
    msg = str(e)
    return f"{type(e).__name__}: {msg}" if len(msg) <= 200 else f"{type(e).__name__}: {msg[:200]}..."


def _num(x: Any) -> bool:
    return isinstance(x, (int, float, fractions.Fraction))


def _plain(x: Any) -> Any:
    """An array as nested lists (so its elements are compared one by one), anything else as it is."""
    if hasattr(x, "tolist") and hasattr(x, "shape"):
        try:
            return x.tolist()
        except Exception:  # noqa: BLE001
            return x
    return x


def _equal(a: Any, b: Any, rtol: float = 0.0, atol: float = 0.0) -> bool:
    """Numbers are exact unless rtol/atol say otherwise (then wherever either side is a float, also inside lists,
    tuples and dicts); a list and a tuple compare by element; the rest is make_compare."""
    a, b = _plain(a), _plain(b)
    if _num(a) and _num(b):
        if a != a and b != b:                      # both nan: the same outcome
            return True
        if (rtol or atol) and (isinstance(a, float) or isinstance(b, float)):
            try:
                return math.isclose(float(a), float(b), rel_tol=rtol, abs_tol=atol)
            except OverflowError:
                pass
        return bool(a == b)                        # exact numbers: make_compare would not call them equal either
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(_equal(x, y, rtol, atol) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_equal(a[k], b[k], rtol, atol) for k in a)
    return bool(make_compare(a, b)["equal"])


def _rule(rtol: float, atol: float) -> str:
    if not rtol and not atol:
        return ("outputs compared exactly (floats not toleranced: 0.1+0.2 and 0.3 disagree; 1/2 and 0.5, a tuple "
                "and a list, and set order count as equal)")
    return (f"outputs compared with rtol={rtol:g}, atol={atol:g} wherever either number is a float, also inside "
            "lists, tuples and dicts (not inside sets); every other number, and everything else, exactly")


class _Abort(BaseException):
    """Raised inside the property to leave Hypothesis the moment the time budget is spent."""


class _Found(Exception):
    """A disagreement of the wanted kind, carrying what to show."""

    def __init__(self, record: dict):
        super().__init__("disagreement")
        self.record = record


class Runner:
    def __init__(self, fast: Callable, ref: Callable, spec: Spec, ctx, examples: int, edge: bool,
                 f_bind: str, r_bind: str, seed: int, rtol: float = 0.0, atol: float = 0.0):
        self.fast, self.ref, self.spec = fast, ref, spec
        self.ctx, self.examples, self.edge, self.seed = ctx, examples, edge, seed
        self.f_bind, self.r_bind = f_bind, r_bind
        self.rtol, self.atol = rtol, atol
        self.ran = self.edge_ran = self.agree = self.both_raised = 0   # ran counts inputs that have finished
        self.shared = 0                                 # calls that got the caller's own object (it could not be copied)
        self.kinds: dict[str, int] = {}                 # kind of disagreement -> count
        self.witness: dict[str, dict] = {}              # kind -> first record
        self.stopped = False                            # the budget ended the sampling phase
        self.shrinking = False                          # inside the shrinking phase
        self.shrink_cut = False                         # the budget ended the shrinking phase (sampling was whole)
        self.inflight: dict | None = None               # what the last progress report said was running
        self._report = time.monotonic()
        self._since = 0
        self._announce_next = False

    # -- calling

    def _call(self, fn: Callable, bind: str, packed: Any):
        try:
            args = copy.deepcopy(packed)
        except Exception:  # noqa: BLE001
            args = packed
            self.shared += 1
        try:
            if isinstance(args, dict):
                return True, (fn(**args) if bind == "kw" else fn(*args.values()))
            return True, fn(*args)
        except Exception as e:  # noqa: BLE001
            return False, e

    def _show_input(self, packed: Any) -> Any:
        if isinstance(packed, dict):
            return _clip(packed)
        if self.spec.form == "single" or (self.spec.gen and len(packed) == 1):
            return _clip(packed[0])
        return _clip(list(packed))

    def _announce(self, who: str, packed: Any) -> None:
        """Say, before the call, which function is about to run on which input: if it never comes back, this
        is the last thing the caller hears."""
        self.inflight = {"in": who, "input": self._show_input(packed), "number": self.ran + 1}
        self.ctx.progress(self.partial())

    def judge(self, packed: Any) -> tuple[str | None, dict]:
        """(kind of disagreement or None, record). Both raising the same exception type counts as agreement
        (kind None, record['both'])."""
        if self._announce_next:
            self._announce("fast", packed)
        ok_f, vf = self._call(self.fast, self.f_bind, packed)
        if self._announce_next:
            self._announce("reference", packed)
        ok_r, vr = self._call(self.ref, self.r_bind, packed)
        rec = {"input": None, "fast": None, "reference": None, "both": False}
        if not ok_f and not ok_r:
            if type(vf).__name__ == type(vr).__name__:
                rec["both"] = True
                return None, rec
            kind = DIFF_TYPES
        elif ok_f and ok_r:
            try:
                same = _equal(vf, vr, self.rtol, self.atol)
            except Exception:  # noqa: BLE001
                same = False
            if same:
                return None, rec
            kind = "the values differ"
        else:
            kind = f"fast raised {type(vf).__name__}" if not ok_f else f"reference raised {type(vr).__name__}"
        rec["input"] = self._show_input(packed)
        rec["fast"] = {"value": _clip(vf)} if ok_f else {"raised": _raised(vf)}
        rec["reference"] = {"value": _clip(vr)} if ok_r else {"raised": _raised(vr)}
        rec["kind"] = kind
        return kind, rec

    # -- counting

    def tally(self, packed: Any, edge: bool = False) -> None:
        kind, rec = self.judge(packed)
        self.ran += 1
        if edge:
            self.edge_ran += 1
        if kind is None:
            self.agree += 1
            self.both_raised += rec["both"]
            return
        self.kinds[kind] = self.kinds.get(kind, 0) + 1
        self.witness.setdefault(kind, dict(rec, shrunk=False))

    def tick(self) -> None:
        """Called before each input: decide whether this input is announced, and leave when the time is spent.
        Running out of time while sampling stops the run; while shrinking it only cuts the shrinking short."""
        if self.ctx.time_left() <= 0.05:
            if self.shrinking:
                self.shrink_cut = True
            else:
                self.stopped = True
            raise _Abort()
        if self.shrinking:
            self._announce_next = False
            return
        now = time.monotonic()
        self._since += 1
        self._announce_next = (self.ran < REPORT_FIRST or self._since >= REPORT_EVERY
                               or now - self._report >= 0.2)
        if self._announce_next:
            self._since = 0
            self._report = now

    def partial(self) -> dict:
        if self.shrinking:
            shown = [{k: v for k, v in r.items() if k != "both"} for r in self.witness.values()]
            scope = (f"stopped at the time budget while shrinking, after all {self.ran} inputs had run; the "
                     "disagreements are shown as first found, not shrunk")
            return {"result": self.result(shown), "method": "sampled", "scope": scope}
        scope = f"stopped at the time budget after {self.ran} inputs had finished; the rest were not run"
        if self.inflight:
            f = self.inflight
            scope += (f". The last report was made inside {f['in']}() on input {f['input']!r} (input #{f['number']}); "
                      "if it never returned, that call is where it stopped (inputs after the report may have run)")
        return {"result": self.result([]), "method": "sampled", "scope": scope}

    def result(self, shown: list[dict]) -> dict:
        d = sum(self.kinds.values())
        return {"inputs_run": self.ran, "edge_inputs": self.edge_ran, "sampled_inputs": self.ran - self.edge_ran,
                "agreements": self.agree, "disagreements": d, "both_raised": self.both_raised,
                "kinds": dict(self.kinds), "disagreement_examples": shown}


# ------------------------------------------------------------------------------------------------ Hypothesis

def _settings(examples: int):
    from hypothesis import HealthCheck, Phase, Verbosity, settings
    return settings(database=None, deadline=None, max_examples=examples, suppress_health_check=list(HealthCheck),
                    phases=[Phase.generate, Phase.shrink], verbosity=Verbosity.quiet, report_multiple_bugs=False,
                    print_blob=False, derandomize=False)


@contextlib.contextmanager
def _nothing_on_disk():
    """Hypothesis reads constants out of every local module's source and caches them under ``.hypothesis`` in the
    working directory, even with the database off. Leave them out: no file is written, and the draws no longer
    depend on which modules happen to be loaded."""
    try:
        from hypothesis.internal.conjecture import providers
        from hypothesis.internal.conjecture.providers import Constants
        original = providers._get_local_constants
        empty = Constants()
        providers._get_local_constants = lambda: empty
    except Exception:  # noqa: BLE001  (a Hypothesis without this internal: nothing to switch off)
        yield
        return
    try:
        yield
    finally:
        providers._get_local_constants = original


def _drive(run: Runner, prop: Callable, seed: int, examples: int) -> None:
    """Run ``prop`` over Hypothesis' packed inputs, seeded, with nothing written to disk."""
    from hypothesis import given, seed as hseed
    test = hseed(seed)(_settings(examples)(given(run.spec.strategy)(prop)))
    with _nothing_on_disk():
        test()


def _generated(run: Runner) -> None:
    """The sampling phase: every generated input is judged and counted, none fails."""
    def prop(packed):
        run.tick()
        run.tally(packed)

    _drive(run, prop, run.seed, run.examples)


def _shrink(run: Runner, kind: str) -> dict | None:
    """Rediscover a disagreement of ``kind`` with the same seed and let Hypothesis shrink it."""
    def prop(packed):
        run.tick()
        k, rec = run.judge(packed)
        if k == kind:
            raise _Found(dict(rec, shrunk=True))

    try:
        _drive(run, prop, run.seed, run.examples)
    except _Found as f:
        return f.record
    except _Abort:
        return None
    except Exception:  # noqa: BLE001  (not reproduced, or the functions are not deterministic)
        return None
    return None


# ------------------------------------------------------------------------------------------------ the button

def _generator_items(spec: Spec, rng: random.Random):
    fn = spec.gen
    import inspect
    try:
        n = len(inspect.signature(fn).parameters)
    except (TypeError, ValueError):
        n = 0
    gen = fn(rng) if n >= 1 else fn()
    for item in gen:
        if isinstance(item, dict):
            yield item
        elif isinstance(item, tuple):
            yield item
        else:
            yield (item,)


def _run(inp: dict, ctx) -> Evidence:
    examples = inp.get("examples", DEFAULT_EXAMPLES)
    edge = inp.get("edge", True)
    if not D.is_int(examples) or examples < 1:
        raise BadInput("examples must be an integer >= 1")
    if not isinstance(edge, bool):
        raise BadInput("edge must be true or false")
    tol = []
    for key in ("rtol", "atol"):
        v = inp.get(key, 0.0)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0:
            raise BadInput(f"{key} must be a finite number >= 0")
        tol.append(float(v))
    rtol, atol = tol
    spec = parse_inputs(inp.get("inputs"))
    seed = ctx.seed if ctx.seed is not None else secrets.randbelow(2 ** 32)

    names = spec.names or None
    expr_names = spec.names or (["x"] if spec.arity == 1 else [f"x{i + 1}" for i in range(spec.arity)])
    fast = compile_callable(inp.get("fast"), "fast", expr_names if not spec.gen else ["x"])
    ref = compile_callable(inp.get("reference"), "reference", expr_names if not spec.gen else ["x"])
    if spec.gen is None:
        f_bind = binding(fast, "fast", spec.arity, names)
        r_bind = binding(ref, "reference", spec.arity, names)
    else:
        f_bind = r_bind = "kw"

    run = Runner(fast, ref, spec, ctx, examples, edge, f_bind, r_bind, seed, rtol, atol)
    cap = max(1, get_config().max_examples)
    notes: list[str] = []
    err: Exception | None = None

    try:
        ctx.progress(run.partial())
        if spec.gen is not None:
            if edge:
                notes.append("edge was ignored: the inputs come from a generator, which sets its own values")
            first = True
            rng = random.Random(seed)
            for item in _generator_items(spec, rng):
                if run.ran >= examples:
                    break
                if first:
                    first = False
                    if isinstance(item, dict):
                        run.f_bind = binding(fast, "fast", len(item), list(item))
                        run.r_bind = binding(ref, "reference", len(item), list(item))
                    else:
                        binding(fast, "fast", len(item))
                        binding(ref, "reference", len(item))
                run.tick()
                run.tally(item)
        else:
            if edge:
                for packed in spec.edge_inputs[:EDGE_CAP]:
                    run.tick()
                    run.tally(packed, edge=True)
                if not spec.edge_inputs:
                    which = (f" (argument{'s' if len(spec.edgeless) > 1 else ''} "
                             f"{', '.join(str(x) for x in spec.edgeless)} had none, and a tuple or dict needs "
                             "boundary values for every argument)" if spec.edgeless else "")
                    notes.append("edge was on but no boundary values could be derived for this strategy "
                                 "(it is not one of the built-in kinds, or was built with map/filter)" + which)
            _generated(run)
    except _Abort:
        pass
    except BadInput:
        raise
    except Exception as e:  # noqa: BLE001  (the strategy or generator itself failed)
        err = e
    d_total = sum(run.kinds.values())

    # shrink one witness per kind of disagreement
    shown: list[dict] = []
    kinds = list(run.kinds)
    if err is None:
        for kind in kinds[:cap]:
            rec = run.witness[kind]
            if spec.gen is None and not run.stopped and not run.shrink_cut and ctx.time_left() > 0.1:
                run.shrinking = True
                ctx.progress(run.partial())      # a function that hangs while shrinking leaves this, not a stale line
                try:
                    better = _shrink(run, kind)
                except Exception:  # noqa: BLE001
                    better = None
                finally:
                    run.shrinking = False
                if better is not None:
                    rec = better
                elif ctx.time_left() <= 0.05:
                    run.shrink_cut = True
            elif spec.gen is None:
                run.shrink_cut = True
            shown.append({k: v for k, v in rec.items() if k != "both"})
    hidden = len(kinds) - len(shown)

    result = run.result(shown)
    if spec.gen is None and run.ran - run.edge_ran < examples and not run.stopped and err is None:
        sampled = run.ran - run.edge_ran
        notes.append(f"Hypothesis stopped after {sampled} generated inputs of the {examples} asked for "
                     "(a small input space, or heavy filtering)")

    if run.shrink_cut:
        notes.append("shrinking was cut short by the time budget; the inputs not shrunk are shown as first found")
    what = f"{run.ran} inputs" if run.ran else "no inputs"
    if spec.gen is not None:
        how = f"{what} from the generator (seed {seed}), not shrunk"
    else:
        sampled = run.ran - run.edge_ran
        edge_text = (f"{run.edge_ran} edge cases included" if edge and run.edge_ran
                     else ("edge cases requested but none could be derived" if edge else "edge cases not included"))
        how = f"{what} ({sampled} generated by Hypothesis, seed {seed}; {edge_text})"
    d = result["disagreements"]
    if run.stopped:
        scope = f"stopped at the time budget after {how}; the rest of the {examples} requested were not run"
    else:
        scope = f"ran {how}"
    scope += f"; {d} disagreed, {run.agree} agreed"
    if run.both_raised:
        scope += f" ({run.both_raised} of the agreements are both raising the same exception type)"
    scope += "; " + _rule(rtol, atol)
    if shown and spec.gen is None:
        loose = [r["kind"] for r in shown if not r.get("shrunk")]
        if not loose:
            scope += "; each kind of disagreement is shown shrunk by Hypothesis to a minimal input"
        else:
            why = ("shrinking was cut short by the time budget" if run.shrink_cut
                   else "Hypothesis did not reproduce them, or the functions are not deterministic")
            scope += (f"; {len(shown) - len(loose)} of the {len(shown)} kinds shown are shrunk by Hypothesis; "
                      f"not shrunk: {', '.join(loose)} ({why}), shown as first found")
    if hidden > 0:
        scope += f"; {hidden} more kind(s) of disagreement not shown (cap {cap})"
        notes.append(f"showing {len(shown)} of {len(kinds)} kinds of disagreement (cap {cap} = max_examples)")
    if d == 0:
        scope += ". Agreement on these inputs is not proof that they agree on others"
    else:
        scope += ". Inputs that did not run are not covered; agreement elsewhere is not proof"

    ev = Evidence(button=NAME, result=result, method="sampled", scope=scope,
                  complete=not run.stopped and err is None, seed=seed, examples=list(shown))
    if run.shared:
        ev.flag("shared_input", f"{run.shared} call(s) got the caller's own input object because it could not be "
                "copied, so fast and reference may have shared (and changed) one object")
    if run.ran and run.both_raised + run.kinds.get(DIFF_TYPES, 0) == run.ran:
        ev.flag("always_raised", "both functions raised on every input, so nothing was compared; "
                "check that the arguments fit the functions")
    if err is not None:
        ev.complete = False
        ev.scope = f"inputs: the strategy or generator failed after {run.ran} inputs; " + ev.scope
        ev.flag("bad_input", f"inputs: {type(err).__name__}: {err}")
    ev.notes.extend(notes)
    return ev


@registry.button(NAME, description=DESCRIPTION, input_schema=SCHEMA, uses_seed=True)
def diff_test_button(inp: dict, ctx) -> Evidence:
    try:
        return _run(inp, ctx)
    except BadInput as e:
        return D.bad_input(NAME, "sampled", str(e))
