"use strict";

const POLL_INTERVAL = 1500;
const PAGE_SIZE = 100;
const ACTIVE_STATUSES = new Set(["queued", "running"]);
const STATUS_LABELS = {
  queued: "排队中",
  running: "采集中",
  needs_user: "需要你处理",
  interrupted: "已中断",
  completed: "已完成",
  failed: "采集失败",
  cancelled: "已停止",
};
const PLATFORM_FALLBACKS = {
  jd: "京东",
  taobao: "淘宝 / 天猫",
  pdd: "拼多多",
  amazon: "Amazon",
  demo: "演示数据",
};

const state = {
  platforms: [],
  selectedPlatform: "jd",
  tasks: [],
  selectedTaskId: null,
  task: null,
  reviews: [],
  total: 0,
  filters: { q: "", rating: "", verified: "" },
  pollTimer: null,
  reviewRequest: 0,
};

const elements = {};

function cacheElements() {
  [
    "platform-strip",
    "task-form",
    "product-input",
    "limit-input",
    "direction-input",
    "direction-note",
    "platform-example",
    "platform-note",
    "consent-row",
    "consent-copy",
    "browser-consent",
    "form-error",
    "start-button",
    "demo-button",
    "task-rail",
    "rail-toggle",
    "task-count",
    "task-list",
    "task-list-empty",
    "ledger",
    "ledger-empty",
    "ledger-content",
    "task-platform",
    "task-product",
    "task-caption",
    "task-status",
    "task-total",
    "progress-track",
    "progress-fill",
    "task-message",
    "task-reason",
    "task-error-code",
    "task-actions",
    "filter-form",
    "keyword-input",
    "rating-filter",
    "verified-filter",
    "clear-filters",
    "review-summary",
    "export-csv",
    "export-json",
    "review-status",
    "review-list",
    "load-more",
    "review-template",
    "notice",
  ].forEach((id) => {
    elements[id] = document.getElementById(id);
  });
}

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function statusClass(status) {
  const known = Object.hasOwn(STATUS_LABELS, status) ? status : "queued";
  return `status--${known.replaceAll("_", "-")}`;
}

function platformName(platform) {
  return (
    state.platforms.find((item) => item.platform === platform)?.name ||
    PLATFORM_FALLBACKS[platform] ||
    platform
  );
}

async function request(path, options = {}) {
  const headers = { Accept: "application/json", ...(options.headers || {}) };
  if (options.body) headers["Content-Type"] = "application/json";
  let response;
  try {
    response = await fetch(path, { ...options, headers });
  } catch {
    throw new Error("无法连接本地服务，请确认程序仍在运行。");
  }
  let payload = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok) {
    const message =
      typeof payload?.detail === "string"
        ? payload.detail
        : "请求没有完成，请稍后重试。";
    throw new Error(message);
  }
  return payload;
}

function showNotice(message) {
  elements.notice.textContent = message;
  elements.notice.classList.add("is-visible");
  window.clearTimeout(showNotice.timer);
  showNotice.timer = window.setTimeout(() => {
    elements.notice.classList.remove("is-visible");
  }, 4200);
}

function showFormError(message) {
  elements["form-error"].textContent = message;
  elements["form-error"].hidden = !message;
  if (message) elements["product-input"].setAttribute("aria-invalid", "true");
  else elements["product-input"].removeAttribute("aria-invalid");
}

async function loadPlatforms() {
  try {
    const payload = await request("/api/platforms");
    state.platforms = (payload.platforms || []).filter(
      (item) => item.platform !== "demo",
    );
    if (!state.platforms.some((item) => item.platform === state.selectedPlatform)) {
      state.selectedPlatform = state.platforms[0]?.platform || "jd";
    }
    renderPlatforms();
    renderPlatformInfo();
    elements["start-button"].disabled = state.platforms.length === 0;
  } catch (error) {
    elements["platform-strip"].replaceChildren(
      node("p", "loading-line", error.message),
    );
    elements["start-button"].disabled = true;
    showFormError(error.message);
  }
}

function renderPlatforms() {
  elements["platform-strip"].replaceChildren();
  state.platforms.forEach((platform) => {
    const button = node("button", "platform-option");
    button.type = "button";
    button.dataset.platform = platform.platform;
    button.setAttribute(
      "aria-pressed",
      String(platform.platform === state.selectedPlatform),
    );
    button.append(
      node("span", "platform-name", platform.name),
      node("span", "platform-capability", capabilityText(platform)),
    );
    button.addEventListener("click", () => {
      state.selectedPlatform = platform.platform;
      elements["platform-strip"]
        .querySelectorAll(".platform-option")
        .forEach((option) => {
          option.setAttribute(
            "aria-pressed",
            String(option.dataset.platform === platform.platform),
          );
        });
      renderPlatformInfo();
    });
    elements["platform-strip"].append(button);
  });
}

