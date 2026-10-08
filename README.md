# abacus

A math toolkit for AI: a calculator it reaches for when it wants to.

It computes what thinking alone can't do reliably: brute-force counting, simulation, exact arithmetic, turning decimals into closed forms, testing identities, measuring geometry by construction, and comparing a clever solution against a brute-force one. It never tells the AI whether it is right. Every result is evidence, and says exactly what it covered.

**Status (2026-10-07):** the first kit build is merged: 13 of the 14 buttons (`construct` waits on the geometry design), the algorithm format, library and minting. `abacus --help` lists the commands; `abacus mcp` serves them over MCP.

```
python -m venv .venv
.venv\Scripts\python -m pip install -e .[dev]     # Windows; use .venv/bin/python elsewhere
.venv\Scripts\python -m pytest -q -p no:cacheprovider
```

Known limits are stated in the results themselves (every result says what it covered). Open items and the build record are in `.superpowers/sdd/kit-build/`.

## Spec

- **[`docs/spec/`](docs/spec/00-README.md) is a mirror.** The canonical copy is in the Learn repo (github.com/sabofa/Learn) at `spec/abacus/`. Edit it there, then copy it here.
- **Spec 1, [`kit/`](docs/spec/kit/00-README.md):** the Python package, 14 buttons and a sandbox, the algorithm format, the algorithm library with its links, and minting.
- **Spec 2, [`live/`](docs/spec/live/00-README.md):** a fresh instance each time a question comes up, pools, per-family scheduling, and demos.
- **Spec 3, create:** how the AI comes up with original problems. Next; not written yet.

## Consumers

Osmosis (github.com/sabofa/Osmosis) is the first consumer. abacus stays independent of it: only `src/abacus/adapters/` knows any consumer's name.
