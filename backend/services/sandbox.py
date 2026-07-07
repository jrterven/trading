from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


RUNNER_SOURCE = r'''
import importlib.util
import json
import sys
import traceback


class Context:
    def __init__(self, payload):
        self.symbol = payload["symbol"]
        self.timeframe = payload["timeframe"]
        self.news = payload.get("news", [])
        try:
            import pandas as pd
            self.candles = pd.DataFrame(payload["candles"])
            self.news = pd.DataFrame(payload.get("news", []))
            self.sentiment = pd.DataFrame(payload.get("sentiment", []))
            if not self.candles.empty and "timestamp" in self.candles:
                self.candles["timestamp"] = pd.to_datetime(self.candles["timestamp"], utc=True)
                self.candles = self.candles.set_index("timestamp", drop=False)
            if not self.news.empty and "available_at" in self.news:
                self.news["available_at"] = pd.to_datetime(self.news["available_at"], utc=True)
            if not self.sentiment.empty and "created_at" in self.sentiment:
                self.sentiment["created_at"] = pd.to_datetime(self.sentiment["created_at"], utc=True)
        except Exception:
            self.candles = payload["candles"]
            self.sentiment = payload.get("sentiment", [])

    def news_until(self, timestamp):
        try:
            import pandas as pd
            if not hasattr(self.news, "empty") or self.news.empty or "available_at" not in self.news:
                return self.news
            cutoff = pd.to_datetime(timestamp, utc=True)
            return self.news[self.news["available_at"] <= cutoff]
        except Exception:
            return self.news

    def sentiment_until(self, timestamp):
        try:
            available_news = self.news_until(timestamp)
            if (
                not hasattr(available_news, "empty")
                or available_news.empty
                or not hasattr(self.sentiment, "empty")
                or self.sentiment.empty
                or "article_id" not in self.sentiment
            ):
                return self.sentiment
            article_ids = set(available_news["id"].tolist())
            return self.sentiment[self.sentiment["article_id"].isin(article_ids)]
        except Exception:
            return self.sentiment


def normalize_signal(value, n):
    if value is None:
        return [False] * n
    if hasattr(value, "fillna"):
        value = value.fillna(False)
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, dict):
        value = list(value.values())
    if not isinstance(value, (list, tuple)):
        raise ValueError("entries/exits deben ser listas, Series de pandas o arrays booleanos")
    normalized = [bool(item) for item in value]
    if len(normalized) < n:
        normalized.extend([False] * (n - len(normalized)))
    return normalized[:n]


def normalize_markers(value):
    if value is None:
        return []
    if hasattr(value, "to_dict"):
        value = value.to_dict("records")
    if not isinstance(value, list):
        raise ValueError("markers debe ser una lista de diccionarios")
    return [item for item in value if isinstance(item, dict)]


def main():
    input_path, strategy_path = sys.argv[1], sys.argv[2]
    payload = json.loads(open(input_path, "r", encoding="utf-8").read())
    spec = importlib.util.spec_from_file_location("user_strategy", strategy_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "run"):
        raise ValueError("La estrategia debe definir def run(ctx):")
    ctx = Context(payload)
    result = module.run(ctx)
    if result is None:
        result = {}
    n = len(payload["candles"])
    output = {
        "entries": normalize_signal(result.get("entries"), n),
        "exits": normalize_signal(result.get("exits"), n),
        "markers": normalize_markers(result.get("markers")),
        "debug": result.get("debug"),
    }
    print(json.dumps(output, default=str))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print(json.dumps({"error": traceback.format_exc()}))
        sys.exit(1)
'''


def run_strategy_subprocess(code: str, payload: dict[str, Any], timeout_seconds: int) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="trading_lab_strategy_") as temp_dir:
        temp_path = Path(temp_dir)
        input_path = temp_path / "input.json"
        strategy_path = temp_path / "strategy_user.py"
        runner_path = temp_path / "runner.py"
        input_path.write_text(json.dumps(payload, default=str), encoding="utf-8")
        strategy_path.write_text(code, encoding="utf-8")
        runner_path.write_text(RUNNER_SOURCE, encoding="utf-8")

        env = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": os.environ.get("PYTHONPATH", ""),
            "MPLBACKEND": "Agg",
        }
        process = subprocess.run(
            [sys.executable, str(runner_path), str(input_path), str(strategy_path)],
            cwd=temp_dir,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        stdout = process.stdout.strip()
        if process.returncode != 0:
            try:
                payload = json.loads(stdout.splitlines()[-1]) if stdout else {}
            except json.JSONDecodeError:
                payload = {}
            error = payload.get("error") or process.stderr or stdout or "Strategy failed"
            raise RuntimeError(error[:4000])
        try:
            return json.loads(stdout.splitlines()[-1])
        except (IndexError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"La estrategia no devolvio JSON valido: {stdout[:500]}") from exc
