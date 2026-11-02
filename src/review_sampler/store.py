from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from threading import RLock
from uuid import uuid4

from review_sampler.models import ReviewDraft


STATUSES = {
    "queued",
    "running",
    "needs_user",
    "interrupted",
    "completed",
    "failed",
    "cancelled",
}
_TASK_FIELDS = {
    "status": "status",
    "status_reason": "status_reason",
    "collected_count": "collected_count",
    "cursor": "cursor",
    "attempts": "attempts",
    "started_at": "started_at",
    "finished_at": "finished_at",
    "error_code": "error_code",
    "limit": "limit_count",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._db = sqlite3.connect(
            self.path,
            timeout=5,
            check_same_thread=False,
        )
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.execute("PRAGMA busy_timeout=5000")
        self._create_schema()

    def _create_schema(self) -> None:
        with self._lock, self._db:
            self._db.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    platform TEXT NOT NULL,
                    product_id TEXT NOT NULL,
                    input_url TEXT,
                    mode TEXT NOT NULL,
                    limit_count INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    status_reason TEXT NOT NULL DEFAULT '',
                    collected_count INTEGER NOT NULL DEFAULT 0,
                    cursor TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    error_code TEXT
                );

                CREATE TABLE IF NOT EXISTS reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                    platform TEXT NOT NULL,
                    product_id TEXT NOT NULL,
                    platform_review_id TEXT,
                    fingerprint TEXT NOT NULL,
                    author TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL DEFAULT '',
                    content TEXT NOT NULL,
                    rating INTEGER,
                    created_at_text TEXT NOT NULL DEFAULT '',
                    created_at TEXT,
                    variant TEXT NOT NULL DEFAULT '',
                    verified_purchase INTEGER,
                    helpful_count INTEGER NOT NULL DEFAULT 0,
                    source_url TEXT NOT NULL DEFAULT '',
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    UNIQUE (platform, product_id, fingerprint)
                );

                CREATE UNIQUE INDEX IF NOT EXISTS reviews_platform_id
                ON reviews(platform, product_id, platform_review_id)
                WHERE platform_review_id IS NOT NULL;

                CREATE INDEX IF NOT EXISTS reviews_task_id
                ON reviews(task_id);

                CREATE INDEX IF NOT EXISTS reviews_product_id
                ON reviews(platform, product_id);
                """
            )

    @staticmethod
    def _task_dict(row: sqlite3.Row) -> dict:
        result = dict(row)
        result["limit"] = result.pop("limit_count")
        return result

    def create_task(
        self,
        platform: str,
        product_id: str,
        input_url: str | None,
        mode: str,
        limit: int,
    ) -> dict:
        if not platform or not product_id.strip():
            raise ValueError("商品平台和商品 ID 不能为空")
        if not 1 <= int(limit) <= 5000:
            raise ValueError("采集上限必须在 1 到 5000 之间")
        task_id = str(uuid4())
        now = _now()
        with self._lock, self._db:
            self._db.execute(
                """
                INSERT INTO tasks (
                    id, platform, product_id, input_url, mode, limit_count,
                    status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'queued', ?, ?)
                """,
                (task_id, platform, product_id, input_url, mode, limit, now, now),
            )
        return self.get_task(task_id)

    def get_task(self, task_id: str) -> dict | None:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
        return self._task_dict(row) if row else None

    def list_tasks(self, limit: int = 100) -> list[dict]:
        bounded = max(0, min(int(limit), 5000))
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM tasks ORDER BY created_at DESC, id DESC LIMIT ?",
                (bounded,),
            ).fetchall()
        return [self._task_dict(row) for row in rows]

    def update_task(self, task_id: str, **fields) -> dict | None:
        updates: list[str] = []
        values: list[object] = []
        for key, value in fields.items():
            column = _TASK_FIELDS.get(key)
            if column is None:
                raise ValueError(f"不支持更新任务字段：{key}")
            if key == "status" and value not in STATUSES:
                raise ValueError("不支持的任务状态")
            updates.append(f"{column} = ?")
            values.append(value)
        if not updates:
            return self.get_task(task_id)
        updates.append("updated_at = ?")
        values.extend([_now(), task_id])
        with self._lock, self._db:
            cursor = self._db.execute(
                f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?",
                values,
            )
        return self.get_task(task_id) if cursor.rowcount else None

    def _filters(
        self,
        *,
        task_id: str | None = None,
        platform: str | None = None,
        product_id: str | None = None,
        rating: int | None = None,
        query: str | None = None,
        verified: bool | None = None,
    ) -> tuple[str, list[object]]:
        clauses: list[str] = []
        values: list[object] = []
        for column, value in (
            ("task_id", task_id),
            ("platform", platform),
            ("product_id", product_id),
            ("rating", rating),
        ):
            if value is not None:
                clauses.append(f"{column} = ?")
                values.append(value)
        if query:
            escaped = (
                query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            )
            pattern = f"%{escaped}%"
            clauses.append(
                "(author LIKE ? ESCAPE '\\' OR title LIKE ? ESCAPE '\\' "
                "OR content LIKE ? ESCAPE '\\')"
            )
            values.extend([pattern, pattern, pattern])
        if verified is not None:
            clauses.append("verified_purchase = ?")
            values.append(1 if verified else 0)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        return where, values

    def count_reviews(self, **filters) -> int:
        where, values = self._filters(**filters)
        with self._lock:
            row = self._db.execute(
                f"SELECT COUNT(*) FROM reviews{where}", values
            ).fetchone()
        return int(row[0])

    def list_reviews(
        self,
        *,
        task_id: str | None = None,
        platform: str | None = None,
        product_id: str | None = None,
        rating: int | None = None,
        query: str | None = None,
        verified: bool | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[dict]:
        where, values = self._filters(
            task_id=task_id,
            platform=platform,
            product_id=product_id,
            rating=rating,
            query=query,
            verified=verified,
        )
        bounded = max(0, min(int(limit), 5000))
        with self._lock:
            rows = self._db.execute(
                f"SELECT * FROM reviews{where} "
                "ORDER BY first_seen_at, id LIMIT ? OFFSET ?",
                [*values, bounded, max(0, int(offset))],
            ).fetchall()
        return [dict(row) for row in rows]

    def upsert_reviews(self, task_id: str, reviews: list[ReviewDraft]) -> int:
        if not reviews:
            return 0
        inserted = 0
        now = _now()
        with self._lock, self._db:
            if not self._db.execute(
                "SELECT 1 FROM tasks WHERE id = ?", (task_id,)
            ).fetchone():
                raise ValueError("采集任务不存在")
            self._db.execute("BEGIN IMMEDIATE")
            try:
                for review in reviews:
                    existing = self._db.execute(
                        """
                        SELECT * FROM reviews
                        WHERE platform = ? AND product_id = ?
                          AND (
                            fingerprint = ?
                            OR (? IS NOT NULL AND platform_review_id = ?)
                          )
                        LIMIT 1
                        """,
                        (
                            review.platform,
                            review.product_id,
                            review.fingerprint,
                            review.platform_review_id,
                            review.platform_review_id,
                        ),
                    ).fetchone()
                    if existing is not None:
                        self._db.execute(
                            """
                            UPDATE reviews SET
                                last_seen_at = ?,
                                platform_review_id = CASE
                                    WHEN platform_review_id IS NULL
                                    THEN ? ELSE platform_review_id END,
                                author = CASE
                                    WHEN TRIM(author) = '' THEN ? ELSE author END,
                                title = CASE
                                    WHEN TRIM(title) = '' THEN ? ELSE title END,
                                content = CASE
                                    WHEN TRIM(content) = '' THEN ? ELSE content END,
                                rating = COALESCE(rating, ?),
                                created_at_text = CASE
                                    WHEN TRIM(created_at_text) = ''
                                    THEN ? ELSE created_at_text END,
                                created_at = COALESCE(created_at, ?),
                                variant = CASE
                                    WHEN TRIM(variant) = '' THEN ? ELSE variant END,
                                verified_purchase = COALESCE(
                                    verified_purchase, ?
                                ),
                                helpful_count = MAX(helpful_count, ?),
                                source_url = CASE
                                    WHEN TRIM(source_url) = '' THEN ? ELSE source_url END
                            WHERE id = ?
                            """,
                            (
                                now,
                                review.platform_review_id,
                                review.author,
                                review.title,
                                review.content,
                                review.rating,
                                review.created_at_text,
                                review.created_at,
                                review.variant,
                                None
                                if review.verified_purchase is None
                                else int(review.verified_purchase),
                                max(0, int(review.helpful_count)),
                                review.source_url,
                                existing["id"],
                            ),
                        )
                        continue
                    self._db.execute(
                        """
                        INSERT INTO reviews (
                            task_id, platform, product_id, platform_review_id,
                            fingerprint, author, title, content, rating,
                            created_at_text, created_at, variant,
                            verified_purchase, helpful_count, source_url,
                            first_seen_at, last_seen_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            task_id,
                            review.platform,
                            review.product_id,
                            review.platform_review_id,
                            review.fingerprint,
                            review.author,
                            review.title,
                            review.content,
                            review.rating,
                            review.created_at_text,
                            review.created_at,
                            review.variant,
                            None
                            if review.verified_purchase is None
                            else int(review.verified_purchase),
                            max(0, int(review.helpful_count)),
                            review.source_url,
                            now,
                            now,
                        ),
                    )
                    inserted += 1
                self._db.commit()
            except Exception:
                self._db.rollback()
                raise
        return inserted

    def recover_interrupted(self) -> int:
        now = _now()
        with self._lock, self._db:
            cursor = self._db.execute(
                """
                UPDATE tasks
                SET status = 'interrupted',
                    status_reason = '本地服务在任务完成前停止，已保存的数据仍在。',
                    error_code = 'INTERRUPTED',
                    updated_at = ?
                WHERE status IN ('queued', 'running')
                """,
                (now,),
            )
        return cursor.rowcount
