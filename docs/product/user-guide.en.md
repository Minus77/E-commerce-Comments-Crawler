# Review Sampler User Guide

[中文](user-guide.zh-CN.md) · [Architecture](../architecture/architecture.en.md) · [Platform policy](../platform-policy.md)

This guide describes version 0.1.0. Button labels below refer to the Chinese interface. State names and error codes use the values stored by the application.

## 1. Scope

Review Sampler is a local tool for personal or small-team review analysis. It turns product identifiers from JD, Taobao/Tmall, PDD, and Amazon into resumable tasks, stores visible reviews, and provides keyword, rating, and purchase-marker filters with CSV and JSON export.

The current collection paths differ by platform:

| Platform | Accepted input | Current collection path | Main limitation |
| --- | --- | --- | --- |
| JD | Numeric product ID; `item.jd.com` or `item.m.jd.com` product URLs | Public comment endpoint first; optional browser assistance | The public endpoint may rate-limit, request verification, or change |
| Taobao/Tmall | Numeric `itemId`; product URLs on `item.taobao.com`, `detail.tmall.com`, `detail.tmall.hk`, or `world.taobao.com` | Browser-assisted collection | Automated APIs require platform authorization; no authorized API adapter is included yet |
| PDD | Numeric `goods_id`; supported `yangkeduo.com` or `pinduoduo.com` product URLs | Browser-assisted collection | Platform permission or a user-visible page is required; no authorized API adapter is included yet |
| Amazon | 10-character alphanumeric ASIN; product URLs on supported regional storefronts | Browser-assisted collection | Creators API does not provide review lists; visibility depends on the storefront, region, and account |

Being able to create a task does not mean the tool can retrieve every review. Platform data availability, the account's view permissions, and verification requirements all affect the result.

One physical product often has different IDs on different platforms. Create a task for each platform item and compare the exports. The current version does not merge product records across platforms and does not import CSV or JSON files.

## 2. Install and start

### 2.1 Requirements

- Python 3.11 or later.
- The JD public path does not require an additional browser.
- Google Chrome is required for Taobao/Tmall, PDD, Amazon, and JD browser fallback.

Run these commands from the repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test,browser]'
.venv/bin/python -m review_sampler
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765).

Start the application from the repository root because its default data paths are relative to the current working directory:

- Database: `runtime/review-sampler.sqlite3`
- Browser state: `runtime/browser-state/<platform>/`

The server always listens on `127.0.0.1:8765`. It has no user authentication or access control. Do not expose the port through a reverse proxy or make it reachable from the network.

### 2.2 Choose another database path

Set `REVIEW_SAMPLER_DB` before the start command:

```bash
REVIEW_SAMPLER_DB=/absolute/path/reviews.sqlite3 .venv/bin/python -m review_sampler
```

A relative value is resolved from the directory where you start the command.

## 3. Walk through the demo

With the server running:

1. Open the local workspace.
2. Click `载入演示`.
3. The application creates a completed task with six reviews.
4. Enter `打印` in `搜索评论` and click `筛选`.
5. Select `5 星` in the rating field and filter again.
6. Click `清除` to show all reviews.
7. Apply a filter and use both `导出 CSV` and `导出 JSON`.

The demo does not contact a platform. It is there to verify the task, filtering, and download flow. The built-in demo contains up to 24 reviews; the `载入演示` button creates six.

## 4. Create a real task

### 4.1 Select a platform and enter an item

Choose the platform in the platform strip at the top of the page. A bare ID always needs an explicit platform. A full product URL can identify its platform, but the selected platform must still match the URL.

Product inputs are validated as follows:

| Platform | Bare ID | URL requirements |
| --- | --- | --- |
| JD | Digits only | Host must be `item.jd.com` or `item.m.jd.com`, with a numeric product ID in the path |
| Taobao/Tmall | Digits only | Supported product host with `id=<number>` in the query string |
| PDD | Digits only | Supported PDD host with `goods_id=<number>` in the query string |
| Amazon | 10 letters or digits, normalized to uppercase | Supports `/dp/<ASIN>`, `/product/<ASIN>`, `/gp/product/<ASIN>`, and `/product-reviews/<ASIN>` |

Amazon URLs must use one of the supported `.amazon.*` storefronts. The application does not expand short links such as `u.jd.com`, `m.tb.cn`, `p.pinduoduo.com`, `a.co`, or `amzn.to`. Open the short link in a browser and paste the final product URL or the original ID.

`最多保存` accepts 1 through 5000. It is a storage cap for the task; it does not mean the platform has that many visible reviews.

### 4.2 Review direction

The `评论方向` options are `全部`, `负面优先`, and `正面优先`. This setting is sent only to the JD public endpoint.

It is disabled for Taobao/Tmall, PDD, and Amazon. Browser-assisted collection does not classify sentiment. Use the rating and keyword filters after collection, or analyze the export later.

