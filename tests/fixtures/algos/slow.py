import time

META = {
    "id": "misc.slow",
    "title": "Never finishes",
    "summary": "compute sleeps far past any test budget.",
    "roles": ["compute"],
    "answer": {"format": "integer"},
}


def compute(params):
    while True:
        time.sleep(0.05)
