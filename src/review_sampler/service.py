from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Condition, Event, RLock, Thread

from review_sampler.collectors.base import (
    BrowserUnavailable,
    TaskCancelled,
    VerificationRequired,
)
from review_sampler.models import ReviewDraft
from review_sampler.store import Store


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class _Execution:
    cancelled: Event = field(default_factory=Event)
    condition: Condition = field(default_factory=Condition)
    paused: str | None = None


class CollectRuntime:
    def __init__(self, service: TaskService, task: dict, execution: _Execution):
        self.service = service
        self.store = service.store
        self.task = task
        self.execution = execution
        self.saved_count = int(task["collected_count"])

    def checkpoint(self) -> None:
        if self.execution.cancelled.is_set():
            raise TaskCancelled()

    def emit(self, reviews: list[ReviewDraft], cursor: str | None) -> int:
        self.checkpoint()
        remaining = max(0, int(self.task["limit"]) - self.saved_count)
        selected = reviews[:remaining]
        inserted = self.store.upsert_reviews(self.task["id"], selected)
        self.saved_count += inserted
        self.store.update_task(
            self.task["id"],
            collected_count=self.saved_count,
            cursor=cursor,
        )
        return inserted

    def pause(self, kind: str, message: str) -> None:
        self.service._pause(self.task["id"], self.execution, kind, message)


class TaskService:
    def __init__(self, store: Store, collectors: dict):
        self.store = store
        self.collectors = collectors
        self._lock = RLock()
        self._active: dict[str, _Execution] = {}

    def _claim(self, task_id: str) -> tuple[_Execution | None, bool]:
        task = self.store.get_task(task_id)
        if task is None:
            raise KeyError(task_id)
        if task["status"] in {"completed", "cancelled"}:
            return None, False
        with self._lock:
            if task_id in self._active:
                return self._active[task_id], False
            execution = _Execution()
            self._active[task_id] = execution
            return execution, True

    def run_now(self, task_id: str) -> dict | None:
        execution, acquired = self._claim(task_id)
        if execution is None or not acquired:
            return self.store.get_task(task_id)
        return self._execute(task_id, execution)

    def submit(self, task_id: str) -> dict | None:
        task = self.store.get_task(task_id)
        if task is None:
            raise KeyError(task_id)
        if task["status"] in {"completed", "cancelled"}:
            return task
        execution, acquired = self._claim(task_id)
        if execution is None or not acquired:
            return task
        thread = Thread(
            target=self._execute,
            args=(task_id, execution),
            name=f"review-task-{task_id[:8]}",
            daemon=True,
        )
        thread.start()
        return task

    def _execute(self, task_id: str, execution: _Execution) -> dict:
        try:
            task = self.store.get_task(task_id)
            if task is None:
                raise KeyError(task_id)
            self.store.update_task(
                task_id,
                status="running",
                status_reason="正在读取评论，已保存的数据会保留。",
                started_at=task["started_at"] or _now(),
                error_code=None,
                finished_at=None,
            )
            collector = self.collectors.get(task["platform"])
            if collector is None:
                self._fail(
                    task_id,
                    "UNSUPPORTED",
                    "当前没有可用的采集通道。已有数据会保留，请检查平台能力或改用演示模式。",
                )
                return self.store.get_task(task_id)
            runtime = CollectRuntime(self, task, execution)
            collector.collect(task, runtime)
            if execution.cancelled.is_set():
                raise TaskCancelled()
            current = self.store.get_task(task_id)
            self.store.update_task(
                task_id,
                status="completed",
                status_reason=(
                    f"本次采集已结束，共保存 {current['collected_count']} 条评论。"
                ),
                finished_at=_now(),
                error_code=None,
            )
        except TaskCancelled:
            current = self.store.get_task(task_id)
            self.store.update_task(
                task_id,
                status="cancelled",
                status_reason=(
                    f"任务已停止。已保存 {current['collected_count']} 条评论。"
                ),
                finished_at=_now(),
                error_code=None,
            )
        except VerificationRequired as exc:
            self.store.update_task(
                task_id,
                status="needs_user",
                status_reason=exc.message,
                error_code="VERIFICATION_REQUIRED",
            )
        except BrowserUnavailable:
            self._fail(
                task_id,
                "UNSUPPORTED",
                "浏览器协助不可用，请安装 Chrome 并确认 Playwright 已安装。",
            )
        except ValueError:
            self._fail(
                task_id,
                "PARSE_ERROR",
                "平台返回的数据无法解析。已保存数据仍在，请稍后重试。",
            )
        except (TimeoutError, ConnectionError):
            self._fail(
                task_id,
                "NETWORK_ERROR",
                "连接平台时发生网络错误。已保存数据仍在，请稍后重试。",
            )
        except Exception:
            self._fail(
                task_id,
                "PARSE_ERROR",
                "采集过程意外停止。已保存数据仍在，请检查页面后重试。",
            )
        finally:
            with self._lock:
                if self._active.get(task_id) is execution:
                    self._active.pop(task_id, None)
        return self.store.get_task(task_id)

    def _fail(self, task_id: str, code: str, reason: str) -> None:
        task = self.store.get_task(task_id)
        self.store.update_task(
            task_id,
            status="failed",
            status_reason=reason,
            error_code=code,
            attempts=int(task["attempts"]) + 1,
            finished_at=_now(),
        )

    def _pause(
        self,
        task_id: str,
        execution: _Execution,
        kind: str,
        message: str,
    ) -> None:
        with execution.condition:
            if execution.cancelled.is_set():
                raise TaskCancelled()
            code = {
                "login": "AUTH_REQUIRED",
                "authorization": "AUTH_REQUIRED",
                "verification": "VERIFICATION_REQUIRED",
                "page_confirmation": "VERIFICATION_REQUIRED",
            }.get(kind, "VERIFICATION_REQUIRED")
            self.store.update_task(
                task_id,
                status="needs_user",
                status_reason=message,
                error_code=code,
            )
            execution.paused = kind
            execution.condition.notify_all()
            while execution.paused is not None:
                if execution.cancelled.is_set():
                    raise TaskCancelled()
                execution.condition.wait(timeout=0.2)
            if execution.cancelled.is_set():
                raise TaskCancelled()
            self.store.update_task(
                task_id,
                status="running",
                status_reason="正在读取评论，已保存的数据会保留。",
                error_code=None,
            )

    def continue_task(self, task_id: str) -> dict | None:
        task = self.store.get_task(task_id)
        if task is None:
            raise KeyError(task_id)
        with self._lock:
            execution = self._active.get(task_id)
        if execution is None:
            if task["status"] in {"needs_user", "interrupted"}:
                self.submit(task_id)
            return self.store.get_task(task_id)
        with execution.condition:
            if execution.paused is not None:
                execution.paused = None
                execution.condition.notify_all()
        return self.store.get_task(task_id)

    def cancel(self, task_id: str) -> dict | None:
        task = self.store.get_task(task_id)
        if task is None:
            raise KeyError(task_id)
        with self._lock:
            execution = self._active.get(task_id)
        if execution is None:
            if task["status"] not in {"completed", "cancelled"}:
                self.store.update_task(
                    task_id,
                    status="cancelled",
                    status_reason=(
                        f"任务已停止。已保存 {task['collected_count']} 条评论。"
                    ),
                    finished_at=_now(),
                    error_code=None,
                )
            return self.store.get_task(task_id)
        with execution.condition:
            execution.cancelled.set()
            execution.condition.notify_all()
        return self.store.get_task(task_id)
