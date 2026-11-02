# 跨平台商品评论工作台实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把原京东单平台脚本改造成可创建、恢复、去重、筛选和导出的本机跨平台评论工作台。

**Architecture:** FastAPI 同时提供本地 API 和静态前端；SQLite 保存任务与评论；同步型采集器由应用内线程运行。京东走可受限速控制的 HTTP 采集，其他平台在用户明确确认后交给有头 Playwright 读取页面已加载的数据；验证出现时任务暂停，不绕过。

**Tech Stack:** Python 3.11+、FastAPI、Uvicorn、httpx、Playwright、SQLite、原生 HTML/CSS/JavaScript、pytest

**Spec:** `docs/superpowers/specs/2026-11-02-multiplatform-review-collector-design.md`

## Global Constraints

- 只监听 `127.0.0.1`，首版是单用户本机应用。
- 状态只使用 `queued`、`running`、`needs_user`、`interrupted`、`completed`、`failed`、`cancelled`。
- 普通请求间隔不小于 800 ms；429 优先使用 `Retry-After`，否则按 1、2、4、8、16 秒指数退避，最多重试 3 次。
- 不实现代理轮换、指纹伪装、自动点击登录/验证或验证码破解。
- 不保存密码、完整 Cookie、验证码截图或请求头中的令牌。
- 浏览器会话写入 `runtime/browser-state/`，数据库写入 `runtime/review-sampler.sqlite3`，二者均加入 `.gitignore`。
- 评论内容按纯文本输出；CSV 导出必须防公式注入。
- 默认界面中文，产品与架构文档交付中英文版本。
- 每个任务在独立测试通过后提交；不能在失败测试仍存在时推进。

## Review Focus

- CSV 中的 `=HYPERLINK(...)`、`+cmd`、`-2+3`、`@SUM(...)` 被表格软件执行：导出时应转义为普通文本。
- 用户在两次运行之间切换商品大小写、空白或 URL 参数：同一评论应去重，同一商品应复用已有记录。
- 服务重启恰逢浏览器任务正在等待：任务应变为 `interrupted`，已有评论保留，不能继续显示 `running`。
- 评论正文含换行、引号、HTML、超长文本或 NUL 字符：界面不执行 HTML，CSV/JSON 仍保持可读。
- 页面登录成功后又出现验证码或 429：采集立即暂停或退避，不能继续当作普通页面滚动。

---

### Task 1: 项目骨架、商品输入与持久化

**Files:**
- Create: `.gitignore`
- Create: `pyproject.toml`
- Create: `src/review_sampler/__init__.py`
- Create: `src/review_sampler/models.py`
- Create: `src/review_sampler/platforms.py`
- Create: `src/review_sampler/store.py`
- Create: `tests/conftest.py`
- Create: `tests/test_platforms.py`
- Create: `tests/test_store.py`

**Interfaces:**
- Consumes: 无。
- Produces:
  - `PlatformName = Literal["jd", "taobao", "pdd", "amazon", "demo"]`
  - `ParsedProduct(platform: str, product_id: str, source_url: str)`
  - `parse_product(platform: str | None, raw: str) -> ParsedProduct`
  - `platform_catalog(browser_available: bool) -> list[dict]`
  - `ReviewDraft`：字段 `platform`, `product_id`, `platform_review_id`, `fingerprint`, `author`, `title`, `content`, `rating`, `created_at_text`, `created_at`, `variant`, `verified_purchase`, `helpful_count`, `source_url`
  - `Store(path: Path)`，以及 `create_task`, `get_task`, `list_tasks`, `update_task`, `upsert_reviews`, `list_reviews`, `count_reviews`, `recover_interrupted` 方法。

- [ ] **Step 1: 建立依赖与测试入口**

`pyproject.toml` 使用 `setuptools`，包目录为 `src`；运行时依赖固定为 FastAPI、Uvicorn、httpx、Playwright 和 Beautiful Soup，测试依赖为 pytest。pytest 配置加入 `src` 到导入路径，并把 `runtime/`、`.venv/`、会话目录和导出文件写入 `.gitignore`。

