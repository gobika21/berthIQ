"""Tiny JSON-file persistence shared by the history and alert stores."""

import json
import logging
import os

logger = logging.getLogger(__name__)

DATA_DIR = os.environ.get("BERTHIQ_DATA_DIR", os.path.join(os.path.dirname(os.path.dirname(__file__)), "live"))


def data_path(filename: str) -> str:
    return os.path.join(DATA_DIR, filename)


def load_json(path: str, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not load %s: %s", path, exc)
        return default


def save_json(path: str, data) -> None:
    tmp = f"{path}.tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, path)  # atomic, so a crash mid-write can't corrupt the file
    except OSError as exc:
        logger.warning("Could not save %s: %s", path, exc)
