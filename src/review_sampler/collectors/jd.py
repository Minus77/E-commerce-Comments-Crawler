from __future__ import annotations

import json
import re

from review_sampler.collectors.base import VerificationRequired
from review_sampler.net import AccessDenied, PacedClient, RateLimited
from review_sampler.normalize import looks_like_challenge, normalize_payload


class JdCollector:
    URL = "https://club.jd.com/comment/skuProductPageComments.action"
    CALLBACK = "fetchJSON_comment98vv1941"
    FILTERS = {"all": "0", "negative": "1", "positive": "2"}
    _JSONP = re.compile(
        rf"^{CALLBACK}\((.*)\);?\s*$",
        flags=re.DOTALL,
    )

    def __init__(self, client: PacedClient):
        self.client = client

    def _payload(self, raw: str) -> dict:
        match = self._JSONP.fullmatch(raw.strip())
        if not match:
            if any(
                marker in raw
                for marker in ("活动太火爆", "请求过于频繁", "请稍微再试")
            ):
                raise RateLimited("京东暂时限制了评论请求")
            if looks_like_challenge(self.URL, raw[:2000], raw):
                raise VerificationRequired(
                    "京东要求登录或人工验证。请在浏览器中处理，然后继续任务。",
                    kind="authorization",
                )
            raise ValueError("京东评论响应不再使用支持的 JSONP 格式")
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError as exc:
            raise ValueError("京东评论响应不是有效 JSON") from exc
        if not isinstance(payload, dict) or not isinstance(
            payload.get("comments", []), list
        ):
            raise ValueError("京东评论响应缺少有效的评论列表")
        return payload

    def collect(self, task: dict, runtime) -> None:
        limit = int(task["limit"])
        if runtime.saved_count >= limit:
            return
        previous_page = int(task.get("cursor") or 0)
        start_page = previous_page + 1
        page = start_page
        source_url = (
            task.get("input_url")
            or f"https://item.jd.com/{task['product_id']}.html"
        )
        filter_name = task.get("review_filter") or "all"
        score = self.FILTERS.get(filter_name, "0")
        seen_responses: set[str] = set()

        while runtime.saved_count < limit:
            runtime.checkpoint()
            try:
                raw = self.client.get_text(
                    self.URL,
                    params={
                        "callback": self.CALLBACK,
                        "productId": task["product_id"],
                        "score": score,
                        "sortType": "5",
                        "pageSize": "10",
                        "isShadowSku": "0",
                        "page": str(page),
                        "fold": "1",
                    },
                    headers={"Referer": source_url},
                )
            except AccessDenied as exc:
                raise VerificationRequired(
                    "京东要求登录或人工验证。请在浏览器中处理，然后继续任务。",
                    kind="authorization",
                ) from exc

            if raw in seen_responses:
                break
            seen_responses.add(raw)
            payload = self._payload(raw)
            comments = payload.get("comments") or []
            if not comments:
                if page > start_page:
                    runtime.emit([], str(page))
                break

            reviews = normalize_payload(
                "jd",
                task["product_id"],
                payload,
                source_url,
            )
            remaining = limit - runtime.saved_count
            runtime.emit(reviews[:remaining], str(page))

            max_page = int(payload.get("maxPage") or 0)
            if max_page and page >= max_page:
                break
            page += 1
