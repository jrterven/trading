from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Any


RUNNER_SOURCE = r'''
import contextlib
import importlib.util
import io
import json
import sys
import time
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
        raise ValueError("entries/exits must be lists, pandas Series, or boolean arrays")
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
        raise ValueError("markers must be a list of dictionaries")
    return [item for item in value if isinstance(item, dict)]


def main():
    input_path, strategy_path = sys.argv[1], sys.argv[2]
    started_at = time.monotonic()
    payload = json.loads(open(input_path, "r", encoding="utf-8").read())
    spec = importlib.util.spec_from_file_location("user_strategy", strategy_path)
    module = importlib.util.module_from_spec(spec)
    user_stdout = io.StringIO()
    try:
        with contextlib.redirect_stdout(user_stdout):
            spec.loader.exec_module(module)
            if not hasattr(module, "run"):
                raise ValueError("The strategy must define def run(ctx):")
            ctx = Context(payload)
            result = module.run(ctx)
    except Exception:
        print(json.dumps({
            "error": traceback.format_exc(),
            "stdout": user_stdout.getvalue(),
            "runtime_seconds": time.monotonic() - started_at,
            "python_executable": sys.executable,
        }, default=str))
        sys.exit(1)
    if result is None:
        result = {}
    n = len(payload["candles"])
    output = {
        "entries": normalize_signal(result.get("entries"), n),
        "exits": normalize_signal(result.get("exits"), n),
        "markers": normalize_markers(result.get("markers")),
        "debug": result.get("debug"),
        "stdout": user_stdout.getvalue(),
        "runtime_seconds": time.monotonic() - started_at,
        "python_executable": sys.executable,
    }
    print(json.dumps(output, default=str))


if __name__ == "__main__":
    main()
'''


@dataclass
class StrategyExecutionError(Exception):
    message: str
    stdout_text: str | None = None
    stderr_text: str | None = None
    debug: Any | None = None
    runtime_seconds: float | None = None
    python_executable: str | None = None

    def __str__(self) -> str:
        return self.message


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
        started_at = time.monotonic()
        try:
            process = subprocess.run(
                [sys.executable, str(runner_path), str(input_path), str(strategy_path)],
                cwd=temp_dir,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            stdout_text = _extract_stdout_text(exc.stdout)
            stderr_text = _decode_output(exc.stderr)
            raise StrategyExecutionError(
                f"Strategy timed out after {timeout_seconds} seconds",
                stdout_text=stdout_text,
                stderr_text=stderr_text,
                runtime_seconds=time.monotonic() - started_at,
                python_executable=sys.executable,
            ) from exc
        stdout = process.stdout.strip()
        if process.returncode != 0:
            try:
                payload = json.loads(stdout.splitlines()[-1]) if stdout else {}
            except json.JSONDecodeError:
                payload = {}
            error = payload.get("error") or process.stderr or stdout or "Strategy failed"
            raise StrategyExecutionError(
                error[:4000],
                stdout_text=payload.get("stdout") or _extract_stdout_text(stdout),
                stderr_text=process.stderr,
                debug=payload.get("debug"),
                runtime_seconds=payload.get("runtime_seconds") or time.monotonic() - started_at,
                python_executable=payload.get("python_executable") or sys.executable,
            )
        try:
            result = json.loads(stdout.splitlines()[-1])
            result["stderr"] = process.stderr
            result.setdefault("runtime_seconds", time.monotonic() - started_at)
            result.setdefault("python_executable", sys.executable)
            return result
        except (IndexError, json.JSONDecodeError) as exc:
            raise StrategyExecutionError(
                f"The strategy did not return valid JSON: {stdout[:500]}",
                stdout_text=_extract_stdout_text(stdout),
                stderr_text=process.stderr,
                runtime_seconds=time.monotonic() - started_at,
                python_executable=sys.executable,
            ) from exc


def strategy_environment(default_timeout_seconds: int) -> dict[str, Any]:
    packages = {}
    for name in ["pandas", "numpy", "torch", "transformers", "vectorbt"]:
        packages[name] = _package_info(name)

    cuda_available = False
    cuda_device_count = 0
    cuda_device_name = None
    try:
        import torch

        cuda_available = bool(torch.cuda.is_available())
        cuda_device_count = int(torch.cuda.device_count()) if cuda_available else 0
        if cuda_device_count:
            cuda_device_name = str(torch.cuda.get_device_name(0))
    except Exception:
        pass

    return {
        "python_executable": sys.executable,
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "strategy_timeout_seconds": default_timeout_seconds,
        "packages": packages,
        "cuda_available": cuda_available,
        "cuda_device_count": cuda_device_count,
        "cuda_device_name": cuda_device_name,
    }


def _package_info(name: str) -> dict[str, Any]:
    try:
        return {"installed": True, "version": metadata.version(name)}
    except metadata.PackageNotFoundError:
        return {"installed": False, "version": None}


def _decode_output(value: str | bytes | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _extract_stdout_text(stdout: str | bytes | None) -> str | None:
    text = _decode_output(stdout)
    if not text:
        return None
    lines = text.splitlines()
    if not lines:
        return text
    try:
        payload = json.loads(lines[-1])
        if isinstance(payload, dict) and "stdout" in payload:
            return payload.get("stdout")
    except json.JSONDecodeError:
        pass
    return "\n".join(lines[:-1]) if len(lines) > 1 else text