function capabilityText(platform) {
  if (platform.auto_api && platform.browser_assist) {
    return "公开接口，浏览器协助可用";
  }
  if (platform.auto_api) return "公开接口";
  if (platform.browser_assist) return "浏览器会话协助";
  return "需平台授权或本机 Chrome";
}

function selectedPlatformData() {
  return state.platforms.find(
    (item) => item.platform === state.selectedPlatform,
  );
}

function renderPlatformInfo() {
  const platform = selectedPlatformData();
  if (!platform) {
    elements["platform-example"].textContent = "";
    elements["platform-note"].textContent = "请选择商品平台。";
    elements["consent-row"].hidden = true;
    return;
  }
  elements["product-input"].placeholder = `例如：${platform.example}`;
  elements["platform-example"].textContent = `示例：${platform.example}`;
  const browserText = platform.browser_assist
    ? platform.platform === "jd"
      ? "勾选下方选项后，接口被拦截时会转用本机 Chrome。"
      : "本机已检测到 Chrome，可在登录或验证时暂停。"
    : "当前未检测到可用的 Chrome，浏览器协助可能无法启动。";
  const autoText = platform.auto_api
    ? "公开接口优先，遇到限流或验证会停下来。"
    : "没有可直接使用的公开评论接口。";
  elements["platform-note"].textContent = `${autoText} ${platform.limitation} ${browserText}`;
  elements["consent-row"].hidden = !platform.browser_assist;
  elements["consent-copy"].textContent =
    platform.platform === "jd"
      ? "公开接口被拦截时，我会在打开的 Chrome 窗口中自行完成登录和验证。"
      : "我会在打开的 Chrome 窗口中自行完成登录和验证。";
  elements["direction-input"].disabled = platform.platform !== "jd";
  if (elements["direction-input"].disabled) {
    elements["direction-input"].value = "all";
  }
  elements["direction-note"].textContent =
    platform.platform === "jd"
      ? "公开接口可按方向请求；浏览器协助在采集后筛选。"
      : "当前通道读取页面中可见的评论，方向请在采集后筛选。";
  elements["browser-consent"].checked = false;
}

function renderTaskList() {
  elements["task-list"].replaceChildren();
  elements["task-count"].textContent = String(state.tasks.length);
  elements["task-list-empty"].hidden = state.tasks.length > 0;

  state.tasks.forEach((task) => {
    const button = node("button", "task-item");
    button.type = "button";
    button.setAttribute(
      "aria-current",
      String(task.id === state.selectedTaskId),
    );

    const label = node("span");
    label.append(
      node(
        "span",
        "task-item__platform",
        platformName(task.platform),
      ),
      node("span", "task-item__id", task.product_id),
    );
    const count = node(
      "span",
      "task-item__count",
      `${task.collected_count} / ${task.limit}`,
    );
    const status = node(
      "span",
      `mini-status ${statusClass(task.status)}`,
      STATUS_LABELS[task.status] || task.status,
    );
    button.append(label, count, status);
    button.addEventListener("click", () => {
      elements.ledger.focus({ preventScroll: true });
      openTask(task.id);
    });
    elements["task-list"].append(button);
  });
}

async function refreshTasks({ selectFirst = false } = {}) {
  try {
    const payload = await request("/api/tasks");
    state.tasks = payload.tasks || [];
    renderTaskList();
    if (
      selectFirst &&
      !state.selectedTaskId &&
      state.tasks.length > 0
    ) {
      await openTask(state.tasks[0].id);
    }
  } catch (error) {
    showNotice(error.message);
  }
}

async function openTask(taskId) {
  if (!taskId) return;
  clearPoll();
  state.selectedTaskId = taskId;
  state.reviews = [];
  state.total = 0;
  state.filters = { q: "", rating: "", verified: "" };
  elements["filter-form"].reset();
  renderTaskList();
  elements["ledger-empty"].hidden = true;
  elements["ledger-content"].hidden = false;
  elements["review-status"].textContent = "正在读取任务…";
  elements["review-list"].replaceChildren();
  elements["load-more"].hidden = true;
  try {
    const payload = await request(`/api/tasks/${encodeURIComponent(taskId)}`);
    if (state.selectedTaskId !== taskId) return;
    setTask(payload.task);
    await loadReviews();
    schedulePoll();
  } catch (error) {
    if (state.selectedTaskId === taskId) {
      elements["review-status"].textContent = error.message;
      showNotice(error.message);
    }
  }
}