- [ ] **Step 2: 安装依赖并确认空基线**

Run: `python3 -m venv .venv && .venv/bin/python -m pip install -e '.[test]'`

Expected: 安装成功，`.venv/bin/pytest --version` 输出版本号。

Run: `.venv/bin/pytest -q`

Expected: `no tests ran`，退出码 5；这是测试收集前的基线。

- [ ] **Step 3: 写商品输入解析的失败测试**

```python
import pytest
from review_sampler.platforms import parse_product

@pytest.mark.parametrize(("platform", "raw", "expected"), [
    ("jd", "https://item.jd.com/100012043978.html", ("jd", "100012043978")),
    ("taobao", "https://detail.tmall.com/item.htm?id=654321&spm=x", ("taobao", "654321")),
    ("pdd", "https://mobile.yangkeduo.com/goods.html?goods_id=987654", ("pdd", "987654")),
    ("amazon", "https://www.amazon.co.uk/dp/B0D1234567?th=1", ("amazon", "B0D1234567")),
])
def test_parse_supported_product_urls(platform, raw, expected):
    product = parse_product(platform, raw)
    assert (product.platform, product.product_id) == expected

def test_bare_digit_id_requires_platform():
    with pytest.raises(ValueError, match="请选择商品所在平台"):
        parse_product(None, "100012043978")

def test_amazon_asin_is_uppercased():
    assert parse_product("amazon", "b0d1234567").product_id == "B0D1234567"
```

补充测试：拒绝主机名包含 `jd.com.evil.test` 的伪链接；拒绝 Amazon 非 `/dp/`、`/gp/product/`、`/product-reviews/` 路径；裸京东/淘宝/拼多多 ID 只接受数字，Amazon ASIN 只接受 10 位字母数字。

- [ ] **Step 4: 运行解析测试，确认 RED**

Run: `.venv/bin/pytest tests/test_platforms.py -q`

Expected: FAIL，原因是 `review_sampler.platforms` 或 `parse_product` 尚不存在。

- [ ] **Step 5: 实现输入解析与能力目录**

用 `urllib.parse.urlsplit` 读取主机和查询参数，不使用会误匹配子域后缀的正则。裸 ID 在 `platform=None` 时抛出 `ValueError("请选择商品所在平台")`。`platform_catalog` 返回四个平台的名称、自动接口状态、浏览器协助状态和一句限制说明；`demo` 只用于演示。

不要解析或请求短链接；短链接返回 `ValueError("短链接无法离线解析，请粘贴最终商品地址或商品 ID")`。

- [ ] **Step 6: 运行解析测试，确认 GREEN**

Run: `.venv/bin/pytest tests/test_platforms.py -q`

Expected: PASS。

- [ ] **Step 7: 写持久化的失败测试**

```python
from review_sampler.models import ReviewDraft
from review_sampler.store import Store

def test_review_upsert_is_idempotent(tmp_path):
    store = Store(tmp_path / "data.sqlite3")
    task = store.create_task(
        platform="jd", product_id="100012043978",
        input_url=None, mode="auto", limit=100,
    )
    review = ReviewDraft(
        platform="jd", product_id="100012043978", platform_review_id="r1",
        fingerprint="f" * 64, author="A", title="", content="很好用",
        rating=5, created_at_text="2026-10-01", created_at=None,
        variant="", verified_purchase=None, helpful_count=0,
        source_url="https://item.jd.com/100012043978.html",
    )
    assert store.upsert_reviews(task["id"], [review]) == 1
    assert store.upsert_reviews(task["id"], [review]) == 0
    assert store.count_reviews(task_id=task["id"]) == 1
```

再覆盖：相同平台商品但评论 ID 不同、指纹相同应去重；不同商品相同指纹可共存；评论筛选按关键词、评分和平台生效；`recover_interrupted()` 只把 `running` 和 `queued` 改为 `interrupted`。

