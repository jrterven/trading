from __future__ import annotations

import re
import uuid

from ..config import Settings, get_settings
from ..db import as_utc_naive, connection, rows_to_dicts
from ..schemas import StrategyRecord, StrategySaveRequest
from ..time_utils import utc_now


class StrategyService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def save(self, request: StrategySaveRequest) -> StrategyRecord:
        created_at = utc_now()
        strategy_id = str(uuid.uuid4())
        name = request.name.strip() or "Untitled strategy"
        file_path = self._write_strategy_file(strategy_id, name, request.code)

        with connection(self.settings) as con:
            con.execute(
                """
                INSERT INTO strategies (id, name, code, file_path, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    strategy_id,
                    name,
                    request.code,
                    str(file_path),
                    as_utc_naive(created_at),
                    as_utc_naive(created_at),
                ],
            )

        return StrategyRecord(
            id=strategy_id,
            name=name,
            code=request.code,
            file_path=str(file_path),
            created_at=created_at,
            updated_at=created_at,
        )

    def list(self, limit: int = 50) -> list[StrategyRecord]:
        with connection(self.settings) as con:
            rows = rows_to_dicts(
                con.execute(
                    """
                    SELECT id, name, code, file_path, created_at, updated_at
                    FROM strategies
                    WHERE file_path IS NOT NULL
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    [limit],
                )
            )
        return [StrategyRecord(**row) for row in rows]

    def _write_strategy_file(self, strategy_id: str, name: str, code: str):
        directory = self.settings.data_dir / "strategies"
        directory.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", name.strip().lower()).strip("-") or "strategy"
        path = directory / f"{slug}-{strategy_id[:8]}.py"
        path.write_text(code, encoding="utf-8")
        return path