function setTask(task) {
  state.task = task;
  const index = state.tasks.findIndex((item) => item.id === task.id);
  if (index >= 0) state.tasks[index] = task;
  else state.tasks.unshift(task);
  renderTaskList();
  renderTask();
}

function renderTask() {
  const task = state.task;
  if (!task) return;
  elements["task-platform"].textContent = platformName(task.platform);
  elements["task-product"].textContent = task.product_id;
  elements["task-caption"].textContent = [
    task.mode === "demo"
      ? "演示任务"
      : task.platform === "jd" && task.mode === "auto"
        ? task.browser_consent
          ? "公开接口优先，可转浏览器协助"
          : "公开接口优先"
        : "浏览器协助",
    `上限 ${task.limit} 条`,
    task.created_at ? `创建于 ${formatDate(task.created_at)}` : "",
  ]
    .filter(Boolean)
    .join(" · ");

  const status = STATUS_LABELS[task.status] || task.status;
  elements["task-status"].textContent = status;
  elements["task-status"].className = `status-pill ${statusClass(task.status)}`;
  elements["task-total"].textContent = `已保存 ${task.collected_count} 条`;
  elements["task-reason"].textContent =
    task.status_reason || "任务已建立，等待采集。";
  elements["task-error-code"].textContent = task.error_code
    ? `错误码 ${task.error_code}`
    : "";
  elements["task-error-code"].hidden = !task.error_code;

  elements["task-message"].className = `task-message ${statusClass(task.status)}`;
  renderTaskActions(task);

  const showProgress = ["queued", "running", "needs_user", "interrupted"].includes(
    task.status,
  );
  elements["progress-track"].hidden = !showProgress;
  const ratio = Math.min(1, task.collected_count / Math.max(1, task.limit));
  elements["progress-fill"].style.transform = `scaleX(${ratio})`;
}

function renderTaskActions(task) {
  elements["task-actions"].replaceChildren();
  if (task.status === "needs_user") {
    addTaskAction("页面已处理，继续", "primary", () =>
      continueTask(task.id, "继续读取评论。"),
    );
  } else if (task.status === "interrupted") {
    addTaskAction("继续任务", "primary", () =>
      continueTask(task.id, "正在恢复任务。"),
    );
  } else if (task.status === "failed") {
    addTaskAction("重试任务", "primary", () =>
      continueTask(task.id, "正在重试任务。"),
    );
  } else if (ACTIVE_STATUSES.has(task.status)) {
    addTaskAction("停止并保留已保存内容", "", () =>
      cancelTask(task.id),
    );
  }
}

function addTaskAction(label, kind, handler) {
  const button = node(
    "button",
    `task-action${kind ? ` task-action--${kind}` : ""}`,
    label,
  );
  button.type = "button";
  button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      await handler();
    } finally {
      button.disabled = false;
    }
  });
  elements["task-actions"].append(button);
}

async function continueTask(taskId, message) {
  try {
    const payload = await request(
      `/api/tasks/${encodeURIComponent(taskId)}/continue`,
      { method: "POST" },
    );
    if (state.selectedTaskId === taskId) {
      setTask(payload.task);
      await loadReviews({ keepLoaded: true });
      schedulePoll(0);
    }
    await refreshTasks();
    showNotice(message);
  } catch (error) {
    showNotice(error.message);
  }
}

async function cancelTask(taskId) {
  try {
    const payload = await request(
      `/api/tasks/${encodeURIComponent(taskId)}/cancel`,
      { method: "POST" },
    );
    if (state.selectedTaskId === taskId) {
      setTask(payload.task);
      clearPoll();
      await loadReviews({ keepLoaded: true });
    }
    await refreshTasks();
    showNotice("任务已停止，已保存的评论仍在本地。");
  } catch (error) {
    showNotice(error.message);
  }
}

function clearPoll() {
  window.clearTimeout(state.pollTimer);
  state.pollTimer = null;
}

function schedulePoll(delay = POLL_INTERVAL) {
  clearPoll();
  if (!state.task || !ACTIVE_STATUSES.has(state.task.status)) return;
  state.pollTimer = window.setTimeout(pollActiveTask, delay);
}

