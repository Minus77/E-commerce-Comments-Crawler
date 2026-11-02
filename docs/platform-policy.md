# 平台访问与使用边界 / Platform Access and Usage Boundaries

<a href="#english"><ins>English</ins></a> · 简体中文

## 中文

### 1. 适用范围

本工具面向个人或小团队的商品评论分析，支持输入京东、淘宝/天猫、拼多多和 Amazon 的商品 ID 或商品链接。它在本机整理可恢复任务、统一评论字段、去重、筛选并导出。

“能够识别商品并创建任务”不等于“能够取得该商品的全部评论”。平台是否开放数据、账号能看到多少内容、地区、登录状态和页面验证都会改变结果。

### 2. 访问顺序

产品采用以下优先级：

1. 已获授权的官方接口。
2. 用户在浏览器中正常登录后可以查看的页面内容。
3. 用户自行取得并导入的文件。

当前版本只实现了京东公开评论页面、浏览器协助和内置演示数据。淘宝/天猫和拼多多没有内置授权 API 适配器，Amazon 也没有评论 API 通道。第 3 项导入能力同样尚未实现。

### 3. 当前能力

| 平台 | 当前通道 | 能读取什么 | 限制 |
| --- | --- | --- | --- |
| 京东 | 公开评论页面；可选浏览器协助 | 公开接口返回的评论；用户同意后读取浏览器中的可见评论 | 公开页面不是稳定契约，可能限流、要求验证、改版或只返回部分内容 |
| 淘宝/天猫 | 浏览器协助 | 页面已经加载的评论 JSON | 自动接口需要平台授权；当前没有授权适配器。DOM 解析也未覆盖淘宝 |
| 拼多多 | 浏览器协助 | 页面已经加载的评论 JSON | 未找到可供普通开发者查询任意商品全部评论的公开接口；当前没有授权适配器。DOM 解析也未覆盖拼多多 |
| Amazon | 浏览器协助 | 页面已经呈现的评论；已知评论 DOM 也可解析 | Creators API 的 `GetItems` 不提供评论列表；页面自动化受站点政策和地区规则约束 |

浏览器协助不是“隐形抓取器”。它会打开一个有界面的 Chrome 窗口，由用户自行完成登录和验证。程序最多滚动 8 轮，每轮等待约 1 秒，连续两轮没有新增评论时停止。

### 4. 验证与风控

常见机制包括登录检查、会话校验、请求频率限制、动态令牌、JavaScript challenge、行为分析和验证码/滑块。不同平台使用哪些机制会随页面、地区和时间变化。

工具按以下方式处理：

| 页面或响应 | 工具行为 | 用户操作 |
| --- | --- | --- |
| 网络抖动、5xx | 使用有限退避 | 等待重试或稍后再试 |
| HTTP 429 | 优先遵循 `Retry-After`，否则退避；最多重试 3 次 | 等待冷却时间 |
| 登录或账号权限不足 | 停止自动读取，任务进入 `needs_user` | 在打开的 Chrome 中自行登录 |
| 验证码、滑块、风险验证 | 停止并等待 | 用户在页面中自行完成 |
| 页面或字段变化 | 保留已有评论并报告解析错误 | 更新适配器后重试 |
| 页面权限不足或平台不提供评论 | 显示不可用原因 | 使用有授权的数据源或用户自己的导出文件 |

工具不会自动填写密码、点击验证码、识别滑块、绕过平台警告、轮换代理、伪造浏览器指纹或模拟真人节奏。这里没有“先绕过失败再继续”的隐藏通道。

### 5. 平台说明

#### 京东

`club.jd.com` 评论页面是原项目使用的来源，不是面向开发者的稳定公共 API。当前实现保留这条路径，加入限速、超时、有限重试、空结果终止和验证页识别。

京东商家开放平台另有商家侧评论接口，但需要应用和商家授权。当前仓库没有把商家凭证接入任务流程。

#### 淘宝/天猫

淘宝开放平台列出的商品评价查询接口取决于应用权限和授权会话。淘宝页面协议对第三方自动化访问有明确限制，并要求在触发人机识别时如实配合。

因此，没有合法凭证时，工具只提供浏览器协助。淘宝评论主要依赖页面已加载的 JSON；页面改版或字段变化可能导致无法识别。后台不会启动未授权的自动采集。

#### 拼多多

调研未找到可供普通开发者查询任意商品全部评论的公开开放接口。拼多多用户协议限制通过机器人或其他程序擅自获取平台内容。