- [ ] **Step 8: 运行持久化测试，确认 RED**

Run: `.venv/bin/pytest tests/test_store.py -q`

Expected: FAIL，原因是数据模型或 `Store` 尚不存在。

- [ ] **Step 9: 实现 SQLite 存储**

连接参数使用 `check_same_thread=False`、`timeout=5`，首次连接执行 `PRAGMA journal_mode=WAL`。创建任务返回完整字典。`upsert_reviews` 在一个事务内写入标准字段，分别用评论 ID 和指纹约束处理冲突，冲突时只更新 `last_seen_at` 与原本为空的字段，并返回新增行数。

列表查询支持：

```text
task_id, platform, product_id, rating, query, verified, offset=0, limit=100
```

`query` 只检索 `author`、`title`、`content`；`limit` 上限 5000。时间字段统一保存为 UTC ISO 8601 字符串。

- [ ] **Step 10: 运行本阶段测试**

Run: `.venv/bin/pytest tests/test_platforms.py tests/test_store.py -q`

Expected: 全部 PASS，无 warning。

- [ ] **Step 11: 提交**

```bash
git add .gitignore pyproject.toml src/review_sampler tests
git commit -m "feat: add product parsing and review storage"
```

---

### Task 2: 任务引擎、演示通道与本地 API

**Files:**
- Create: `src/review_sampler/collectors/__init__.py`
- Create: `src/review_sampler/collectors/base.py`
- Create: `src/review_sampler/collectors/demo.py`
- Create: `src/review_sampler/service.py`
- Create: `src/review_sampler/app.py`
- Create: `src/review_sampler/main.py`
- Create: `tests/test_service.py`
- Create: `tests/test_api.py`

**Interfaces:**
- Consumes: Task 1 的 `Store`, `parse_product`, `ReviewDraft`。
- Produces:
  - `Collector.collect(task: dict, runtime: CollectRuntime) -> None`
  - `CollectRuntime.emit(reviews: list[ReviewDraft], cursor: str | None) -> int`
  - `CollectRuntime.pause(kind: str, message: str) -> None`
  - `CollectRuntime.checkpoint() -> None`，取消时抛 `TaskCancelled`
  - `TaskService(store, collectors)`，方法 `submit`, `run_now`, `continue_task`, `cancel`
  - `create_app(store: Store, service: TaskService) -> FastAPI`
  - CLI：`python -m review_sampler`

- [ ] **Step 1: 写任务状态与演示采集的失败测试**

```python
def test_demo_task_completes_and_is_exportable(tmp_path):
    store = Store(tmp_path / "data.sqlite3")
    service = TaskService(store, {"demo": DemoCollector()})
    task = store.create_task(
        platform="demo", product_id="DEMO-001", input_url=None,
        mode="demo", limit=6,
    )
    service.run_now(task["id"])
    done = store.get_task(task["id"])
    assert done["status"] == "completed"
    assert done["collected_count"] == 6
    assert store.count_reviews(task_id=task["id"]) == 6
```

再覆盖：重复 `run_now` 不重复保存；未知平台变成 `failed`；采集器抛普通异常时写入 `failed` 和稳定错误码；`cancel` 后采集器看到的取消检查抛 `TaskCancelled`。

- [ ] **Step 2: 运行任务测试，确认 RED**

Run: `.venv/bin/pytest tests/test_service.py -q`

Expected: FAIL，原因是采集器、运行时或 `TaskService` 尚不存在。

- [ ] **Step 3: 实现任务运行时与演示通道**

`DemoCollector` 根据任务上限生成确定性的 24 条中文样例评论，覆盖 1–5 分、不同作者、换行和带引号内容。`TaskService` 用锁保护活动任务集合；`run_now` 在调用线程执行，`submit` 才创建 daemon 线程。运行时每批调用 `emit` 保存评论，再更新游标与数量。

