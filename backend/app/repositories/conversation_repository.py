"""使用SQLite保存会话和需求版本。"""

import json
import sqlite3

from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError
from pydantic_core import PydanticSerializationError

from app.models.conversation import (
    ConversationDetail,
    ConversationVersion,
)
from app.models.history import DecisionHistoryDetail
from app.models.schemas import HousingDecisionRequest


"""建立了一个SQLite会话仓库的基础部分，负责准备数据库、创建表、管理连接和事务，以及统一处理存储错误"""

"""三个异常类：区分不用性质的失败"""
class ConversationNotFoundError(RuntimeError):
    """会话不存在。"""

class ConversationConflictError(RuntimeError):
    """版本过期或结果关联发生冲突。"""

class ConversationStorageError(RuntimeError):
    """会话存储失败。"""

def utc_now() -> str:
    """生成统一格式的时间。"""
    return datetime.now(timezone.utc).isoformat(
        timespec="microseconds"
    )

def request_signature(
    request: HousingDecisionRequest,
) -> str:
    """将需求转换为一个格式稳定，可直接比较的字符串。"""
    data = request.model_dump(mode="json")
    data["preferred_facilities"] = sorted(
    set(data["preferred_facilities"])
    )
    return json.dumps(
    data,
    ensure_ascii=False,
    sort_keys=True,
    separators=(",", ":"),
    )

