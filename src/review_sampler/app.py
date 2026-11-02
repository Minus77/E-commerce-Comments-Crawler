from __future__ import annotations

from contextlib import asynccontextmanager
from csv import writer
import io
from pathlib import Path
import shutil
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from review_sampler.platforms import PlatformName, ParsedProduct, parse_product, platform_catalog
from review_sampler.service import TaskService
from review_sampler.store import Store


CSV_COLUMNS = [
    "platform",
    "product_id",
    "platform_review_id",
    "author",
    "title",
    "content",
    "rating",
    "created_at_text",
    "created_at",
    "variant",
    "verified_purchase",
    "helpful_count",
    "source_url",
]
STATIC_DIR = Path(__file__).with_name("static")


class CreateTaskRequest(BaseModel):
    platform: PlatformName | None = None
    product: str = Field(min_length=1, max_length=8192)
    mode: Literal["auto", "browser", "demo"] = "auto"
    limit: int = Field(default=100, ge=1, le=5000)
    browser_consent: bool = False
    review_filter: Literal["all", "negative", "positive"] = "all"


def _browser_available() -> bool:
    return bool(
        Path("/Applications/Google Chrome.app").exists()
        or shutil.which("google-chrome")
        or shutil.which("chrome")
        or shutil.which("chromium")
    )


def _public_task(task: dict | None) -> dict | None:
    if task is None:
        return None
    result = dict(task)
    result.pop("cursor", None)
    return result


def _csv_cell(value):
    if not isinstance(value, str):
        return value
    cleaned = value.replace("\x00", "")
    if cleaned.startswith(("=", "+", "-", "@")):
        return f"'{cleaned}"
    return cleaned


def _review_filters(
    task_id: str,
    *,
    platform: str | None = None,
    product_id: str | None = None,
    rating: int | None = None,
    q: str | None = None,
    verified: bool | None = None,
) -> dict:
    return {
        "task_id": task_id,
        "platform": platform,
        "product_id": product_id,
        "rating": rating,
        "query": q,
        "verified": verified,
    }


def create_app(store: Store, service: TaskService) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        store.recover_interrupted()
        yield

    application = FastAPI(
        title="评论采样台",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.mount(
        "/static",
        StaticFiles(directory=STATIC_DIR),
        name="static",
    )

    @application.get("/", include_in_schema=False)
    def workspace():
        return FileResponse(STATIC_DIR / "index.html", media_type="text/html")

    @application.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, _exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={"detail": "请求参数不正确，请检查商品、平台或采集上限。"},
        )

    @application.get("/api/platforms")
    def platforms():
        return {"platforms": platform_catalog(_browser_available())}

    @application.post("/api/tasks", status_code=202)
    def create_task(payload: CreateTaskRequest):
        raw = payload.product.strip()
        if payload.platform == "demo":
            parsed = ParsedProduct("demo", raw, "")
        else:
            try:
                parsed = parse_product(payload.platform, raw)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        browser_needed = (
            parsed.platform != "demo"
            and (payload.mode == "browser" or parsed.platform != "jd")
        )
        if browser_needed and not payload.browser_consent:
            raise HTTPException(
                status_code=422,
                detail=(
                    "此平台需要浏览器协助。请确认你会在本机浏览器中自行完成登录和验证。"
                ),
            )
        task = store.create_task(
            platform=parsed.platform,
            product_id=parsed.product_id,
            input_url=raw if raw.startswith(("http://", "https://")) else None,
            mode=payload.mode,
            limit=payload.limit,
            review_filter=payload.review_filter,
            browser_consent=payload.browser_consent,
        )
        service.submit(task["id"])
        return _public_task(store.get_task(task["id"]))

    @application.post("/api/demo", status_code=202)
    def create_demo(limit: int = Query(default=6, ge=1, le=24)):
        task = store.create_task("demo", "DEMO-001", None, "demo", limit)
        service.submit(task["id"])
        return _public_task(store.get_task(task["id"]))

    @application.get("/api/tasks")
    def list_tasks(limit: int = Query(default=100, ge=1, le=5000)):
        return {"tasks": [_public_task(item) for item in store.list_tasks(limit)]}

    @application.get("/api/tasks/{task_id}")
    def get_task(task_id: str):
        task = store.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="采集任务不存在")
        return {"task": _public_task(task)}

    @application.post("/api/tasks/{task_id}/continue", status_code=202)
    def continue_task(task_id: str):
        try:
            task = service.continue_task(task_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="采集任务不存在") from exc
        return {"task": _public_task(task)}

    @application.post("/api/tasks/{task_id}/cancel", status_code=202)
    def cancel_task(task_id: str):
        try:
            task = service.cancel(task_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="采集任务不存在") from exc
        return {"task": _public_task(task)}

    @application.get("/api/reviews")
    def reviews(
        task_id: str | None = None,
        platform: str | None = None,
        product_id: str | None = None,
        rating: int | None = Query(default=None, ge=1, le=5),
        q: str | None = None,
        verified: bool | None = None,
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=5000),
    ):
        filters = {
            "task_id": task_id,
            "platform": platform,
            "product_id": product_id,
            "rating": rating,
            "query": q,
            "verified": verified,
        }
        items = store.list_reviews(
            **filters,
            offset=offset,
            limit=limit,
        )
        return {
            "reviews": items,
            "total": store.count_reviews(**filters),
            "offset": offset,
            "limit": limit,
        }

    def export_data(
        task_id: str,
        *,
        platform: str | None,
        product_id: str | None,
        rating: int | None,
        q: str | None,
        verified: bool | None,
    ):
        task = store.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="采集任务不存在")
        filters = _review_filters(
            task_id,
            platform=platform,
            product_id=product_id,
            rating=rating,
            q=q,
            verified=verified,
        )
        items = store.list_reviews(**filters, limit=5000)
        return _public_task(task), items

    @application.get("/api/tasks/{task_id}/export.csv")
    def export_csv(
        task_id: str,
        platform: str | None = None,
        product_id: str | None = None,
        rating: int | None = Query(default=None, ge=1, le=5),
        q: str | None = None,
        verified: bool | None = None,
    ):
        _task, items = export_data(
            task_id,
            platform=platform,
            product_id=product_id,
            rating=rating,
            q=q,
            verified=verified,
        )
        output = io.StringIO(newline="")
        csv_writer = writer(output)
        csv_writer.writerow(CSV_COLUMNS)
        for review in items:
            csv_writer.writerow(
                [_csv_cell(review.get(column)) for column in CSV_COLUMNS]
            )
        content = ("\ufeff" + output.getvalue()).encode("utf-8")
        return Response(
            content=content,
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="reviews-{task_id}.csv"'
                )
            },
        )

    @application.get("/api/tasks/{task_id}/export.json")
    def export_json(
        task_id: str,
        platform: str | None = None,
        product_id: str | None = None,
        rating: int | None = Query(default=None, ge=1, le=5),
        q: str | None = None,
        verified: bool | None = None,
    ):
        task, items = export_data(
            task_id,
            platform=platform,
            product_id=product_id,
            rating=rating,
            q=q,
            verified=verified,
        )
        return {"task": task, "reviews": items}

    return application
