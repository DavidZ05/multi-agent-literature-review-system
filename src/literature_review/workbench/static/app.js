(() => {
  "use strict";

  const messages = {
    "en": {
      brand: "Literature Review Workbench", workbenchActions: "Workbench actions",
      events: "Events", resumeRun: "Resume", closeDiscovery: "Close discovery",
      cancelRun: "Cancel run", newRun: "New discovery run", researchRuns: "Research runs",
      localStorage: "Local storage", database: "Database", artifacts: "Artifacts",
      loadingRuns: "Loading research runs...", loadingDetail: "Loading run details...",
      noRuns: "No research runs yet.", createFirstRun: "Create the first run",
      retry: "Retry", candidates: "Candidates", candidateFilters: "Candidate filters",
      candidateTable: "Discovered literature candidates", paper: "Paper", year: "Year",
      source: "Source", score: "Score", status: "Status", noCandidates: "No candidates match this filter.",
      selectCandidate: "Select a candidate", selectCandidateHint: "Candidate metadata and decisions appear here.",
      detailLoadFailed: "Run details unavailable",
      abstractEvidence: "Abstract evidence", screeningRecommendation: "Screening recommendation",
      identifiers: "Identifiers and sources", approvalMetadata: "Approval metadata",
      category: "Category", contribution: "Contribution", tags: "Tags",
      decisionReason: "Decision reason", approve: "Approve", defer: "Defer", reject: "Reject",
      equivalentCli: "Equivalent CLI:", close: "Close", topic: "Topic", corpusPath: "Corpus path",
      enableDiscovery: "Discover additional literature", providers: "Providers",
      maxResults: "Maximum results per query", startRun: "Start run",
      pending: "Pending", recommended: "Recommended", approved: "Approved", all: "All sources",
      rejected: "Rejected", deferred: "Deferred", include: "Include", review: "Review", exclude: "Exclude",
      waiting: "Waiting", active: "Active", paused: "Paused", retry_wait: "Retry wait",
      failed: "Failed", cancelled: "Cancelled", completed: "Completed",
      waitingApproval: "Waiting for approval", candidatesCount: "{count} candidates",
      deduplicatedCount: "{count} deduplicated candidates", runMeta: "{id} · {stage} · corpus v{version}",
      workflowProgress: "Workflow progress: stage {current} of 6", unknown: "Unknown",
      noAbstract: "No abstract available.", noIdentifiers: "No identifiers or source URLs available.",
      jobQueued: "Job queued.", jobRunning: "Job running.", jobSucceeded: "Job completed.",
      mutationSucceeded: "Update saved.", runCancelled: "Run cancelled.",
      discoveryClosed: "Discovery closed.", eventsEmpty: "No events recorded.",
      loadingEvents: "Loading events...", reasonRequired: "A decision reason is required.",
      approvalFieldsRequired: "Category and contribution are required for approval.",
      tagsRequired: "Enter at least one tag before approval.",
      providerRequired: "Select at least one provider when discovery is enabled.",
      loadFailed: "Could not load the workbench.", requestFailed: "The request failed.",
      forbidden: "Mutation access was denied.", invalid_request: "Check the submitted fields.",
      invalid_json: "The server returned invalid data.", not_found: "The requested item was not found.",
      pending_candidates: "Resolve all pending candidates before closing discovery.",
      duplicate_resume_job: "A resume job is already active for this run.",
      internal_error: "The server could not complete the request.",
      network_error: "The server could not be reached.", jobFailed: "The workflow job failed."
    },
    "zh-CN": {
      brand: "文献综述工作台", workbenchActions: "工作台操作",
      events: "事件记录", resumeRun: "继续运行", closeDiscovery: "关闭检索",
      cancelRun: "取消运行", newRun: "新建文献检索", researchRuns: "研究任务",
      localStorage: "本地存储", database: "数据库", artifacts: "产物目录",
      loadingRuns: "正在加载研究任务...", loadingDetail: "正在加载运行详情...",
      noRuns: "暂无研究任务。", createFirstRun: "创建首个任务",
      retry: "重试", candidates: "候选论文", candidateFilters: "候选论文筛选",
      candidateTable: "检索到的候选文献", paper: "论文", year: "年份",
      source: "来源", score: "评分", status: "状态", noCandidates: "当前筛选条件下没有候选论文。",
      selectCandidate: "请选择候选论文", selectCandidateHint: "此处显示论文元数据与审批操作。",
      detailLoadFailed: "无法加载运行详情",
      abstractEvidence: "摘要证据", screeningRecommendation: "筛选建议",
      identifiers: "标识符与来源", approvalMetadata: "审批信息",
      category: "研究类别", contribution: "核心贡献", tags: "标签",
      decisionReason: "审批理由", approve: "批准", defer: "暂缓", reject: "拒绝",
      equivalentCli: "等价 CLI 命令：", close: "关闭", topic: "研究主题", corpusPath: "语料路径",
      enableDiscovery: "检索更多文献", providers: "检索平台",
      maxResults: "每条查询的最大结果数", startRun: "开始运行",
      pending: "待处理", recommended: "推荐", approved: "已批准", all: "全部来源",
      rejected: "已拒绝", deferred: "暂缓", include: "纳入", review: "复核", exclude: "排除",
      waiting: "等待中", active: "运行中", paused: "已暂停", retry_wait: "等待重试",
      failed: "失败", cancelled: "已取消", completed: "已完成",
      waitingApproval: "等待人工审批", candidatesCount: "{count} 篇候选论文",
      deduplicatedCount: "{count} 篇去重候选论文", runMeta: "{id} · {stage} · 语料版本 {version}",
      workflowProgress: "工作流进度：第 {current} 阶段，共 6 阶段", unknown: "未知",
      noAbstract: "暂无摘要。", noIdentifiers: "暂无标识符或来源链接。",
      jobQueued: "任务已进入队列。", jobRunning: "任务正在运行。", jobSucceeded: "任务已完成。",
      mutationSucceeded: "更新已保存。", runCancelled: "运行已取消。",
      discoveryClosed: "检索已关闭。", eventsEmpty: "暂无事件记录。",
      loadingEvents: "正在加载事件...", reasonRequired: "请填写审批理由。",
      approvalFieldsRequired: "批准论文时必须填写研究类别与核心贡献。",
      tagsRequired: "批准论文前请至少填写一个标签。",
      providerRequired: "启用检索时，请至少选择一个平台。",
      loadFailed: "无法加载工作台。", requestFailed: "请求失败。",
      forbidden: "没有修改权限。", invalid_request: "请检查提交字段。",
      invalid_json: "服务器返回了无效数据。", not_found: "找不到所请求的项目。",
      pending_candidates: "关闭检索前，请处理全部待审批论文。",
      duplicate_resume_job: "此运行已有继续任务正在执行。",
      internal_error: "服务器无法完成请求。", network_error: "无法连接服务器。",
      jobFailed: "工作流任务失败。"
    }
  };

  const config = readConfig();
  const apiPaths = Object.freeze({
    runs: "/api/runs",
    jobs: "/api/jobs/",
    events: "/events",
    candidates: "/candidates",
    approve: "/approve",
    defer: "/defer",
    reject: "/reject",
    resume: "/resume",
    cancel: "/cancel",
    closeDiscovery: "/close-discovery"
  });
  const runStatuses = Object.freeze([
    "waiting", "active", "paused", "retry_wait", "failed", "cancelled", "completed"
  ]);
  const state = {
    language: storedLanguage() || browserLanguage(),
    runs: [],
    detail: null,
    candidates: [],
    selectedRunId: null,
    selectedCandidateId: null,
    filter: "pending",
    detailState: "empty",
    detailError: "",
    runGeneration: 0,
    candidateGeneration: 0,
    activeRunRequests: new Set(),
    activeCandidateRequests: new Set(),
    pending: false,
    stopped: false,
    jobIds: new Set(),
    jobTimer: null,
    runTimer: null,
    loadingRuns: false,
    pollingJobs: false
  };

  const terminalRunStatuses = new Set(runStatuses.slice(4));
  const pollableRunStatuses = new Set(["waiting", "active", "retry_wait"]);
  const terminalJobStatuses = new Set(["succeeded", "failed"]);
  const stageGroups = [
    ["created", "planning"],
    ["discovering", "screening"],
    ["awaiting_corpus_approval"],
    ["drafting", "reviewing"],
    ["revising", "polishing"],
    ["final_verification", "completed"]
  ];

  function byId(id) {
    return document.getElementById(id);
  }

  function readConfig() {
    try {
      return JSON.parse(byId("workbench-config").textContent);
    } catch (_) {
      return {
        mutationToken: "",
        defaultCorpusPath: null,
        databasePath: "",
        artifactRoot: ""
      };
    }
  }

  function storedLanguage() {
    try {
      const value = localStorage.getItem("literature-review-language");
      return messages[value] ? value : null;
    } catch (_) {
      return null;
    }
  }

  function browserLanguage() {
    const languages = navigator.languages && navigator.languages.length
      ? navigator.languages
      : [navigator.language];
    return languages.some((language) => String(language).toLowerCase().startsWith("zh"))
      ? "zh-CN"
      : "en";
  }

  function t(key, values = {}) {
    let text = messages[state.language][key] || messages.en[key] || key;
    Object.entries(values).forEach(([name, value]) => {
      text = text.replaceAll(`{${name}}`, String(value));
    });
    return text;
  }

  function applyLanguage(language) {
    state.language = messages[language] ? language : "en";
    document.documentElement.lang = state.language;
    document.querySelectorAll("[data-i18n]").forEach((element) => {
      element.textContent = t(element.dataset.i18n);
    });
    document.querySelectorAll("[data-i18n-aria]").forEach((element) => {
      element.setAttribute("aria-label", t(element.dataset.i18nAria));
    });
    const toggle = byId("language-toggle");
    toggle.setAttribute("aria-label", state.language === "zh-CN" ? "Switch interface to English" : "切换界面为中文");
    renderAll();
  }

  class APIError extends Error {
    constructor(code, message, fields = {}) {
      super(message);
      this.name = "APIError";
      this.code = code;
      this.fields = fields;
    }
  }

  async function api(path, options = {}) {
    const method = options.method || "GET";
    const headers = { "Accept": "application/json" };
    if (method !== "GET") {
      headers["Content-Type"] = "application/json";
      headers["X-Workbench-Token"] = config.mutationToken;
    }
    let response;
    try {
      response = await fetch(path, {
        method,
        headers,
        body: options.body === undefined ? undefined : JSON.stringify(options.body),
        credentials: "same-origin"
      });
    } catch (_) {
      throw new APIError("network_error", "Network request failed.");
    }
    let payload;
    try {
      payload = await response.json();
    } catch (_) {
      throw new APIError("invalid_json", "Response was not valid JSON.");
    }
    if (!response.ok) {
      const error = payload && payload.error ? payload.error : {};
      throw new APIError(error.code || "request_failed", error.message || "Request failed.", error);
    }
    return payload;
  }

  function safeDate(value) {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? String(value || "") : date.toLocaleString(state.language);
  }

  function shortId(value) {
    const id = String(value || "");
    return id.length > 19 ? `${id.slice(0, 11)}…${id.slice(-6)}` : id;
  }

  function showFeedback(message, isError = false) {
    const element = byId("feedback");
    element.textContent = message;
    element.classList.toggle("error", isError);
    element.hidden = !message;
  }

  function errorMessage(error) {
    if (error instanceof APIError) {
      const base = t(error.code);
      if (error.code === "pending_candidates" && error.fields.pending_count !== undefined) {
        return `${base} (${error.fields.pending_count})`;
      }
      return base;
    }
    return t("requestFailed");
  }

  function setInitialState(name, message = "") {
    byId("app-loading").hidden = name !== "loading";
    byId("app-empty").hidden = name !== "empty";
    byId("app-error").hidden = name !== "error";
    byId("workbench-shell").hidden = name !== "ready";
    if (name === "error") byId("app-error-message").textContent = message;
  }

  function resetCandidateForm() {
    byId("candidate-category").value = "";
    byId("candidate-contribution").value = "";
    byId("candidate-tags").value = "";
    byId("candidate-reason").value = "";
  }

  function beginRunSelection(runId) {
    state.runGeneration += 1;
    state.candidateGeneration += 1;
    state.selectedRunId = runId;
    state.selectedCandidateId = null;
    state.detail = null;
    state.candidates = [];
    state.detailState = runId ? "loading" : "empty";
    state.detailError = "";
    clearTimeout(state.runTimer);
    resetCandidateForm();
    renderAll();
    return state.runGeneration;
  }

  function isCurrentRunRequest(runId, generation) {
    return state.selectedRunId === runId && state.runGeneration === generation;
  }

  function isCurrentCandidateRequest(runId, filter, runGeneration, candidateGeneration) {
    return isCurrentRunRequest(runId, runGeneration)
      && state.filter === filter
      && state.candidateGeneration === candidateGeneration;
  }

  async function refreshRunDetail(runId) {
    if (state.selectedRunId !== runId) return;
    state.runGeneration += 1;
    state.candidateGeneration += 1;
    await loadRunDetail(runId, state.runGeneration);
  }

  function candidateRequestPath(runId, filter) {
    const base = `${apiPaths.runs}/${encodeURIComponent(runId)}${apiPaths.candidates}`;
    if (filter === "pending" || filter === "approved") {
      return `${base}?status=${encodeURIComponent(filter)}`;
    }
    return base;
  }

  async function loadRuns({ preserveSelection = true } = {}) {
    if (state.loadingRuns || state.stopped) return;
    state.loadingRuns = true;
    if (!state.runs.length) setInitialState("loading");
    try {
      const runs = await api("/api/runs");
      state.runs = Array.isArray(runs) ? runs : [];
      const selectedExists = state.runs.some((run) => run.run_id === state.selectedRunId);
      if (!preserveSelection || !selectedExists) {
        beginRunSelection(state.runs[0] ? state.runs[0].run_id : null);
      }
      renderRuns();
      if (!state.selectedRunId) {
        setInitialState("empty");
        renderAll();
        return;
      }
      setInitialState("ready");
      await loadRunDetail(state.selectedRunId, state.runGeneration);
    } catch (error) {
      setInitialState("error", errorMessage(error));
    } finally {
      state.loadingRuns = false;
    }
  }

  async function loadRunDetail(runId, generation = state.runGeneration, { quiet = false } = {}) {
    if (!runId || state.stopped || state.activeRunRequests.has(generation)) return;
    state.activeRunRequests.add(generation);
    try {
      const detail = await api(`/api/runs/${encodeURIComponent(runId)}`);
      if (!isCurrentRunRequest(runId, generation)) return;
      state.detail = detail;
      state.detailState = "ready";
      state.detailError = "";
      renderAll();
      await loadCandidates(runId, state.filter, generation, { preserveSelection: true });
      scheduleRunPoll();
    } catch (error) {
      if (!isCurrentRunRequest(runId, generation)) return;
      state.detail = null;
      state.candidates = [];
      state.selectedCandidateId = null;
      state.detailState = "error";
      state.detailError = errorMessage(error);
      resetCandidateForm();
      renderAll();
      if (!quiet) showFeedback(state.detailError, true);
    } finally {
      state.activeRunRequests.delete(generation);
    }
  }

  async function loadCandidates(
    runId,
    filter,
    runGeneration = state.runGeneration,
    { preserveSelection = false } = {}
  ) {
    const candidateGeneration = ++state.candidateGeneration;
    const requestKey = `${runGeneration}:${candidateGeneration}`;
    state.activeCandidateRequests.add(requestKey);
    try {
      let candidates = await api(candidateRequestPath(runId, filter));
      if (filter === "recommended") {
        candidates = candidates.filter((candidate) => candidate.recommendation === "include");
      }
      if (!isCurrentCandidateRequest(runId, filter, runGeneration, candidateGeneration)) return;
      state.candidates = Array.isArray(candidates) ? candidates : [];
      const selectedExists = state.candidates.some(
        (candidate) => candidate.candidate_id === state.selectedCandidateId
      );
      if (!preserveSelection || !selectedExists) {
        state.selectedCandidateId = null;
        resetCandidateForm();
      }
      renderCandidates();
      renderCandidateDetail();
    } catch (error) {
      if (!isCurrentCandidateRequest(runId, filter, runGeneration, candidateGeneration)) return;
      state.candidates = [];
      state.selectedCandidateId = null;
      resetCandidateForm();
      renderCandidates();
      renderCandidateDetail();
      showFeedback(errorMessage(error), true);
    } finally {
      state.activeCandidateRequests.delete(requestKey);
    }
  }

  function renderAll() {
    renderRuns();
    renderRunDetail();
    renderCandidates();
    renderCandidateDetail();
    updateActions();
  }

  function renderRuns() {
    const list = byId("runs-list");
    list.replaceChildren();
    state.runs.forEach((run) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "run-button";
      button.disabled = state.pending;
      button.classList.toggle("selected", run.run_id === state.selectedRunId);
      if (run.run_id === state.selectedRunId) button.setAttribute("aria-current", "page");
      const title = document.createElement("strong");
      title.textContent = run.topic;
      const meta = document.createElement("span");
      const count = Object.values(run.candidate_counts || {}).reduce((sum, value) => sum + Number(value || 0), 0);
      meta.textContent = `${runStatusLabel(run)} · ${t("candidatesCount", { count })}`;
      button.append(title, meta);
      button.addEventListener("click", () => selectRun(run.run_id));
      list.append(button);
    });
  }

  function runStatusLabel(run) {
    if (run.current_stage === "awaiting_corpus_approval") return t("waitingApproval");
    return t(run.status || "unknown");
  }

  function renderRunDetail() {
    const run = state.detail && state.detail.run;
    if (!run) {
      const selected = state.runs.find((item) => item.run_id === state.selectedRunId);
      byId("run-topic").textContent = selected ? selected.topic : "";
      byId("run-meta").textContent = "";
      byId("run-status").textContent = state.detailState === "loading" ? t("loadingDetail") : "";
      byId("run-status").className = "status-badge";
      byId("run-progress").querySelectorAll(".progress-step").forEach((step) => {
        step.classList.remove("done", "current");
      });
      return;
    }
    byId("run-topic").textContent = run.topic;
    byId("run-meta").textContent = t("runMeta", {
      id: shortId(run.run_id),
      stage: String(run.current_stage || "").replaceAll("_", " "),
      version: run.corpus_version
    });
    const badge = byId("run-status");
    badge.textContent = runStatusLabel(run);
    badge.className = `status-badge ${run.status || ""}`;
    const current = Math.max(1, stageGroups.findIndex((group) => group.includes(run.current_stage)) + 1);
    const progress = byId("run-progress");
    progress.setAttribute("aria-valuenow", String(current));
    progress.setAttribute("aria-label", t("workflowProgress", { current }));
    progress.querySelectorAll(".progress-step").forEach((step, index) => {
      step.classList.toggle("done", index < current - 1 || run.status === "completed");
      step.classList.toggle("current", index === current - 1 && run.status !== "completed");
    });
  }

  function candidateCounts() {
    const stored = state.detail ? state.detail.candidate_counts || {} : {};
    const all = Object.values(stored).reduce((sum, value) => sum + Number(value || 0), 0);
    return {
      pending: Number(stored.pending || 0),
      recommended: state.detail
        ? (state.detail.candidates || []).filter(
            (candidate) => candidate.recommendation === "include"
          ).length
        : 0,
      approved: Number(stored.approved || 0),
      all
    };
  }

  function renderCandidates() {
    const body = byId("candidates-body");
    body.replaceChildren();
    const candidates = state.candidates;
    const counts = candidateCounts();
    document.querySelectorAll("[data-filter]").forEach((button) => {
      const filter = button.dataset.filter;
      button.textContent = `${t(filter)} ${counts[filter]}`;
      const active = filter === state.filter;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
    byId("candidate-count").textContent = t("deduplicatedCount", { count: counts.all });
    byId("candidates-empty").hidden = candidates.length !== 0;
    candidates.forEach((candidate) => body.append(candidateRow(candidate)));
  }

  function candidateRow(candidate) {
    const row = document.createElement("tr");
    row.className = "candidate-row";
    row.tabIndex = 0;
    row.classList.toggle("selected", candidate.candidate_id === state.selectedCandidateId);
    row.setAttribute("aria-selected", String(candidate.candidate_id === state.selectedCandidateId));
    const paper = document.createElement("td");
    const title = document.createElement("div");
    title.className = "paper-title";
    title.textContent = candidate.title;
    const authors = document.createElement("div");
    authors.className = "paper-authors";
    authors.textContent = (candidate.authors || []).join(", ");
    paper.append(title, authors);
    row.append(
      paper,
      labeledCell(candidate.year || "—", "year"),
      labeledCell(providerLabel(candidate), "source"),
      labeledCell(Number(candidate.relevance_score || 0).toFixed(2), "score", "score"),
      labeledCell(t(candidate.status || "unknown"), "status")
    );
    const select = () => {
      if (state.selectedCandidateId !== candidate.candidate_id) {
        resetCandidateForm();
      }
      state.selectedCandidateId = candidate.candidate_id;
      renderCandidates();
      renderCandidateDetail();
    };
    row.addEventListener("click", select);
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        select();
      }
    });
    return row;
  }

  function labeledCell(value, labelKey, className = "") {
    const cell = document.createElement("td");
    cell.textContent = String(value);
    cell.dataset.label = t(labelKey);
    if (className) cell.className = className;
    return cell;
  }

  function providerLabel(candidate) {
    const providers = candidate.provenance || [];
    const hasArxiv = candidate.arxiv_id || providers.some((value) => String(value).toLowerCase().includes("arxiv"));
    const hasS2 = candidate.semantic_scholar_id || providers.some((value) => String(value).toLowerCase().includes("semantic"));
    if (hasArxiv && hasS2) return "arXiv + S2";
    if (hasArxiv) return "arXiv";
    if (hasS2) return "S2";
    return providers.join(", ") || "—";
  }

  function selectedCandidate() {
    return state.candidates.find(
      (candidate) => candidate.candidate_id === state.selectedCandidateId
    ) || null;
  }

  function renderCandidateDetail() {
    const candidate = selectedCandidate();
    byId("candidate-empty").hidden = Boolean(candidate);
    byId("candidate-content").hidden = !candidate;
    byId("approval-form").querySelectorAll("input, textarea, button").forEach((control) => {
      control.disabled = state.pending || !candidate || candidate.status !== "pending";
    });
    if (!candidate) {
      const title = byId("candidate-state-title");
      const message = byId("candidate-state-message");
      if (state.detailState === "loading") {
        title.textContent = t("loadingDetail");
        message.textContent = "";
      } else if (state.detailState === "error") {
        title.textContent = t("detailLoadFailed");
        message.textContent = state.detailError;
      } else {
        title.textContent = t("selectCandidate");
        message.textContent = t("selectCandidateHint");
      }
      return;
    }
    byId("candidate-title").textContent = candidate.title;
    const meta = [candidate.venue, candidate.year, (candidate.authors || []).join(", ")].filter(Boolean);
    byId("candidate-meta").textContent = meta.join(" · ");
    byId("candidate-abstract").textContent = candidate.abstract || t("noAbstract");
    byId("candidate-recommendation").textContent = `${t(candidate.recommendation)} · ${Number(candidate.relevance_score || 0).toFixed(2)}`;
    renderIdentifiers(candidate);
  }

  function renderIdentifiers(candidate) {
    const container = byId("candidate-identifiers");
    container.replaceChildren();
    const identifiers = [
      candidate.doi ? `DOI: ${candidate.doi}` : null,
      candidate.arxiv_id ? `arXiv: ${candidate.arxiv_id}` : null,
      candidate.semantic_scholar_id ? `Semantic Scholar: ${candidate.semantic_scholar_id}` : null
    ].filter(Boolean);
    identifiers.forEach((value) => {
      const line = document.createElement("p");
      line.textContent = value;
      container.append(line);
    });
    (candidate.source_urls || []).forEach((url) => {
      const link = document.createElement("a");
      link.href = url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = url;
      container.append(link);
    });
    if (candidate.open_access_pdf_url) {
      const link = document.createElement("a");
      link.href = candidate.open_access_pdf_url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = candidate.open_access_pdf_url;
      container.append(link);
    }
    if (!container.childElementCount) container.textContent = t("noIdentifiers");
  }

  function updateActions() {
    const run = state.detail && state.detail.run;
    const hasRun = Boolean(run);
    byId("events-button").disabled = !hasRun || state.pending;
    byId("cancel-run-button").disabled = !hasRun || state.pending || terminalRunStatuses.has(run && run.status);
    byId("resume-run-button").disabled = !hasRun || state.pending || ["active", "completed", "cancelled"].includes(run && run.status);
    byId("close-discovery-button").disabled = !hasRun || state.pending || run.current_stage !== "awaiting_corpus_approval";
    byId("new-run-button").disabled = state.pending;
    document.querySelectorAll("[data-filter]").forEach((button) => {
      button.disabled = !hasRun || state.pending;
    });
  }

  async function selectRun(runId) {
    if (runId === state.selectedRunId) return;
    const generation = beginRunSelection(runId);
    await loadRunDetail(runId, generation);
  }

  async function withPending(operation) {
    if (state.pending) return;
    state.pending = true;
    updateActions();
    renderCandidateDetail();
    showFeedback("");
    try {
      await operation();
    } catch (error) {
      showFeedback(errorMessage(error), true);
    } finally {
      state.pending = false;
      updateActions();
      renderCandidateDetail();
    }
  }

  function showCommand(payload) {
    if (!payload || typeof payload.equivalent_command !== "string") return;
    byId("equivalent-command").textContent = payload.equivalent_command;
    byId("command-panel").hidden = false;
  }

  async function mutateRun(action, successKey) {
    const runId = state.selectedRunId;
    if (!runId) return;
    await withPending(async () => {
      const payload = await api(`/api/runs/${encodeURIComponent(runId)}/${action}`, { method: "POST", body: {} });
      showCommand(payload);
      if (payload.job_id) {
        state.jobIds.add(payload.job_id);
        showFeedback(t("jobQueued"));
        scheduleJobPoll();
      } else {
        showFeedback(t(successKey));
        await loadRuns();
      }
    });
  }

  async function decideCandidate(action) {
    const candidate = selectedCandidate();
    if (!candidate || !state.selectedRunId) return;
    const reason = byId("candidate-reason").value.trim();
    if (!reason) {
      showFeedback(t("reasonRequired"), true);
      byId("candidate-reason").focus();
      return;
    }
    const body = { reason };
    if (action === "approve") {
      body.category = byId("candidate-category").value.trim();
      body.contribution = byId("candidate-contribution").value.trim();
      const tags = byId("candidate-tags").value
        .split(",")
        .map((tag) => tag.trim())
        .filter(Boolean);
      if (!body.category || !body.contribution) {
        showFeedback(t("approvalFieldsRequired"), true);
        return;
      }
      if (tags.length === 0) {
        showFeedback(t("tagsRequired"), true);
        byId("candidate-tags").focus();
        return;
      }
      body.tags = tags;
    }
    const runId = state.selectedRunId;
    const runGeneration = state.runGeneration;
    await withPending(async () => {
      const path = `/api/runs/${encodeURIComponent(runId)}/candidates/${encodeURIComponent(candidate.candidate_id)}/${action}`;
      const payload = await api(path, { method: "POST", body });
      if (!isCurrentRunRequest(runId, runGeneration)) return;
      showCommand(payload);
      showFeedback(t("mutationSucceeded"));
      await refreshRunDetail(runId);
    });
  }

  async function startRun(event) {
    event.preventDefault();
    const discover = byId("new-run-discover").checked;
    const providers = Array.from(document.querySelectorAll('input[name="providers"]:checked')).map((input) => input.value);
    if (discover && providers.length === 0) {
      showFeedback(t("providerRequired"), true);
      return;
    }
    const body = {
      topic: byId("new-run-topic").value,
      corpus_path: byId("new-run-corpus").value,
      discover,
      providers,
      max_results: Number(byId("new-run-max-results").value)
    };
    await withPending(async () => {
      const payload = await api("/api/runs", { method: "POST", body });
      showCommand(payload);
      state.jobIds.add(payload.job_id);
      showFeedback(t("jobQueued"));
      closeDialog("new-run-dialog");
      scheduleJobPoll();
    });
  }

  function scheduleJobPoll(delay = 900) {
    clearTimeout(state.jobTimer);
    if (state.stopped || state.jobIds.size === 0) return;
    state.jobTimer = setTimeout(pollJobs, delay);
  }

  async function pollJobs() {
    if (state.pollingJobs || state.stopped) return;
    state.pollingJobs = true;
    let completed = false;
    try {
      for (const jobId of Array.from(state.jobIds)) {
        const job = await api(`/api/jobs/${encodeURIComponent(jobId)}`);
        showCommand(job);
        if (job.status === "running") showFeedback(t("jobRunning"));
        if (terminalJobStatuses.has(job.status)) {
          state.jobIds.delete(jobId);
          completed = true;
          showFeedback(job.status === "succeeded" ? t("jobSucceeded") : t("jobFailed"), job.status === "failed");
          if (job.result && job.result.run_id && job.result.run_id !== state.selectedRunId) {
            beginRunSelection(job.result.run_id);
          }
        }
      }
      if (completed) await loadRuns();
    } catch (error) {
      showFeedback(errorMessage(error), true);
    } finally {
      state.pollingJobs = false;
      scheduleJobPoll(1200);
    }
  }

  function scheduleRunPoll() {
    clearTimeout(state.runTimer);
    const run = state.detail && state.detail.run;
    if (state.stopped || !run || !pollableRunStatuses.has(run.status)) return;
    state.runTimer = setTimeout(async () => {
      if (!state.activeRunRequests.has(state.runGeneration)) {
        await loadRunDetail(run.run_id, state.runGeneration, { quiet: true });
      }
      else scheduleRunPoll();
    }, 2500);
  }

  async function openEvents() {
    if (!state.selectedRunId) return;
    const list = byId("events-list");
    list.replaceChildren();
    list.textContent = t("loadingEvents");
    openDialog("events-dialog");
    try {
      const events = await api(`/api/runs/${encodeURIComponent(state.selectedRunId)}/events`);
      list.replaceChildren();
      if (!events.length) {
        list.textContent = t("eventsEmpty");
        return;
      }
      events.forEach((event) => {
        const item = document.createElement("article");
        item.className = "event-item";
        const title = document.createElement("strong");
        title.textContent = event.event_type;
        const meta = document.createElement("span");
        meta.textContent = [event.stage, safeDate(event.created_at)].filter(Boolean).join(" · ");
        const payload = document.createElement("code");
        payload.textContent = JSON.stringify(event.payload);
        item.append(title, meta, payload);
        list.append(item);
      });
    } catch (error) {
      list.textContent = errorMessage(error);
    }
  }

  function openDialog(id) {
    const dialog = byId(id);
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
  }

  function closeDialog(id) {
    const dialog = byId(id);
    if (typeof dialog.close === "function") dialog.close();
    else dialog.removeAttribute("open");
  }

  function bindEvents() {
    byId("language-toggle").addEventListener("click", () => {
      const language = state.language === "zh-CN" ? "en" : "zh-CN";
      try { localStorage.setItem("literature-review-language", language); } catch (_) {}
      applyLanguage(language);
    });
    byId("new-run-button").addEventListener("click", () => openDialog("new-run-dialog"));
    byId("empty-new-run-button").addEventListener("click", () => openDialog("new-run-dialog"));
    byId("events-button").addEventListener("click", openEvents);
    byId("resume-run-button").addEventListener("click", () => mutateRun("resume", "jobQueued"));
    byId("cancel-run-button").addEventListener("click", () => mutateRun("cancel", "runCancelled"));
    byId("close-discovery-button").addEventListener("click", () => mutateRun("close-discovery", "discoveryClosed"));
    byId("retry-load-button").addEventListener("click", () => loadRuns({ preserveSelection: false }));
    byId("new-run-form").addEventListener("submit", startRun);
    byId("approval-form").addEventListener("submit", (event) => {
      event.preventDefault();
      decideCandidate("approve");
    });
    byId("defer-button").addEventListener("click", () => decideCandidate("defer"));
    byId("reject-button").addEventListener("click", () => decideCandidate("reject"));
    byId("candidate-filters").addEventListener("click", (event) => {
      const button = event.target.closest("[data-filter]");
      if (!button || button.disabled || !state.selectedRunId) return;
      state.filter = button.dataset.filter;
      state.selectedCandidateId = null;
      state.candidates = [];
      resetCandidateForm();
      renderCandidates();
      renderCandidateDetail();
      loadCandidates(state.selectedRunId, state.filter, state.runGeneration);
    });
    document.querySelectorAll("[data-close-dialog]").forEach((button) => {
      button.addEventListener("click", () => closeDialog(button.dataset.closeDialog));
    });
    byId("new-run-discover").addEventListener("change", (event) => {
      document.querySelectorAll('input[name="providers"]').forEach((input) => {
        input.disabled = !event.target.checked;
      });
    });
    window.addEventListener("pagehide", () => {
      state.stopped = true;
      clearTimeout(state.jobTimer);
      clearTimeout(state.runTimer);
    });
  }

  function initialize() {
    byId("new-run-corpus").value = config.defaultCorpusPath || "";
    byId("database-path").textContent = config.databasePath || "";
    byId("artifact-root").textContent = config.artifactRoot || "";
    bindEvents();
    applyLanguage(state.language);
    loadRuns({ preserveSelection: false });
  }

  initialize();
})();