任务进入 `running` 时写入 `started_at`。成功设置 `completed` 和 `finished_at`。异常映射到：

```text
TaskCancelled -> cancelled
ValueError -> PARSE_ERROR
TimeoutError/ConnectionError -> NETWORK_ERROR
其他异常 -> PARSE_ERROR，错误文案不得包含堆栈或凭证
```

- [ ] **Step 4: 运行任务测试，确认 GREEN**

Run: `.venv/bin/pytest tests/test_service.py -q`

Expected: PASS。

- [ ] **Step 5: 写 API 的失败测试**

```python
def test_create_demo_task_and_query_reviews(client, wait_for_task):
    response = client.post("/api/tasks", json={
        "platform": "demo", "product": "DEMO-001",
        "mode": "demo", "limit": 3, "browser_consent": False,
    })
    assert response.status_code == 202
    task = wait_for_task(response.json()["id"])
    assert task["status"] == "completed"
    reviews = client.get(f"/api/reviews?task_id={task['id']}").json()
    assert reviews["total"] == 3
```

再覆盖：平台能力列表；创建请求的 limit 边界 1 和 5000；短链接 422；浏览器平台未勾选同意时 422；重复继续不会重复启动；未知任务 404；筛选结果；CSV 中文 BOM、引号、换行和公式注入；JSON 导出结构。

- [ ] **Step 6: 运行 API 测试，确认 RED**

Run: `.venv/bin/pytest tests/test_api.py -q`

Expected: FAIL，原因是应用工厂和路由尚不存在。

- [ ] **Step 7: 实现 FastAPI 应用**

`create_app` 使用给定 `Store` 和 `TaskService` 构造应用，测试不依赖全局数据库。实现设计文档列出的平台、任务和评论路由；创建任务成功返回 202，浏览器平台缺少同意时返回 422。

CSV 列顺序固定为：

```text
platform,product_id,platform_review_id,author,title,content,rating,
created_at_text,created_at,variant,verified_purchase,helpful_count,source_url
```

CSV 使用 UTF-8 BOM；每个文本单元格若以 `=`, `+`, `-`, `@` 开头，在前面加单引号。JSON 顶层返回 `task` 和 `reviews`，不包含本地路径或游标。所有 FastAPI 错误使用 `{"detail": "面向用户的中文说明"}`。

- [ ] **Step 8: 实现启动入口与重启恢复**

`python -m review_sampler` 在 `127.0.0.1:8765` 启动 Uvicorn。应用 lifespan 开始时调用 `recover_interrupted()`；数据库默认路径为 `runtime/review-sampler.sqlite3`。启动时不得打印数据库中的评论或会话内容。

- [ ] **Step 9: 运行完整测试**

Run: `.venv/bin/pytest -q`

Expected: 全部 PASS。

- [ ] **Step 10: 启动服务做 API 冒烟**

Run: `(.venv/bin/python -m review_sampler > runtime/server.log 2>&1 &) && sleep 1 && curl -fsS http://127.0.0.1:8765/api/platforms`

Expected: 返回四个平台和 demo 的能力 JSON，进程正常监听 `127.0.0.1:8765`。

- [ ] **Step 11: 提交并推送**

```bash
git add src/review_sampler tests
git commit -m "feat: add resumable task API and demo collector"
git push
```

---

### Task 3: 京东采集、限速、重试与浏览器入口

**Files:**
- Create: `src/review_sampler/net.py`
- Create: `src/review_sampler/collectors/jd.py`
- Create: `src/review_sampler/collectors/browser.py`
- Create: `src/review_sampler/normalize.py`
- Create: `tests/fixtures/jd_page_1.json`
- Create: `tests/fixtures/platform_payloads.json`
- Create: `tests/fixtures/amazon_reviews.html`
- Create: `tests/test_net.py`
- Create: `tests/test_jd.py`
- Create: `tests/test_normalize.py`
- Modify: `src/review_sampler/service.py`
- Modify: `src/review_sampler/app.py`
- Modify: `tests/test_service.py`
- Modify: `tests/test_api.py`

