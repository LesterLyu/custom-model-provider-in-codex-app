"""Platform-independent, narrowly scoped JSON-RPC provider routing."""
import json
import os
from pathlib import Path
import sqlite3
import time

METHODS = frozenset(("thread/start", "thread/resume", "thread/fork"))


def validate_routes(routes):
    if not isinstance(routes, dict) or not routes:
        raise ValueError("routes must be a nonempty model-to-provider object")
    for model, provider in routes.items():
        if not isinstance(model, str) or not model.strip() or not isinstance(provider, str) or not provider.strip():
            raise ValueError("Each route needs a nonempty model and provider string")
        if provider == "openai":
            raise ValueError("Only custom provider routes belong in this mapping")
    return dict(routes)


class Router:
    def __init__(self, home, routes, audit=None):
        self.home = Path(home)
        self.audit = audit
        self.routes = validate_routes(routes)

    def saved_model(self, thread_id):
        if not isinstance(thread_id, str):
            return None
        try:
            paths = sorted(self.home.glob("state_*.sqlite"), key=lambda p: p.stat().st_mtime, reverse=True)
        except OSError:
            return None
        for path in paths[:1]:
            try:
                with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=0.1) as db:
                    row = db.execute("SELECT model FROM threads WHERE id = ?", (thread_id,)).fetchone()
                    return row[0] if row else None
            except (OSError, sqlite3.Error):
                return None
        return None

    def rewrite(self, message):
        if not isinstance(message, str):
            return message
        try:
            obj = json.loads(message)
        except (ValueError, TypeError):
            return message
        if not isinstance(obj, dict) or obj.get("method") not in METHODS:
            return message
        params = obj.get("params")
        if not isinstance(params, dict):
            return message
        config = params.get("config")
        model = params.get("model")
        if model is None and isinstance(config, dict):
            model = config.get("model")
        if model is None and obj["method"] != "thread/start":
            model = self.saved_model(params.get("threadId"))
        if not isinstance(model, str) or model not in self.routes:
            return message
        provider = self.routes[model]
        before = params.get("modelProvider")
        changed = before != provider or params.get("model") != model
        params["model"], params["modelProvider"] = model, provider
        if isinstance(config, dict) and "model_provider" in config:
            changed |= config["model_provider"] != provider
            config["model_provider"] = provider
        if not changed:
            return message
        if self.audit:
            row = {"at": time.time(), "method": obj["method"],
                   "model": model, "before": before if isinstance(before, str) else None, "after": provider}
            try:
                fd = os.open(self.audit, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
                with os.fdopen(fd, "a") as f:
                    f.write(json.dumps(row) + "\n")
            except OSError:
                pass
        return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
