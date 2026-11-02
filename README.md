# 评论采样台 / Review Sampler

评论采样台是一个本机运行的商品评论工具。它接受京东、淘宝/天猫、拼多多和 Amazon 的商品 ID 或商品链接，把采集过程保存为可恢复的任务，并统一去重、筛选和导出评论。

<a href="docs/product/user-guide.en.md"><ins>English</ins></a> · 简体中文

[使用指南](docs/product/user-guide.zh-CN.md) · [架构说明](docs/architecture/architecture.zh-CN.md) · [平台限制](docs/platform-policy.md)

## 当前能做什么

- 京东：先请求公开评论页面；用户勾选浏览器协助后，遇到登录、验证或限流时转到本机 Chrome。
- 淘宝/天猫、拼多多：当前版本通过浏览器协助读取用户能正常查看的评论。授权 API 适配器尚未内置。
- Amazon：通过浏览器协助读取页面内容。Creators API 不提供评论列表，当前版本也没有把商品 API 当作评论来源。
- 演示数据：不访问平台，可用来体验任务、筛选和 CSV/JSON 导出。

“支持一个平台”是指能够识别该平台的商品输入、建立任务并保存统一字段，不表示任意商品都能取得全部评论。账号权限、商品页面的评论可见范围、平台条款、页面改版和地区限制都会影响结果。

## 快速启动

需要 Python 3.11 或更高版本。浏览器协助还需要本机安装 Google Chrome。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test,browser]'
.venv/bin/python -m review_sampler
```

打开 [http://127.0.0.1:8765](http://127.0.0.1:8765)。服务只监听本机回环地址。

第一次使用可以先点击“载入演示”。接着修改关键词、评分或购买标记，再点击“导出 CSV”或“导出 JSON”检查筛选后的结果。

## 数据位置

默认数据库是 `runtime/review-sampler.sqlite3`，浏览器会话按平台保存在 `runtime/browser-state/<platform>/`。两者都在 `.gitignore` 中，不会被提交。

可以用 `REVIEW_SAMPLER_DB` 指定另一个数据库路径：

```bash
REVIEW_SAMPLER_DB=/absolute/path/reviews.sqlite3 .venv/bin/python -m review_sampler
```

浏览器会话目录包含登录 Cookie，等同于本机身份数据。停止服务后，可以手动删除不再需要的平台目录。删除前请先确认不需要继续使用该登录状态。

## 使用边界

本项目只处理用户正常登录后可以查看的内容。它不会自动登录，不会处理验证码或滑块，也不会提供代理轮换、指纹伪装或验证绕过。遇到平台验证时，任务会暂停并等待用户在自己打开的 Chrome 窗口中处理。

当前版本不提供 CSV/JSON 导入。`src/review_sampler/static/fixtures/demo_reviews.csv` 只展示导出格式和公式安全写法。

完整的平台限制见 [平台访问与使用边界](docs/platform-policy.md)，调研来源和事实记录见 [平台访问调研](docs/research/2026-11-02-platform-access.md)。

## 开发与测试

```bash
.venv/bin/pytest -q
node --check src/review_sampler/static/app.js
```

默认测试使用固定响应和页面夹具，不访问淘宝、拼多多或 Amazon 的线上评论。真实平台采集仍需单独检查账号权限和当前页面结构。
