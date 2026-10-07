"""Registry, CLI, MCP and the spec headings in 04-buttons.md must agree (spec 09 s4)."""
import re
from pathlib import Path

from abacus import cli, mcp_server, registry

SPEC = Path(__file__).resolve().parents[1] / "docs" / "spec" / "kit" / "04-buttons.md"
INTERNAL = {"run", "algo_lint", "algo_run", "algo_search", "algo_show", "link_add", "link_rm", "link_find",
            "mint_make", "mint_review", "mint_export"}

# Spec buttons that are not built yet. Remove a name here when its button lands.
PENDING = {
    "enumerate",
    "sequence",
    "counterexample",
    "simulate",
    "markov",
    "identify",
    "extremum",
    "numeric",
    "construct",
    "diff_test",
    "growth",
}


def spec_names() -> set[str]:
    return set(re.findall(r"^### \d+\. `([^`]+)`", SPEC.read_text(encoding="utf-8"), re.M))


def registered() -> set[str]:
    registry.load_all()
    return {b.name for b in registry.all_buttons()}


def real_registered() -> set[str]:
    # test-only buttons (registered by other test modules) are prefixed t_
    return {n for n in registered() if n not in INTERNAL and not n.startswith("t_")}


def test_spec_headings_found():
    assert len(spec_names()) == 14


def test_pending_names_are_real_spec_names():
    assert PENDING <= spec_names()


def test_every_registered_button_has_a_spec_heading():
    assert real_registered() <= spec_names()


def test_every_spec_heading_is_registered_or_pending():
    assert spec_names() <= real_registered() | PENDING
    assert not (real_registered() & PENDING), "built buttons must be removed from PENDING"


def test_cli_and_mcp_expose_registry_plus_run():
    reg = registered()
    assert "run" in reg
    assert set(cli.button_names()) == reg
    assert {t.name for t in mcp_server.list_tools()} == reg
