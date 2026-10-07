import json

from abacus import mcp_server, registry
from tests import _budget_buttons  # noqa: F401  (registers t_* test buttons)


def test_list_tools_matches_registry():
    tools = mcp_server.list_tools()
    assert [t.name for t in tools] == [b.name for b in registry.all_buttons()]
    assert "run" in [t.name for t in tools]
    assert all(t.description and t.input_schema for t in tools)


def test_call_run_tool():
    text, is_err = mcp_server.call_tool("run", {"code": "print(1)\n2+3"})
    ev = json.loads(text)
    assert not is_err and ev["button"] == "run"
    assert ev["result"] == {"stdout": "1\n", "value": 5}


def test_call_bad_input_is_evidence():
    text, is_err = mcp_server.call_tool("run", {"nope": 1})
    ev = json.loads(text)
    assert not is_err and ev["complete"] is False and ev["flags"][0]["code"] == "bad_input"


def test_call_unknown_tool():
    text, is_err = mcp_server.call_tool("zzz", {})
    assert is_err and "unknown button" in json.loads(text)["error"]


def test_server_builds():
    assert mcp_server.make_server() is not None