**Interfaces:**
- Consumes: Task 2 的 `Collector`, `CollectRuntime`, `TaskService`。
- Produces:
  - `async` 不进入接口；`PacedClient.get_json(url, params, headers=None) -> dict`，内部同步使用 httpx。
  - `JdCollector(client: PacedClient).collect(task, runtime) -> None`
  - `normalize_payload(platform: str, product_id: str, payload: object, source_url: str) -> list[ReviewDraft]`
  - `parse_dom_reviews(platform: str, product_id: str, html: str, source_url: str) -> list[ReviewDraft]`
  - `looks_like_challenge(url: str, title: str, body_text: str) -> bool`
  - `BrowserCollector(...).collect(task, runtime) -> None`

- [ ] **Step 1: 写限速与退避的失败测试**

```python
def test_retry_after_wins_over_backoff(monkeypatch):
    sleeps = []
    monkeypatch.setattr("review_sampler.net.time.sleep", sleeps.append)
    client = PacedClient(min_interval=0, max_retries=2)
    delay = client.retry_delay(attempt=1, retry_after="7")
    assert delay == 7.0

def test_non_retryable_403_raises_access_denied():
    client = PacedClient(min_interval=0, max_retries=3)
    with pytest.raises(AccessDenied):
        client.raise_for_status(403)
```

补充：429 三次后抛 `RateLimited`；500 三次后抛 `NetworkError`；400 立即失败；两个线程共享同一平台限速器时调用开始时间相差至少 0.8 秒。

- [ ] **Step 2: 运行网络测试，确认 RED**

Run: `.venv/bin/pytest tests/test_net.py -q`

Expected: FAIL，原因是 `review_sampler.net` 尚不存在。

- [ ] **Step 3: 实现最小 HTTP 客户端**

`PacedClient` 使用进程内锁保证同一实例请求间隔。最大重试次数 3，退避上限 16 秒并加 0–250 ms 抖动；`Retry-After` 支持整数秒和 HTTP 日期。错误类映射到稳定任务错误码。日志只记录 URL 主机、状态码和尝试次数。

- [ ] **Step 4: 运行网络测试，确认 GREEN**

Run: `.venv/bin/pytest tests/test_net.py -q`

Expected: PASS。

- [ ] **Step 5: 写京东采集的失败测试**

`tests/fixtures/jd_page_1.json` 保存一个 JSONP 响应，其中严格 callback 为 `fetchJSON_comment98vv1941`，包含 3 条评论。测试注入 `httpx.MockTransport`：

```python
def test_jd_collects_comments_and_stops_at_limit(store, runtime):
    collector = JdCollector(client=client_returning_fixture)
    task = task_for("jd", limit=2)
    collector.collect(task, runtime)
    assert runtime.saved_count == 2
    assert runtime.cursors[-1] == "1"
```

再覆盖：空 `comments` 结束；没有 `maxPage` 时连续空页结束；JSONP 壳变化为 malformed JSON 时抛 `ValueError`；评论缺少内容或作者时跳过但保留合法评论；按 `score=1` 创建的任务只把差评参数传给请求。

- [ ] **Step 6: 运行京东测试，确认 RED**

Run: `.venv/bin/pytest tests/test_jd.py -q`

Expected: FAIL，原因是 `JdCollector` 尚不存在。

- [ ] **Step 7: 实现京东采集器**

请求 `https://club.jd.com/comment/skuProductPageComments.action`，参数保持原脚本语义：`productId`, `score`, `sortType=5`, `pageSize=10`, `isShadowSku=0`, `page`, `fold=1`。固定 JSONP 壳只接受仓库原有的 callback；页面返回 HTML、登录页或验证提示时抛 `VerificationRequired`，不要静默结束。每页调用 `runtime.emit`，最后把 `cursor` 更新为请求页码。

