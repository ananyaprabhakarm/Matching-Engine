import json
import pickle
from typing import Any, List
from pathlib import Path

SNAPSHOT_FILE = Path("data/order_books_snapshot.pkl")

# Append-only, human-readable audit trail / write-ahead log: every accepted order,
# executed trade, and cancellation is appended as one JSON line. On startup, this
# is replayed on top of the last pickle snapshot to reconstruct exactly what
# happened since that snapshot was taken - the standard snapshot + replay-the-tail
# pattern. The periodic snapshot then truncates this file, since the snapshot
# already captures everything up to that point.
EVENT_LOG_FILE = Path("data/events.jsonl")


def save_snapshot(obj: Any, path: Path = SNAPSHOT_FILE):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        pickle.dump(obj, f)


def load_snapshot(path: Path = SNAPSHOT_FILE):
    if not path.exists():
        return None
    with open(path, "rb") as f:
        return pickle.load(f)


def append_event(event: dict, path: Path = EVENT_LOG_FILE):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(event) + "\n")


def read_events(path: Path = EVENT_LOG_FILE) -> List[dict]:
    if not path.exists():
        return []
    events = []
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            events.append(json.loads(line))
    return events


def truncate_event_log(path: Path = EVENT_LOG_FILE):
    if path.exists():
        path.unlink()
