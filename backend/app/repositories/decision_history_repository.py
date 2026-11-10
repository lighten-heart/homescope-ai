"""使用SQLite保存和查询决策历史。"""

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError
from pydantic_core import PydanticSerializationError

from app.core.config import BACKEND_DIR, get_settings
from app.models.history import (
    DecisionHistoryDetail,
    DecisionHistorySummary,
)
from app.models.schemas import (
    HousingDecisionRequest,
    MultiAgentDecisionResult,
)

class HistoryStorageError(RuntimeError):
    """历史记录保存或读取失败。"""

class DecisionHistoryRepository:
    """只保存数据库路径，每次操作使用独立连接。"""
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        """创建连接、准备数据表、管理事务并关闭连接。"""

        try:
            self.db_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            with closing(
                sqlite3.connect(
                    self.db_path,
                    timeout=5.0,
                )
            ) as connection:

                # 查询结果可以按字段名访问。
                connection.row_factory = sqlite3.Row

                # 正常结束时提交，发生异常时回滚。
                with connection:
                    # 创建数据表。
                    connection.execute(
                        """
                        CREATE TABLE IF NOT EXISTS decision_history (
                            id TEXT PRIMARY KEY,
                            created_at TEXT NOT NULL,
                            city TEXT NOT NULL,
                            monthly_budget INTEGER NOT NULL,
                            recommended_candidate_id TEXT NOT NULL,
                            payload_json TEXT NOT NULL
                        )
                        """
                    )

                    # 创建索引，按创建时间倒序查询历史列表。
                    connection.execute(
                        """
                        CREATE INDEX IF NOT EXISTS
                        idx_decision_history_created
                        ON decision_history (
                            created_at DESC,
                            id DESC
                        )
                        """
                    )

                    yield connection

        except (
            OSError,
            sqlite3.Error,
            ValidationError,
            PydanticSerializationError,
        ) as exc:
            # 不把文件路径、SQL细节或历史内容暴露给接口调用者。
            raise HistoryStorageError(
                "历史记录保存或读取失败"
            ) from exc

    def save(
        self,
        request: HousingDecisionRequest,
        result: MultiAgentDecisionResult,
    ) -> str:
        """保存一个完整快照，提交成功后返回记录ID。"""

        with self._connection() as connection:
            record = DecisionHistoryDetail(
                id=str(uuid4()),
                created_at=datetime.now(timezone.utc),
                city=request.city,
                monthly_budget=request.monthly_budget,
                recommended_candidate_id=(
                    result.recommended_candidate_id
                ),
                request=request,
                result=result,
            )
            connection.execute(
                """
                INSERT INTO decision_history (
                    id,
                    created_at,
                    city,
                    monthly_budget,
                    recommended_candidate_id,
                    payload_json
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.created_at.isoformat(
                        timespec="microseconds"
                    ),
                    record.city,
                    record.monthly_budget,
                    record.recommended_candidate_id,
                    record.model_dump_json(),
                ),
            )
        # 离开上面的with后，事务已经提交并关闭连接。
        return record.id

    def list_recent(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> list[DecisionHistorySummary]:
        """按保存时间从新到旧分页查询摘要。"""

        if not 1 <= limit <= 100:
            raise ValueError("limit必须在1到100之间")

        if offset < 0:
            raise ValueError("offset不能小于0")

        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT
                    id,
                    created_at,
                    city,
                    monthly_budget,
                    recommended_candidate_id
                FROM decision_history
                ORDER BY created_at DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()

            return [
                DecisionHistorySummary.model_validate(
                    dict(row)
                )
                for row in rows
            ]

    def get(
        self,
        record_id: str,
    ) -> DecisionHistoryDetail | None:
        """查询完整快照；记录不存在时返回None。"""

        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT payload_json
                FROM decision_history
                WHERE id = ?
                """,
                (record_id,),
            ).fetchone()

            if row is None:
                return None

            # 不直接返回未经检查的数据库JSON。
            return DecisionHistoryDetail.model_validate_json(
                row["payload_json"]
            )

@lru_cache
def get_decision_history_repository() -> DecisionHistoryRepository:
    """返回共享仓库对象，但不共享数据库连接。"""

    path = get_settings().history_db_path

    if not path.is_absolute():
        path = BACKEND_DIR / path

    return DecisionHistoryRepository(
        db_path=path.resolve(),
    )