If a JD task falls back to the browser, the direction parameter no longer restricts the visible page content. Filter the saved reviews separately.

### 4.3 Browser consent

Taobao/Tmall, PDD, and Amazon require you to check `我会在打开的 Chrome 窗口中自行完成登录和验证` before starting.

JD makes the checkbox optional:

- Unchecked: use only the public comment endpoint.
- Checked: allow a fallback to browser assistance when the public endpoint requires login, verification, or rate limiting stops progress.

Checking the box authorizes the application to open Chrome on this machine and wait for you to handle the platform's own page. It does not give the application a password, and it does not authorize automatic cookie extraction, CAPTCHA solving, or clicking login or verification controls.

## 5. Use browser assistance

Browser assistance uses a dedicated persistent Chrome profile. It does not open or read your everyday Chrome profile. You must log in inside the new window on first use; later tasks on the same platform reuse `runtime/browser-state/<platform>/`.

1. Start the task. Chrome opens the product page.
2. The task moves to `需要你处理` and displays the current reason.
3. Switch to the Chrome window and complete login or verification yourself.
4. Open the product's review section. For Taobao and PDD, wait until reviews have actually loaded. For Amazon, open the visible review list.
5. Return to the workspace and click `页面已处理，继续`.
6. The collector reads reviews already present on the page and performs a limited number of scroll rounds. The task area continues to poll status.
7. If verification appears again, the task returns to `需要你处理`. Complete the page step and continue again.

A browser-assisted task performs at most eight scroll rounds with about one second between rounds. It stops early after two consecutive rounds with no new review. Taobao and PDD primarily depend on JSON responses loaded by the page. JD and Amazon also have parsers for known review markup. A site redesign or field change can produce a parse failure.

The browser state directory may contain identity cookies. Treat `runtime/` as private data. Do not commit, upload, or share it.

### 5.1 JD fallback

When you enabled browser consent, a JD task can move to Chrome after the public endpoint encounters verification, access denial, or rate limiting. Follow the browser steps above if the page asks for a person.

If consent was not enabled, no Chrome window is opened for that task. Clicking `页面已处理，继续` cannot add a browser session to it. Wait for the restriction to clear and retry, or create a new task with browser assistance enabled.

## 6. Task states

Each task uses one of seven states:

| State | UI label | Meaning | Available action |
| --- | --- | --- | --- |
| `queued` | `排队中` | Created and waiting for the background runner | Stop and keep saved data |
| `running` | `采集中` | Requesting an endpoint or reading a browser page | Stop and keep saved data |
| `needs_user` | `需要你处理` | Login, verification, page confirmation, or authorization is required | Handle the page, then select `页面已处理，继续` |
| `interrupted` | `已中断` | The local service stopped while the task was active | Select `继续任务` |
| `completed` | `已完成` | The current collection path reached its end rule or the storage limit | View, filter, and export |
| `failed` | `采集失败` | Rate limiting, parsing, network, or channel failure stopped the task | Read the reason, then retry or wait |
| `cancelled` | `已停止` | The user stopped the task | View and export saved data |

`completed` means the collector followed its current end rule. It does not prove that no additional reviews exist on the platform. A JD empty response, partial page visibility, the task cap, or the browser scroll limit can all produce a smaller result.

Common error codes:

| Error code | Typical cause |
| --- | --- |
| `AUTH_REQUIRED` | Login, account permission, or platform authorization is required |
| `VERIFICATION_REQUIRED` | A CAPTCHA, slider, or other human check is present |
| `RATE_LIMITED` | Requests were still rate-limited after bounded retries |
| `NETWORK_ERROR` | Network failure, timeout, or server error |
| `PARSE_ERROR` | Page markup, response format, or fields changed |
| `UNSUPPORTED` | The current environment lacks the required collection path |
| `INTERRUPTED` | The local service stopped and the task is waiting for recovery |

A failure does not delete saved reviews. The visible task reason is also designed not to expose cookies, request headers, or account details.

## 7. View, filter, and export

### 7.1 View reviews

Select a task in `最近任务`. The ledger shows the platform, product ID, task limit, status, saved count, and review rows. Reviews saved while a task is running can be used immediately.

Review content is rendered as plain text with `textContent`; HTML tags or scripts inside a review do not execute as page markup.

### 7.2 Filter

Filters apply to the selected task:

- `搜索评论` searches author, title, and body.
- `评分` matches an exact 1 through 5 star value. Reviews without a rating appear only under the unfiltered view.
- `购买标记` offers verified and non-verified records. Reviews whose platform did not provide a purchase marker appear only under the unfiltered view.

Click `筛选` to apply and `清除` to reset. The page loads 100 rows at a time; use `再显示 100 条` for more.

