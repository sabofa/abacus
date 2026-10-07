import time

from abacus import registry
from abacus.evidence import Evidence


def _reg(name, **kw):
    def deco(fn):
        try:
            registry.get(name)
        except KeyError:
            registry.button(name, **kw)(fn)
        return fn
    return deco


_ANY = {"type": "object"}


@_reg("t_sleep_loop", description="loops", input_schema=_ANY)
def t_sleep_loop(inp, ctx):
    n = 0
    while True:
        n += 1
        ctx.progress({"result": n, "scope": f"counted to {n}", "method": "search"})
        time.sleep(0.05)


@_reg("t_seeded", description="seed", input_schema=_ANY, uses_seed=True)
def t_seeded(inp, ctx):
    return Evidence(button="t_seeded", result=ctx.seed, method="sampled", scope="the seed")


@_reg("t_schema", description="schema", input_schema={
    "type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]})
def t_schema(inp, ctx):
    return Evidence(button="t_schema", result=inp["n"] + 1, method="numeric", scope="n plus one")


@_reg("t_raise", description="raises", input_schema=_ANY)
def t_raise(inp, ctx):
    raise ValueError("boom")


@_reg("t_polite", description="stops itself", input_schema=_ANY)
def t_polite(inp, ctx):
    while ctx.time_left() >= 0.05:
        ctx.progress({"result": "bare", "scope": "bare progress", "method": "search"})
        time.sleep(0.02)
    return Evidence(button="t_polite", result="mine", method="timed", scope="stopped myself", complete=False)


@_reg("t_raise_after", description="progress then raises", input_schema=_ANY)
def t_raise_after(inp, ctx):
    ctx.progress({"result": 3, "scope": "got to 3", "method": "search"})
    raise ValueError("late")