class ConversationRepository:
    """数据库读写入口"""
    """保存路径，每次操作使用独立连接。"""
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        """提供可自动收尾的数据库环境"""
        try:
            # 创建数据库所在的目录
            self.db_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            # 打开连接，并保证最终关闭
            with closing(
                sqlite3.connect(
                    self.db_path,
                    timeout=5.0,
                )
            ) as connection:
                # 让查询结果可以按列名读取
                connection.row_factory = sqlite3.Row

                # 开启外键检查
                connection.execute(
                    "PRAGMA foreign_keys = ON"
                )

                # 创建会话表和需求版本表
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS
                    conversation_sessions (
                        id TEXT PRIMARY KEY,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        current_version INTEGER NOT NULL
                            CHECK (current_version >= 1)
                    );

                    CREATE TABLE IF NOT EXISTS
                    conversation_versions (
                        session_id TEXT NOT NULL,
                        version INTEGER NOT NULL
                            CHECK (version >= 1),
                        created_at TEXT NOT NULL,
                        request_json TEXT NOT NULL,
                        history_id TEXT,
                        PRIMARY KEY (session_id, version),
                        FOREIGN KEY (session_id)
                            REFERENCES conversation_sessions(id)
                    );
                    """
                )

                with connection:
                    yield connection

        except (
            OSError,
            sqlite3.Error,
            ValidationError,
            PydanticSerializationError,
        ) as exc:
            raise ConversationStorageError(
                "会话保存或读取失败"
            ) from exc


    @staticmethod
    def _version_from_row(
        row: sqlite3.Row,
    ) -> ConversationVersion:
        """数据库行转换为经过校验的版本模型。"""

        return ConversationVersion(
            session_id=row["session_id"],
            version=row["version"],
            created_at=row["created_at"],
            request=(
                HousingDecisionRequest.model_validate_json(
                    row["request_json"]
                )
            ),
            history_id=row["history_id"],
        )

    def _get_current(
        self,
        connection: sqlite3.Connection,
        session_id: str,
    ) -> ConversationDetail:
        """用一次数据库查询读取会话和当前版本。"""

        # 读取会话当前使用的完整需求及其分析结果编号
        row = connection.execute(
            """
            SELECT
                s.id,
                s.created_at AS session_created_at,
                s.updated_at,
                s.current_version,
                v.created_at AS version_created_at,
                v.request_json,
                v.history_id
            FROM conversation_sessions AS s
            JOIN conversation_versions AS v
              ON v.session_id = s.id
             AND v.version = s.current_version
            WHERE s.id = ?
            """,
            (session_id,),
        ).fetchone()

        if row is None:
            raise ConversationNotFoundError(
                "会话不存在"
            )

        current = ConversationVersion(
            session_id=row["id"],
            version=row["current_version"],
            created_at=row["version_created_at"],
            request=(
                HousingDecisionRequest.model_validate_json(
                    row["request_json"]
                )
            ),
            history_id=row["history_id"],
        )

        return ConversationDetail(
            id=row["id"],
            created_at=row["session_created_at"],
            updated_at=row["updated_at"],
            current_version=row["current_version"],
            current=current,
        )

    @staticmethod
    def _check_version(
        detail: ConversationDetail,
        expected_version: int,
    ) -> None:
        # 比较版本
        if detail.current_version != expected_version:
            raise ConversationConflictError(
                "会话版本已变化，请重新读取当前需求后再提交"
            )

    def create(
        self,
        request: HousingDecisionRequest,
    ) -> ConversationDetail:
        # 创建会话，同时保存第一份需求
        session_id = str(uuid4())
        now = utc_now()

        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")

            connection.execute(
                # 保存会话信息
                """
                INSERT INTO conversation_sessions (
                    id,
                    created_at,
                    updated_at,
                    current_version
                )
                VALUES (?, ?, ?, 1)
                """,
                (session_id, now, now),
            )

            connection.execute(
                # 保存第一版完整需求
                """
                INSERT INTO conversation_versions (
                    session_id,
                    version,
                    created_at,
                    request_json,
                    history_id
                )
                VALUES (?, 1, ?, ?, NULL)
                """,
                (
                    session_id,
                    now,
                    request.model_dump_json(),
                ),
            )

            # 读取刚创建的详情，再提交返回
            detail = self._get_current(
                connection,
                session_id,
            )

        return detail

    def get(
        self,
        session_id: str,
    ) -> ConversationDetail:
        # 读取当前会话状态
        with self._connection() as connection:
            return self._get_current(
                connection,
                session_id,
            )

    def list_versions(
        self,
        session_id: str,
        *,
        limit: int = 20,
        offset: int = 0,
    ) -> list[ConversationVersion]:
        # 分页查看所有需求版本
        if not 1 <= limit <= 100:
            raise ValueError("limit必须在1到100之间")

        if offset < 0:
            raise ValueError("offset不能小于0")

        with self._connection() as connection:
            self._get_current(connection, session_id)

            rows = connection.execute(
                """
                SELECT
                    session_id,
                    version,
                    created_at,
                    request_json,
                    history_id
                FROM conversation_versions
                WHERE session_id = ?
                ORDER BY version DESC
                LIMIT ? OFFSET ?
                """,
                (session_id, limit, offset),
            ).fetchall()

            return [
                self._version_from_row(row)
                for row in rows
            ]

    def create_version(
        self,
        session_id: str,
        expected_version: int,
        request: HousingDecisionRequest,
    ) -> ConversationDetail:
        # 新版本保存方法
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")

            detail = self._get_current(
                connection,
                session_id,
            )

            self._check_version(
                detail,
                expected_version,
            )

            next_version = expected_version + 1
            now = utc_now()

            updated = connection.execute(
                """
                UPDATE conversation_sessions
                SET
                    current_version = ?,
                    updated_at = ?
                WHERE id = ?
                  AND current_version = ?
                """,
                (
                    next_version,
                    now,
                    session_id,
                    expected_version,
                ),
            )

            if updated.rowcount != 1:
                raise ConversationConflictError(
                    "更新版本失败，请重新读取会话"
                )

            connection.execute(
                """
                INSERT INTO conversation_versions (
                    session_id,
                    version,
                    created_at,
                    request_json,
                    history_id
                )
                VALUES (?, ?, ?, ?, NULL)
                """,
                (
                    session_id,
                    next_version,
                    now,
                    request.model_dump_json(),
                ),
            )

            result = self._get_current(
                connection,
                session_id,
            )

        return result

    def bind_decision(
        self,
        session_id: str,
        expected_version: int,
        history: DecisionHistoryDetail,
    ) -> ConversationDetail:
        # 历史关联方法
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")

            detail = self._get_current(
                connection,
                session_id,
            )

            self._check_version(
                detail,
                expected_version,
            )

            if request_signature(
                detail.current.request
            ) != request_signature(history.request):
                raise ConversationConflictError(
                    "分析历史的需求与当前版本不一致，不能关联"
                )

            existing_id = detail.current.history_id

            if existing_id is not None:
                if existing_id == history.id:
                    # 重复关联同一条历史，直接返回。
                    return detail

                raise ConversationConflictError(
                    "当前版本已经关联其他分析结果"
                )

            # 更新版本表：只写入历史ID
            connection.execute(
                """
                UPDATE conversation_versions
                SET history_id = ?
                WHERE session_id = ?
                  AND version = ?
                  AND history_id IS NULL
                """,
                (
                    history.id,
                    session_id,
                    expected_version,
                ),
            )

            connection.execute(
                """
                UPDATE conversation_sessions
                SET updated_at = ?
                WHERE id = ?
                """,
                (utc_now(), session_id),
            )

            result = self._get_current(
                connection,
                session_id,
            )

        return result