The JD direction selector is a collection-time request option. Browser-assisted review direction is not inferred and is not available as a result filter.

### 7.3 Export

`导出 CSV` and `导出 JSON` preserve the current keyword, rating, and purchase-marker filters. They export data saved when the download request is made, so an active task can produce a partial export.

CSV columns are:

```text
platform, product_id, platform_review_id, author, title, content,
rating, created_at_text, created_at, variant, verified_purchase,
helpful_count, source_url
```

CSV uses a UTF-8 BOM for spreadsheet compatibility. A string beginning with `=`, `+`, `-`, or `@` is prefixed with a single quote so spreadsheet software does not treat it as a formula. NUL characters are removed.

JSON has this structure:

```json
{
  "task": {
    "id": "...",
    "platform": "jd",
    "product_id": "...",
    "status": "completed"
  },
  "reviews": []
}
```

JSON keeps the stored strings unchanged and does not add the CSV formula prefix. Treat the content as untrusted text if it is later imported into a spreadsheet.

Exports can contain reviewer names, purchase markers, and review text. Check the file before sharing it and follow the relevant platform terms and applicable law.

## 8. Restart and recovery

If the service stops while tasks are queued or running, the next startup marks those tasks `interrupted`. Reviews already written to SQLite remain available:

1. Start `.venv/bin/python -m review_sampler` again.
2. Open the original task.
3. Click `继续任务`.

The JD public path resumes from the stored page cursor. Browser assistance opens the page again and reads the content currently visible. Deduplication prevents reviews seen again from being stored twice. The platform session may have expired, in which case the task returns to `需要你处理`.

A failed task can be retried. For sustained rate limiting, wait for the platform's cooldown. A parser error after a site change needs an updated adapter.

## 9. Local data and session cleanup

| Data | Path | Contents |
| --- | --- | --- |
| Tasks and reviews | `runtime/review-sampler.sqlite3` | SQLite database; WAL mode may also create `-wal` and `-shm` files |
| Browser state | `runtime/browser-state/<platform>/` | Persistent Chrome profile, cookies, and site-local storage |

Both paths are ignored by Git. Stop the service before moving or deleting them.

Clear one platform's browser session:

```bash
rm -rf runtime/browser-state/jd
```

Replace `jd` with `taobao`, `pdd`, or `amazon` for another platform. Do not remove a profile while the service is using it.

Remove all local tasks, reviews, exports kept in the runtime directory, and browser sessions:

```bash
rm -rf runtime
```

This is destructive and cannot be undone. To keep task data, stop the service and copy the database after all connections close. Copying a live WAL database directly can produce an inconsistent backup.

There is no interface button for clearing browser state and no encryption for the local database or browser profile. File access is protected by the operating system account.

## 10. Troubleshooting

### Chrome did not open

Install Google Chrome and reload the page. The platform capability display checks whether Chrome is available in the current environment. Without Chrome, Taobao/Tmall, PDD, and Amazon browser tasks cannot start.

### The task remains in `需要你处理`

Switch to the opened Chrome window, complete login or verification, and open the review list before returning. Then click `页面已处理，继续`. If this JD task started without browser consent, create a new task with consent enabled.

### The task completed with few or no reviews

Check whether the product and review list are visible to the current account and region. The JD public path can return partial data. Browser assistance has an eight-round scroll limit and stops after two consecutive rounds without new reviews. Inspect the task reason and create another task with a suitable limit if needed.

### The page says no visible reviews were recognized

The review list may not be loaded, the page may require login, or the site's DOM or JSON fields may have changed. Confirm that reviews are visible in Chrome first. If the task still fails, update the collector or normalization aliases.

### The platform rate-limited the request

Stop repeated retries and wait. The client applies bounded backoff to HTTP 429, temporary network errors, and server errors. It does not switch proxies to keep requesting.

### Why is there no direct Taobao or PDD API path?

Automated APIs require platform application, account, or merchant authorization. This repository does not include those credentials or authorized connectors. The browser path reads only content the user can view in the current page.

### Why not use Amazon Creators API for reviews?

The Creators API `GetItems` operation does not provide a review list. It can return product metadata but cannot replace review collection. The current Amazon path is browser-assisted.

### Can I import a CSV exported by a marketplace?

No. The current version has no import API or import button. `src/review_sampler/static/fixtures/demo_reviews.csv` documents the export columns and safe formula notation only.

## 11. Technical checks

Run the test suite:

```bash
.venv/bin/pytest -q
```

Check the frontend script syntax:

```bash
node --check src/review_sampler/static/app.js
```

Local API documentation is available at [http://127.0.0.1:8765/docs](http://127.0.0.1:8765/docs). Keep it on the local machine.

The default automated tests use fixed response and page fixtures; they do not verify live marketplace access. A fixture test and a manual check under a real account answer different questions. The latter depends on the platform's current page structure and account visibility.