async function pollActiveTask() {
  const selectedId = state.selectedTaskId;
  if (!selectedId || document.hidden) {
    schedulePoll();
    return;
  }
  try {
    const [tasksPayload, taskPayload] = await Promise.all([
      request("/api/tasks"),
      request(`/api/tasks/${encodeURIComponent(selectedId)}`),
    ]);
    if (state.selectedTaskId !== selectedId) return;
    state.tasks = tasksPayload.tasks || [];
    setTask(taskPayload.task);
    await loadReviews({ keepLoaded: true, quiet: true });
  } catch (error) {
    if (state.selectedTaskId === selectedId) showNotice(error.message);
  } finally {
    if (state.selectedTaskId === selectedId) schedulePoll();
  }
}

function activeFilters() {
  const params = new URLSearchParams();
  if (state.filters.q) params.set("q", state.filters.q);
  if (state.filters.rating) params.set("rating", state.filters.rating);
  if (state.filters.verified) {
    params.set("verified", state.filters.verified);
  }
  return params;
}

function reviewParams(offset, limit) {
  const params = new URLSearchParams();
  params.set("task_id", state.selectedTaskId);
  activeFilters().forEach((value, key) => params.set(key, value));
  params.set("offset", String(offset));
  params.set("limit", String(limit));
  return params;
}

async function loadReviews({ append = false, keepLoaded = false, quiet = false } = {}) {
  if (!state.selectedTaskId) return;
  const taskId = state.selectedTaskId;
  const requestNumber = ++state.reviewRequest;
  const limit = append || !keepLoaded
    ? PAGE_SIZE
    : Math.max(PAGE_SIZE, state.reviews.length);
  const offset = append ? state.reviews.length : 0;
  if (!quiet) elements["review-status"].textContent = "正在读取评论…";
  try {
    const payload = await request(
      `/api/reviews?${reviewParams(offset, limit).toString()}`,
    );
    if (
      state.selectedTaskId !== taskId ||
      requestNumber !== state.reviewRequest
    ) {
      return;
    }
    const incoming = payload.reviews || [];
    state.reviews = append ? [...state.reviews, ...incoming] : incoming;
    state.total = Number(payload.total || 0);
    elements["review-status"].textContent = "";
    renderReviews();
  } catch (error) {
    if (state.selectedTaskId !== taskId) return;
    elements["review-status"].textContent = error.message;
  }
}

function updateFilters() {
  state.filters = {
    q: elements["keyword-input"].value.trim(),
    rating: elements["rating-filter"].value,
    verified: elements["verified-filter"].value,
  };
  state.reviews = [];
  state.total = 0;
  loadReviews();
}

function renderReviews() {
  elements["review-list"].replaceChildren();
  elements["review-summary"].textContent =
    `共 ${state.total} 条匹配，已显示 ${state.reviews.length} 条`;
  updateExportLinks();

  if (state.reviews.length === 0) {
    const message =
      state.total === 0 &&
      !state.filters.q &&
      !state.filters.rating &&
      !state.filters.verified
        ? emptyReviewMessage()
        : "当前筛选没有匹配的评论。";
    elements["review-list"].append(node("p", "rail-empty", message));
  }

  state.reviews.forEach((review) => {
    const fragment = elements["review-template"].content.cloneNode(true);
    const row = fragment.querySelector(".review-row");
    row.querySelector(".review-title").textContent = review.title || "";
    row.querySelector(".review-author").textContent =
      review.author || "匿名用户";
    const rating = Number(review.rating || 0);
    const ratingElement = row.querySelector(".review-rating");
    ratingElement.textContent = rating > 0 ? "★".repeat(rating) : "未评分";
    ratingElement.setAttribute(
      "aria-label",
      rating > 0 ? `${rating} 星` : "未评分",
    );
    row.querySelector(".review-content").textContent = review.content || "";

    const meta = [];
    if (review.created_at_text) meta.push(review.created_at_text);
    if (review.variant) meta.push(review.variant);
    if (review.verified_purchase === 1) meta.push("已验证购买");
    else if (review.verified_purchase === 0) meta.push("未标注已验证购买");
    else meta.push("购买状态未标注");
    row.querySelector(".review-meta").textContent = meta.join(" · ");
    row.querySelector(".review-helpful").textContent =
      review.helpful_count > 0 ? `${review.helpful_count} 人觉得有用` : "";
    elements["review-list"].append(fragment);
  });

  const remaining = state.total - state.reviews.length;
  elements["load-more"].hidden = remaining <= 0;
  elements["load-more"].textContent = `再显示 ${Math.min(PAGE_SIZE, remaining)} 条`;
}