当前浏览器通道只读取用户当前页面已经加载的内容。它不声称获得平台许可，也不自动处理验证。

#### Amazon

PA-API 5 已停用。Creators API 的 `GetItems` 可返回商品信息，但不提供评论列表，且调用额度和错误处理需要遵循官方文档。

当前 Amazon 通道仅提供浏览器协助。站点、地区、登录状态和 Amazon 计划政策会影响可见内容。工具不会用商品 API 假装成评论来源。

### 6. 用户责任与数据

- 只分析你有权访问和使用的数据。
- 遵守目标平台的当前条款、访问限制和适用法律。
- 不要用本工具绕过账号权限、付费墙、验证或地域限制。
- 不要把 `runtime/browser-state/` 上传、提交或发送给其他人。该目录可能包含身份 Cookie。
- 导出可能包含昵称、购买标记和评论正文。分享前检查内容并做必要脱敏。
- 浏览器任务尽量串行运行。同一平台的持久化 Chrome profile 不适合同时被多个采集器使用。

### 7. 明确不支持

- 代理池或代理轮换。
- 浏览器指纹伪装、隐身补丁或规避脚本。
- 自动登录、自动过验证码、滑块识别或打码平台。
- 绕过平台风控、访问限制或账号权限。
- 集中托管多个用户的平台 Cookie。
- 保证任意商品的全量评论或长期稳定的页面结构。

### 8. 调研边界

平台条款和实施方式会变化。本仓库的调研记录见[多平台商品评论采集：平台访问与风险调研](research/2026-11-02-platform-access.md)。

主要来源：