任务没有“评论类型”字段时固定使用 `score=0`。新增任务请求字段 `review_filter: Literal["all", "negative", "positive"] = "all"`，映射为 0/1/2。

- [ ] **Step 8: 运行京东测试，确认 GREEN**

Run: `.venv/bin/pytest tests/test_jd.py -q`

Expected: PASS。

- [ ] **Step 9: 写评论标准化与页面解析的失败测试**

`platform_payloads.json` 为四个平台各提供一条常见字段组合。测试断言四者都生成非空 `fingerprint`，并把评分文本 `"5.0 out of 5 stars"` 转为 5。另覆盖：

```python
def test_fingerprint_ignores_whitespace_changes():
    a = normalize_payload("jd", "1", {"comments": [{"id": "7", "content": "很好  用", "nickname": "A"}]}, "")
    b = normalize_payload("jd", "1", {"comments": [{"id": "7", "content": " 很好 用 ", "nickname": "A"}]}, "")
    assert a[0].fingerprint == b[0].fingerprint

def test_script_text_stays_inert_string():
    reviews = normalize_payload("taobao", "2", {"rateList": [{"rateContent": "<script>alert(1)</script>", "id": "9"}]}, "")
    assert reviews[0].content == "<script>alert(1)</script>"
```

再覆盖：递归数组、嵌套分页对象、未知字段不抛异常、负评分丢弃、超长正文截断到 20,000 字符、Amazon fixture DOM 解析、挑战 URL 和标题识别、商品评论正文中出现“登录”不会单独触发验证状态。

- [ ] **Step 10: 运行标准化测试，确认 RED**

Run: `.venv/bin/pytest tests/test_normalize.py -q`

Expected: FAIL，原因是标准化和 DOM 解析函数尚不存在。

- [ ] **Step 11: 实现标准化与浏览器采集器**

JSON 提取使用字段别名和“至少包含内容及一个身份/时间/评分字段”的规则，递归深度上限 8。DOM 解析只实现 Amazon 和京东的明确结构；淘宝/拼多多以网络 JSON 为主，解析不到时返回 `PARSE_ERROR`。标准化后按指纹做批次内去重。

`BrowserCollector` 用 `playwright.sync_api` 启动 `channel="chrome"` 的有头浏览器，持久化上下文位于 `runtime/browser-state/`。页面打开后先 `runtime.pause("login", ...)`；用户继续后监听 XHR/fetch 响应，最多滚动 8 轮，每轮等待 1 秒，连续两轮无新评论结束。检测到登录、验证码、滑块、风控或 `429` 马上暂停。用户继续后仍无法读取时抛出 `VerificationRequired` 或 `ValueError`，保留已提交批次。

Playwright 不可用或 Chrome 无法启动时抛 `BrowserUnavailable("浏览器协助不可用，请先安装 Chrome 并运行 pip install -e .[browser]")`，任务变为 `failed`。

- [ ] **Step 12: 接入服务与 API**

`TaskService` 根据平台选择采集器：`demo -> DemoCollector`，`jd + auto -> JdCollector`，其余 `auto/browser -> BrowserCollector`。`POST /api/tasks/{id}/continue` 唤醒暂停的运行时；`POST /api/tasks/{id}/cancel` 同时唤醒并设置取消标记。浏览器平台创建时 `browser_consent` 必须为 `true`。

- [ ] **Step 13: 运行全部测试**

Run: `.venv/bin/pytest -q`

Expected: 全部 PASS；真实网络和真实浏览器测试默认标记为跳过或手工执行。

- [ ] **Step 14: 手工冒烟**

Run: `(.venv/bin/python -m review_sampler > runtime/server.log 2>&1 &)`

用一个公开京东商品 ID 创建最多 10 条评论的任务。检查：首个请求至少间隔 800 ms；成功时有记录；验证或 403 时任务显示可处置错误。若当前网络触发平台验证，记录为“需人工处理”，不尝试绕过。

- [ ] **Step 15: 提交并推送**

