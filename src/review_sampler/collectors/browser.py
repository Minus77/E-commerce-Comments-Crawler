from __future__ import annotations

from pathlib import Path

from review_sampler.collectors.base import BrowserUnavailable, VerificationRequired
from review_sampler.normalize import (
    looks_like_challenge,
    normalize_payload,
    parse_dom_reviews,
)
from review_sampler.platforms import parse_product


class BrowserCollector:
    def __init__(
        self,
        state_dir: str | Path = "runtime/browser-state",
        *,
        rounds: int = 8,
    ):
        self.state_dir = Path(state_dir)
        self.rounds = max(1, int(rounds))

    def collect(self, task: dict, runtime) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise BrowserUnavailable(
                "浏览器协助不可用，请安装 Chrome 并运行 pip install -e .[browser]"
            ) from exc

        platform = task["platform"]
        source_url = task.get("input_url") or parse_product(
            platform, task["product_id"]
        ).source_url
        state_path = self.state_dir / platform
        state_path.mkdir(parents=True, exist_ok=True)
        payloads: list[object] = []
        challenge = {"seen": False}

        with sync_playwright() as playwright:
            try:
                context = playwright.chromium.launch_persistent_context(
                    str(state_path),
                    channel="chrome",
                    headless=False,
                    no_viewport=True,
                    args=["--start-maximized"],
                )
            except Exception as exc:
                raise BrowserUnavailable(
                    "浏览器协助不可用，请安装 Chrome 并运行 pip install -e .[browser]"
                ) from exc

            try:
                page = context.pages[0] if context.pages else context.new_page()

                def on_response(response):
                    if response.status == 429:
                        challenge["seen"] = True
                    content_type = response.headers.get("content-type", "")
                    if "json" not in content_type.lower():
                        return
                    try:
                        payloads.append(response.json())
                    except Exception:
                        return

                page.on("response", on_response)
                page.goto(
                    source_url,
                    wait_until="domcontentloaded",
                    timeout=45_000,
                )
                page.bring_to_front()
                runtime.pause(
                    "login",
                    (
                        "浏览器已打开。请在该窗口完成登录或验证，并进入评论列表，"
                        "然后回到工作台点击“继续”。"
                    ),
                )

                self._drain(payloads, task, runtime, page.url)
                if self._is_challenge(page):
                    challenge["seen"] = True
                    runtime.pause(
                        "verification",
                        "页面仍要求验证。请在浏览器中处理，然后继续。",
                    )

                blank_rounds = 0
                for _ in range(self.rounds):
                    runtime.checkpoint()
                    before = runtime.saved_count
                    page.mouse.wheel(0, 1800)
                    page.wait_for_timeout(1000)
                    self._drain(payloads, task, runtime, page.url)
                    self._emit_dom(page, task, runtime)
                    if self._is_challenge(page):
                        challenge["seen"] = True
                        runtime.pause(
                            "verification",
                            "页面要求验证。请在浏览器中处理，然后继续。",
                        )
                        self._drain(payloads, task, runtime, page.url)
                    blank_rounds = (
                        blank_rounds + 1
                        if runtime.saved_count == before
                        else 0
                    )
                    if runtime.saved_count >= int(task["limit"]):
                        break
                    if blank_rounds >= 2:
                        break

                if runtime.saved_count == 0:
                    if challenge["seen"]:
                        raise VerificationRequired(
                            "页面要求验证，当前无法读取可见评论。"
                        )
                    raise ValueError(
                        "页面中没有识别到可见评论。请打开评论列表后重试。"
                    )
            finally:
                context.close()

    @staticmethod
    def _drain(payloads: list[object], task: dict, runtime, url: str) -> None:
        while payloads and runtime.saved_count < int(task["limit"]):
            payload = payloads.pop(0)
            reviews = normalize_payload(
                task["platform"],
                task["product_id"],
                payload,
                url,
            )
            if reviews:
                runtime.emit(
                    reviews[: max(0, int(task["limit"]) - runtime.saved_count)],
                    url,
                )

    @staticmethod
    def _emit_dom(page, task: dict, runtime) -> None:
        if runtime.saved_count >= int(task["limit"]):
            return
        reviews = parse_dom_reviews(
            task["platform"],
            task["product_id"],
            page.content(),
            page.url,
        )
        if reviews:
            runtime.emit(
                reviews[: max(0, int(task["limit"]) - runtime.saved_count)],
                page.url,
            )

    @staticmethod
    def _is_challenge(page) -> bool:
        try:
            body = page.locator("body").inner_text(timeout=2_000)
        except Exception:
            body = ""
        return looks_like_challenge(page.url, page.title(), body)