- [淘宝商品评价查询 API](https://developer.alibaba.com/docs/api.htm?apiId=70274)
- [淘宝网法律声明与相关协议](https://terms.alicdn.com/legal-agreement/terms/suit_bu1_taobao/suit_bu1_taobao201811121436_80276.html)
- [京东开放平台评论接口目录](https://jos.jd.com/apilist?apiGroupId=676)
- [拼多多用户服务协议](https://www.yangkeduo.com/pdd_user_services_agreement.pdf)
- [Amazon PA-API 5 deprecation](https://affiliate-program.amazon.com/creatorsapi/docs/en-us/paapiv5-deprecation)
- [Amazon Creators API GetItems](https://affiliate-program.amazon.com/creatorsapi/docs/en-us/api-reference/operations/get-items)
- [Amazon 计划政策](https://affiliate-program.amazon.com/help/operating/policies)

仓库没有在自动化测试中验证淘宝、拼多多或 Amazon 的实时线上采集。页面可见性、账号权限和平台规则仍需在实际使用时检查。

---

## English

### 1. Scope

Review Sampler is a local tool for personal or small-team product review analysis. It accepts product IDs and URLs for JD, Taobao/Tmall, PDD, and Amazon, then stores resumable tasks, normalizes review fields, removes duplicates, filters results, and exports CSV or JSON.

Being able to recognize an item and create a task does not mean the tool can retrieve every review. Data availability, account visibility, region, login state, and page verification all affect the result.

### 2. Access order

The intended order is:

1. An authorized official API.
2. Content a user can view after logging in normally.
3. A file the user obtained and imported.

The current version implements a JD public comment page, browser assistance, and built-in demo data. Taobao/Tmall and PDD have no authorized API adapter. Amazon has no review API path. File import is not implemented either.

### 3. Current capabilities

| Platform | Current path | What can be read | Limitation |
| --- | --- | --- | --- |
| JD | Public comment page; optional browser assistance | Reviews returned by the public page; visible browser reviews after consent | The page is not a stable contract and may rate-limit, request verification, change, or expose only partial data |
| Taobao/Tmall | Browser assistance | Review JSON already loaded by the page | Automated APIs need platform authorization; no authorized adapter is included. DOM parsing does not cover Taobao |
| PDD | Browser assistance | Review JSON already loaded by the page | No public API was found for arbitrary-item review access; no authorized adapter is included. DOM parsing does not cover PDD |
| Amazon | Browser assistance | Reviews already displayed on the page; known review DOM can also be parsed | Creators API `GetItems` does not provide reviews; automation remains subject to storefront policy and regional rules |

Browser assistance is not a hidden crawler. It opens a visible Chrome window and asks the user to log in or handle verification. It scrolls for at most eight rounds, waits about one second per round, and stops after two rounds with no new reviews.

### 4. Verification and risk controls

Platforms may combine login checks, sessions, request limits, dynamic tokens, JavaScript challenges, behavior analysis, and CAPTCHA or slider checks. The exact mechanisms vary by page, region, and time.

| Page or response | Tool behavior | User action |
| --- | --- | --- |
| Temporary network error or 5xx | Bounded backoff | Wait or retry later |
| HTTP 429 | Honor `Retry-After` when present, otherwise back off; at most three retries | Wait for the cooldown |
| Login or missing account permission | Stop automatic reading and enter `needs_user` | Log in within the opened Chrome window |
| CAPTCHA, slider, or risk check | Stop and wait | Complete the page challenge yourself |
| Page or field change | Keep saved reviews and report a parse error | Update the adapter before retrying |
| No access or no review data | Show the limitation | Use an authorized source or the user's own export |

The tool does not fill passwords, complete CAPTCHAs, solve sliders, bypass warnings, rotate proxies, spoof fingerprints, or imitate human timing. There is no hidden path that continues past a failed verification.

### 5. Platform notes

#### JD

The `club.jd.com` comment page is the source used by the original project. It is not a stable public developer API. The current implementation adds pacing, timeouts, bounded retries, empty-result termination, and challenge detection.

JD's merchant open platform has a merchant-side review interface, but access requires application and merchant authorization. This repository does not connect merchant credentials to the task flow.

#### Taobao/Tmall

The product review query listed by the Taobao Open Platform depends on application permission and an authorized session. Taobao's page terms also set explicit conditions for third-party automated access and require cooperation with human verification.

Without valid credentials, this tool provides browser assistance only. Taobao reviews primarily depend on JSON loaded by the page; markup or field changes can prevent recognition. The application does not start unauthorized background collection.

#### PDD

The research found no public API that lets an ordinary developer query all reviews for an arbitrary product. PDD's user agreement restricts collection of platform content through robots or similar programs.

The browser path reads only content already loaded in the user's page. It makes no claim of platform permission and does not handle verification automatically.

#### Amazon

PA-API 5 is retired. Creators API `GetItems` can return product information, but not review lists, and API use remains subject to official rate limits and error handling.

The current Amazon path is browser assistance only. Storefront, region, login state, and Amazon program policy affect what is visible. The tool does not present product API data as reviews.

### 6. User responsibilities and data

- Analyze only data you are allowed to access and use.
- Follow the current platform terms, access limits, and applicable law.
- Do not use this tool to bypass account permissions, paywalls, verification, or regional restrictions.
- Do not upload, commit, or send `runtime/browser-state/`. It may contain identity cookies.
- Exports may contain aliases, purchase markers, and review text. Inspect and redact them before sharing.
- Prefer serial browser tasks. Persistent Chrome profiles for one platform are not suitable for simultaneous collectors.

### 7. Explicit non-goals

- Proxy pools or proxy rotation.
- Fingerprint spoofing, stealth patches, or evasion scripts.
- Automatic login, CAPTCHA solving, slider solving, or third-party solving services.
- Bypassing risk controls, access limits, or account permissions.
- Central storage of multiple users' marketplace cookies.
- A guarantee of complete reviews for an arbitrary product or permanently stable page markup.

### 8. Research boundary

Platform terms and implementations change. The repository research record is [Platform Access and Risk Research](research/2026-11-02-platform-access.md).

Primary sources:

- [Taobao product review query API](https://developer.alibaba.com/docs/api.htm?apiId=70274)
- [Taobao legal notices and agreements](https://terms.alicdn.com/legal-agreement/terms/suit_bu1_taobao/suit_bu1_taobao201811121436_80276.html)
- [JD Open Platform review API directory](https://jos.jd.com/apilist?apiGroupId=676)
- [PDD user service agreement](https://www.yangkeduo.com/pdd_user_services_agreement.pdf)
- [Amazon PA-API 5 deprecation](https://affiliate-program.amazon.com/creatorsapi/docs/en-us/paapiv5-deprecation)
- [Amazon Creators API GetItems](https://affiliate-program.amazon.com/creatorsapi/docs/en-us/api-reference/operations/get-items)
- [Amazon program policies](https://affiliate-program.amazon.com/help/operating/policies)

The automated test suite does not verify live Taobao, PDD, or Amazon collection. Page visibility, account permissions, and platform rules still need to be checked during real use.