```bash
git add src/review_sampler tests
git commit -m "feat: add paced collectors and browser handoff"
git push
```

---

### Task 4: 原生前端工作台

**Files:**
- Create: `src/review_sampler/static/index.html`
- Create: `src/review_sampler/static/app.css`
- Create: `src/review_sampler/static/app.js`
- Modify: `src/review_sampler/app.py`
- Create: `tests/test_frontend.py`

**Interfaces:**
- Consumes: Task 2 和 Task 3 的 API。
- Produces: `GET /` 返回中文工作台；静态资源位于 `/static`；所有网络错误显示服务端 `detail`。

- [ ] **Step 1: 写静态入口的失败测试**

```python
def test_workspace_page_contains_real_controls(client):
    html = client.get("/").text
    assert 'id="task-form"' in html
    assert "商品链接或 ID" in html
    assert 'aria-live="polite"' in html
    assert "载入演示" in html
```

再断言页面没有内联事件属性（如 `onclick=`），评论结果模板使用 `<p class="review-content">`，以及 CSS 文件可通过 `/static/app.css` 获取。

- [ ] **Step 2: 运行前端入口测试，确认 RED**

Run: `.venv/bin/pytest tests/test_frontend.py -q`

Expected: FAIL，原因是根路由或静态页面尚不存在。

- [ ] **Step 3: 实现桌面与移动布局**

视觉方向按设计文档“跨平台采样台账”执行：

- 冷灰纸面 `#EEF2EF`，墨蓝 `#172B36`，钴蓝 `#2146C7`，验证琥珀 `#A15C13`。
- 标题用 `Iowan Old Style`/`Songti SC`，正文用 `Avenir Next`/`PingFang SC`。
- 顶部一个宽幅标题和平台能力条；主体为左任务轨道与右记录区，使用连续分隔线，不套重复卡片。
- 主操作固定叫“开始采样”；等待用户时固定叫“页面已处理，继续”。
- 状态变化只做一次颜色和进度过渡；遵守 `prefers-reduced-motion`。
- 390 px 宽度下把任务轨道移入可折叠区域，表单和结果保持单列。

实现空状态、表单错误、任务列表、状态详情、评分/关键词/已验证筛选、结果台账和导出按钮。所有用户数据通过 `textContent` 或安全 DOM API 插入，禁止 `innerHTML` 拼评论正文。

- [ ] **Step 4: 实现前端行为**

首次加载调用 `/api/platforms` 和 `/api/tasks`。平台切换时更新 URL 示例和限制说明。创建任务后选择该任务并每 1.5 秒轮询活跃状态。`needs_user` 显示原因与继续按钮；`interrupted` 显示恢复按钮；失败显示已保存数量、错误码和重试入口。演示按钮创建 `demo/DEMO-001` 任务。

筛选参数与导出链接保持一致。导出时对 `q`、`rating` 和 `verified` 使用 `URLSearchParams`，不手工拼字符串。

- [ ] **Step 5: 运行服务并用浏览器检查**

Run: `(.venv/bin/python -m review_sampler > runtime/server.log 2>&1 &)`

在 Chrome 中打开 `http://127.0.0.1:8765`，分别检查 1440×900 和 390×844：

- 载入演示后可看到至少 6 条评论。
- 键盘 Tab 顺序可完成创建、切换任务和导出。
- 焦点环清楚；正文和按钮对比度达到 WCAG AA。
- 页面无控制台错误；网络失败时提示可理解。
- 截图保存到 `runtime/screenshots/desktop.png` 与 `runtime/screenshots/mobile.png` 供人工复核，文件不提交。

- [ ] **Step 6: 运行全部自动化测试**

Run: `.venv/bin/pytest -q`

Expected: 全部 PASS。

- [ ] **Step 7: 提交并推送**

```bash
git add src/review_sampler/static src/review_sampler/app.py tests/test_frontend.py
git commit -m "feat: add review workspace interface"
git push
```

---

### Task 5: 中英双语产品与架构文档

