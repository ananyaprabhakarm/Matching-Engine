import pickle
from typing import Any
from pathlib import Path

SNAPSHOT_FILE = Path("data/order_books_snapshot.pkl")

def save_snapshot(obj: Any, path: Path = SNAPSHOT_FILE):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        pickle.dump(obj, f)

def load_snapshot(path: Path = SNAPSHOT_FILE):
    if not path.exists():
        return None
    with open(path, "rb") as f:
        return pickle.load(f)
