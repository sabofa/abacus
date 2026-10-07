from abacus import budget, sandbox  # noqa: F401


def test_stdout_before_timeout_survives():
    ev = budget.call("run", {"code": 'print("a"); print("b")\nwhile True: pass'}, time_s=1.5)
    assert ev.complete is False
    assert "a\nb" in ev.result["stdout"]


def test_stdout_survives_exception():
    ev = budget.call("run", {"code": 'print("before"); raise ValueError("x")'}, time_s=30)
    assert ev.result == {"stdout": "before\n", "value": None}
    assert ev.complete is False
    assert any("ValueError: x" in str(f) for f in ev.flags)


def test_heavy_aliases_are_lazy_and_available():
    ns = sandbox.namespace()
    assert "np" not in dict.keys(ns)
    assert sandbox.run_code("np.arange(3).sum()")[1] == 3
    assert sandbox.run_code("def f():\n    return sp.Symbol('x').name\nf()")[1] == "x"
    try:
        sandbox.run_code("nope")
    except NameError:
        pass
    else:
        raise AssertionError("expected NameError")


def test_tee_close_flushes_and_nothing_is_sent_after():
    import threading
    import time

    events, lock = [], threading.Lock()

    def progress(p):
        with lock:
            events.append(("progress", p["result"]["stdout"]))

    tee = sandbox._Tee(progress)
    tee.write("one\n")           # t=0: sent inline
    time.sleep(0.01)
    tee.write("two\n")           # t=+10ms: schedules the trailing timer
    assert tee._timer is not None
    tee.close_stream()
    with lock:
        events.append(("closed", None))
    time.sleep(0.2)              # an orphaned timer would fire here
    with lock:
        kinds = [k for k, _ in events]
    assert kinds.count("closed") == 1 and kinds[-1] == "closed"
    assert tee.getvalue() == "one\ntwo\n"
    tee.write("late\n")
    assert [k for k, _ in events][-1] == "closed"


def test_tee_sends_are_serialised_and_cancel_pending_timer():
    import threading

    active, overlap = [0], []

    def progress(p):
        active[0] += 1
        overlap.append(active[0])
        active[0] -= 1

    tee = sandbox._Tee(progress)
    tee.write("a")
    tee.write("b")               # timer pending
    tee._send()                  # inline send must cancel it
    assert tee._timer is None
    tee.close_stream()
    assert max(overlap) == 1 and threading.active_count() >= 1


def test_run_turns_any_compile_failure_into_did_not_parse():
    ev = budget.call("run", {"code": "x = (" * 1}, time_s=30)
    assert ev.scope == "the code did not parse"
    ev = budget.call("run", {"code": "a\x00b"}, time_s=30)
    assert ev.scope == "the code did not parse"