function emptyReviewMessage() {
  if (state.task?.status === "running" || state.task?.status === "queued") {
    return "任务正在读取评论，已保存的内容会自动出现在这里。";
  }
  if (state.task?.status === "needs_user") {
    return "浏览器窗口需要你处理。完成后点击上方“页面已处理，继续”。";
  }
  return "这个任务还没有保存评论。请查看任务状态或调整筛选。";
}

function updateExportLinks() {
  if (!state.selectedTaskId) return;
  const query = activeFilters().toString();
  const suffix = query ? `?${query}` : "";
  elements["export-csv"].href =
    `/api/tasks/${encodeURIComponent(state.selectedTaskId)}/export.csv${suffix}`;
  elements["export-json"].href =
    `/api/tasks/${encodeURIComponent(state.selectedTaskId)}/export.json${suffix}`;
}

async function submitTask(event) {
  event.preventDefault();
  showFormError("");
  const product = elements["product-input"].value.trim();
  if (!product) {
    showFormError("请输入商品链接或商品 ID。");
    elements["product-input"].focus();
    return;
  }

  const platform = selectedPlatformData();
  if (!platform) {
    showFormError("请选择商品所在平台。");
    return;
  }
  const needsConsent = platform.platform !== "jd";
  if (needsConsent && !platform.browser_assist) {
    showFormError(
      "此平台需要浏览器协助，但本机未检测到 Chrome。请安装 Chrome 后重启服务。",
    );
    return;
  }
  if (needsConsent && !elements["browser-consent"].checked) {
    showFormError("请先确认你会自行完成浏览器中的登录和验证。");
    elements["browser-consent"].focus();
    return;
  }

  const limit = Number(elements["limit-input"].value);
  if (!Number.isInteger(limit) || limit < 1 || limit > 5000) {
    showFormError("采集上限必须是 1 到 5000 之间的整数。");
    elements["limit-input"].focus();
    return;
  }

  elements["start-button"].disabled = true;
  elements["start-button"].textContent = "正在建立任务…";
  try {
    const task = await request("/api/tasks", {
      method: "POST",
      body: JSON.stringify({
        platform: platform.platform,
        product,
        mode: "auto",
        limit,
        browser_consent:
          elements["browser-consent"].checked,
        review_filter: elements["direction-input"].value,
      }),
    });
    elements["product-input"].value = "";
    elements["browser-consent"].checked = false;
    state.selectedTaskId = task.id;
    await refreshTasks();
    await openTask(task.id);
    elements["ledger"].scrollIntoView({ block: "start", behavior: "smooth" });
    showNotice("采样任务已开始，已保存的评论会陆续出现。");
  } catch (error) {
    showFormError(error.message);
  } finally {
    elements["start-button"].disabled = false;
    elements["start-button"].textContent = "开始采样";
  }
}

async function createDemo() {
  elements["demo-button"].disabled = true;
  elements["demo-button"].textContent = "正在载入…";
  try {
    const task = await request("/api/demo?limit=6", { method: "POST" });
    state.selectedTaskId = task.id;
    await refreshTasks();
    await openTask(task.id);
    elements["ledger"].scrollIntoView({ block: "start", behavior: "smooth" });
    showNotice("演示任务已建立。");
  } catch (error) {
    showNotice(error.message);
  } finally {
    elements["demo-button"].disabled = false;
    elements["demo-button"].textContent = "载入演示";
  }
}

function formatDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function bindEvents() {
  elements["task-form"].addEventListener("submit", submitTask);
  elements["demo-button"].addEventListener("click", createDemo);
  elements["filter-form"].addEventListener("submit", (event) => {
    event.preventDefault();
    updateFilters();
  });
  elements["clear-filters"].addEventListener("click", () => {
    elements["filter-form"].reset();
    updateFilters();
  });
  elements["load-more"].addEventListener("click", () =>
    loadReviews({ append: true }),
  );
  elements["rail-toggle"].addEventListener("click", () => {
    const collapsed = elements["task-rail"].classList.toggle("is-collapsed");
    elements["rail-toggle"].setAttribute("aria-expanded", String(!collapsed));
    elements["rail-toggle"].textContent = collapsed ? "展开" : "收起";
  });
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && state.task && ACTIVE_STATUSES.has(state.task.status)) {
      schedulePoll(0);
    }
  });
}

async function init() {
  cacheElements();
  bindEvents();
  await Promise.all([loadPlatforms(), refreshTasks({ selectFirst: true })]);
}

init();