**Files:**
- Modify: `README.md`
- Create: `docs/product/user-guide.zh-CN.md`
- Create: `docs/product/user-guide.en.md`
- Create: `docs/architecture/architecture.zh-CN.md`
- Create: `docs/architecture/architecture.en.md`
- Create: `docs/platform-policy.md`
- Create: `src/review_sampler/static/fixtures/demo_reviews.csv`

**Interfaces:**
- Consumes: 已实现功能和测试结果。
- Produces: 默认中文的入口文档；中英文功能说明；中英文架构说明；平台能力与限制说明；可复制的启动、演示、浏览器协助、导入、筛选和导出步骤。

- [ ] **Step 1: 写产品使用文档中文稿**

覆盖安装、启动、四平台输入、浏览器同意、人工验证、状态含义、筛选、导出、重启恢复、清除会话和数据位置。每个步骤给出真实按钮名称和预期结果。对“没有授权”和“页面结构变化”提供具体处理办法。

- [ ] **Step 2: 使用 humanizer-zh 编辑中文稿**

逐段检查空泛铺垫、重复、假对比、宣传语和套话；保留版本、条件、限制、平台政策和数据状态。命令、URL、表头、状态名和代码块保持原样。编辑完成后对照事实清单，确认没有新增性能、覆盖率或平台兼容性结论。

- [ ] **Step 3: 写对应英文产品文档**

英文版逐项对应中文步骤和警告，不添加新的能力承诺。平台专有名词和状态码不翻译。术语统一使用 `task`、`review`、`browser-assisted`、`verification` 和 `export`。

- [ ] **Step 4: 写架构文档**

包含系统图、任务状态机、数据表、去重规则、采集器接口、并发边界、限速/重试、浏览器会话位置、安全约束和扩展新平台步骤。引用源代码路径和关键测试名称，不复制整段实现。

- [ ] **Step 5: 写平台限制页**

摘要调研结论并链接 `docs/research/2026-11-02-platform-access.md`。明确四个平台的输入、可用通道和限制，尤其是 Amazon Creators API 不含评论资源、淘宝/拼多多需平台许可、只处理用户可正常查看的数据。

- [ ] **Step 6: 更新 README 和演示数据**

README 默认中文，顶部链接英文产品文档；替换“仅抓京东 HP 打印机评论”的旧描述。演示 CSV 包含至少 3 条，覆盖评分、换行和公式前缀，确保导入/导出说明与实际文件一致。

- [ ] **Step 7: 检查中英文一致性与 Markdown**

Run: `rg -n 'TODO|TBD|仅限 HP|仅抓取京东|unlimited|无限' README.md docs`

Expected: 没有遗留占位内容或错误承诺。

Run: `git diff --check`

Expected: 无输出。

- [ ] **Step 8: 完成最终验证**

Run: `.venv/bin/pytest -q`

Expected: 全部 PASS，0 skipped 的浏览器单元测试；真实网络手工测试不计入默认测试。

Run: `.venv/bin/python -m review_sampler` 后访问 `http://127.0.0.1:8765`，按中文文档从零走一次演示流程、筛选和两种导出。

Expected: 文档步骤与界面一致，下载文件可打开，公开 API 只绑定本机。

- [ ] **Step 9: 提交并推送**

```bash
git add README.md docs src/review_sampler/static/fixtures
git commit -m "docs: add bilingual product and architecture guides"
git push
```

---

## 计划自检记录

- 规格覆盖：输入、状态、去重、续采、错误、限速、浏览器边界、导出、安全、前端、中英文文档均有对应任务。
- 接口一致性：任务由 `TaskService` 运行，采集器只通过 `CollectRuntime` 写数据和暂停；API 只调用服务层。
- 未实现项会在界面和文档标明，不用未授权接口或虚假成功补齐。
- 真实平台验证受账号、地区和页面变化影响，默认测试使用固定响应与页面夹具；上线后需按平台单独做手工冒烟。
