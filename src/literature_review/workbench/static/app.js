(() => {
  "use strict";

  const messages = {
    "en": {
      brand: "Literature Review Workbench", workbenchActions: "Workbench actions",
      events: "Events", previewSurvey: "Preview survey", downloadSurvey: "Download Markdown",
      exportRun: "Export audit ZIP", resumeRun: "Resume", closeDiscovery: "Close discovery",
      cancelRun: "Cancel run", deleteRun: "Delete run", newRun: "New discovery run",
      researchRuns: "Research runs",
      localStorage: "Local storage", database: "Database", artifacts: "Artifacts",
      runtimeBackend: "Backend", runtimeModel: "Model",
      runtimeExecutor: "Current executor", runtimeError: "Last safe error",
      backend_deterministic: "Deterministic", backend_api: "API",
      model_deterministic: "Local rules", model_multiple_models: "Multiple models",
      model_api_configured: "API configured", error_none: "None",
      executor_workflow_planner: "Workflow planner",
      executor_literature_discovery: "Literature discovery",
      executor_screening_agent: "Screening agent",
      executor_human_approval: "Human approval",
      executor_document_acquisition: "PDF acquisition",
      executor_evidence_indexing: "Evidence indexing",
      executor_claim_verification: "Claim verification",
      executor_human_evidence_review: "Human evidence review",
      executor_model_agent_loop: "Model-backed agent loop",
      executor_deterministic_agent_loop: "Deterministic agent loop",
      executor_workflow_engine: "Workflow engine", executor_completed: "Completed",
      retryable_api_failure: "Retryable API failure",
      permanent_api_failure: "Permanent API failure",
      retryable_workflow_failure: "Retryable workflow failure",
      workflow_failure: "Workflow failure",
      loadingRuns: "Loading research runs...", loadingDetail: "Loading run details...",
      noRuns: "No research runs yet.", createFirstRun: "Create the first run",
      retry: "Retry", candidates: "Candidates", candidateFilters: "Candidate filters",
      candidateTable: "Discovered literature candidates", paper: "Paper", year: "Year",
      source: "Source", score: "Score", status: "Status", noCandidates: "No candidates match this filter.",
      discoveryEmptyTitle: "Discovery completed with no approval candidates.",
      discoveryEmptyHint: "No papers are ready for approval. Review the discovery summary, then retry discovery or continue with the seed corpus.",
      discoverySummaryTitle: "Discovery summary", discoveryReview: "Discovery needs review",
      retryDiscovery: "Retry discovery", retryDiscoveryHint: "Runs another discovery attempt in this research run. Existing candidates and decisions are preserved.",
      runDiscoveryAttempt: "Run discovery attempt", discoveryRetryQueued: "Discovery retry queued.",
      customQueries: "Custom queries", customQueriesPlaceholder: "One exact scholarly query per line",
      customQueriesHint: "Optional. Enter one exact scholarly query per line; leave blank to use four generated queries.",
      retryQueryHint: "Edit the generated suggestions or enter one exact query per line.",
      queryRequired: "Enter no more than eight queries, one per line.",
      funnelRaw: "Retrieved", funnelNormalized: "Normalized", funnelDeduplicated: "Deduplicated",
      funnelScreened: "Screened", funnelNew: "New candidates", discoveryAttempts: "Attempts",
      attemptSummary: "Attempt {number} · {status} · {providers}",
      continueSeedCorpus: "Continue with seed corpus",
      discoveryIssue_ok: "Discovery ready",
      discoveryIssue_not_run: "Discovery not run",
      discoveryIssue_running: "Discovery running",
      discoveryIssue_zero_candidates: "No approval candidates",
      discoveryIssue_partial_provider_failure: "Provider warning",
      discoveryIssue_provider_failure: "Discovery provider failure",
      discoveryMessage_ok: "Discovery found candidate papers for human screening.",
      discoveryMessage_not_run: "This run did not use automatic literature discovery.",
      discoveryMessage_running: "Automatic discovery is still running. Provider results and candidate counts may change while the job is active.",
      discoveryMessage_zero_candidates: "Automatic discovery ran, but no provider result survived deduplication and screening. The workflow is paused so you can review the cause before drafting.",
      discoveryMessage_zero_candidates_completed: "Automatic discovery ran, but no provider result survived deduplication and screening. This older run already completed; new zero-candidate runs pause for review before drafting.",
      discoveryMessage_partial_provider_failure: "Discovery found candidates, but at least one provider failed or was rate limited. Review the provider details before continuing.",
      discoveryMessage_provider_failure: "The selected providers did not return a usable response. Adjust the providers or queries, then retry this run.",
      providerSummary: "{provider}: {queries} queries, {results} results, {failures} failures",
      providerError_rate_limited: "Latest error: rate limited. Add an API key or retry later.",
      providerError_network_unavailable: "Latest error: network unavailable. Retry later.",
      providerError_timeout: "Latest error: timeout. Retry later.",
      providerError_provider_error: "Latest error: provider request failed.",
      providerErrors: "Observed errors: {errors}",
      providerErrorLabel_rate_limited: "rate limited",
      providerErrorLabel_network_unavailable: "network unavailable",
      providerErrorLabel_timeout: "timeout",
      providerErrorLabel_provider_error: "provider request failed",
      recommendation_broaden_topic: "Use a more specific scholarly query or broaden the topic wording.",
      recommendation_increase_max_results: "Increase the maximum results per query.",
      recommendation_try_arxiv_only: "Try arXiv only if Semantic Scholar is rate limited.",
      recommendation_review_seed_corpus: "Review the seed corpus; it may not match the research topic.",
      recommendation_configure_semantic_scholar_key: "Configure SEMANTIC_SCHOLAR_API_KEY for a higher Semantic Scholar quota.",
      recommendation_retry_discovery_later: "Retry discovery after the provider or network recovers.",
      recommendation_continue_with_seed_corpus: "Continue only if drafting from the current seed corpus is intentional.",
      selectCandidate: "Select a candidate", selectCandidateHint: "Candidate metadata and decisions appear here.",
      detailLoadFailed: "Run details unavailable",
      abstractEvidence: "Abstract evidence", screeningRecommendation: "Screening recommendation",
      identifiers: "Identifiers and sources", approvalMetadata: "Approval metadata",
      category: "Category", contribution: "Contribution", tags: "Tags",
      decisionReason: "Decision reason", approve: "Approve", defer: "Defer", reject: "Reject",
      equivalentCli: "Equivalent CLI:", close: "Close", topic: "Topic", runId: "Run ID",
      corpusPath: "Corpus path", deletePermanently: "Delete permanently",
      deleteRunScope: "SQLite history and run artifacts will be removed.",
      deleteRunUnaffected: "The seed corpus and shared provider cache are unaffected.",
      enableDiscovery: "Discover additional literature", providers: "Providers",
      enableFullText: "Download PDFs and verify claims against full text",
      maxResults: "Maximum results per query", startRun: "Start run",
      evidenceReview: "Claim evidence review", claim: "Claim", citation: "Citation", pages: "Pages",
      claimEvidence: "Claim evidence", noEvidenceClaims: "No claim evidence is available yet.",
      evidenceSummary: "{documents} documents · {claims} claims · {blocking} blocking",
      verification_supported: "Supported", verification_partially_supported: "Partially supported",
      verification_contradicted: "Contradicted", verification_not_found: "Not found",
      verification_full_text_unavailable: "Full text unavailable",
      verification_missing_citation: "Missing citation", noCitation: "No citation",
      requireRevision: "Require revision", acceptRisk: "Accept unavailable-text risk",
      pdfPath: "Local PDF path", importPdf: "Import and index PDF", exportReady: "Audit ZIP created locally.",
      evidenceDecisionSaved: "Evidence decision saved.", pdfImported: "PDF imported and indexed.",
      evidenceDecisionSuperseded: "A previous decision is retained in history but no longer applies because the evidence changed.",
      pending: "Pending", recommended: "Recommended", approved: "Approved", all: "All sources",
      rejected: "Rejected", deferred: "Deferred", include: "Include", review: "Review", exclude: "Exclude",
      waiting: "Waiting", active: "Active", paused: "Paused", retry_wait: "Retry wait",
      running: "Running", succeeded: "Succeeded", partial: "Partial",
      failed: "Failed", cancelled: "Cancelled", completed: "Completed",
      waitingApproval: "Waiting for approval", candidatesCount: "{count} candidates",
      deduplicatedCount: "{count} deduplicated candidates", runMeta: "{id} · {stage} · corpus v{version}",
      workflowProgress: "Workflow progress: stage {current} of 6", unknown: "Unknown",
      noAbstract: "No abstract available.", noIdentifiers: "No identifiers or source URLs available.",
      jobQueued: "Job queued.", jobRunning: "Job running.", jobSucceeded: "Job completed.",
      jobInterrupted: "A previous Job was interrupted when the Workbench backend stopped. Review the run and use Resume when appropriate.",
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
      approval_not_allowed: "Candidate decisions are only allowed while the run is waiting for corpus approval.",
      duplicate_resume_job: "A resume job is already active for this run.",
      run_busy: "This run is still executing. Wait for it to stop before deleting it.",
      run_deletion_busy: "This run is being deleted. Reload the run list and try again.",
      run_not_deletable: "This run can only be deleted after it is cancelled, completed, or failed.",
      run_deletion_conflict: "The run changed status during deletion. Review its current status and try again.",
      runDeleted: "Run deleted permanently.",
      deleteCleanupPending: "Run deleted, but artifact cleanup is still pending.",
      internal_error: "The server could not complete the request.",
      network_error: "The server could not be reached.", jobFailed: "The workflow job failed."
    },
    "zh-CN": {
      brand: "文献综述工作台", workbenchActions: "工作台操作",
      events: "事件记录", previewSurvey: "预览综述", downloadSurvey: "下载 Markdown",
      exportRun: "导出审计 ZIP", resumeRun: "继续运行", closeDiscovery: "关闭检索",
      cancelRun: "取消运行", deleteRun: "删除运行", newRun: "新建文献检索",
      researchRuns: "研究任务",
      localStorage: "本地存储", database: "数据库", artifacts: "产物目录",
      runtimeBackend: "后端", runtimeModel: "模型",
      runtimeExecutor: "当前执行者", runtimeError: "最近安全错误",
      backend_deterministic: "确定性", backend_api: "API",
      model_deterministic: "本地规则", model_multiple_models: "多个模型",
      model_api_configured: "已配置 API", error_none: "无",
      executor_workflow_planner: "工作流规划",
      executor_literature_discovery: "文献检索",
      executor_screening_agent: "筛选 Agent",
      executor_human_approval: "人工审批",
      executor_document_acquisition: "PDF 获取",
      executor_evidence_indexing: "证据索引",
      executor_claim_verification: "论断核验",
      executor_human_evidence_review: "人工证据审查",
      executor_model_agent_loop: "模型 Agent 回环",
      executor_deterministic_agent_loop: "确定性 Agent 回环",
      executor_workflow_engine: "工作流引擎", executor_completed: "已完成",
      retryable_api_failure: "可重试 API 失败",
      permanent_api_failure: "永久 API 失败",
      retryable_workflow_failure: "可重试工作流失败",
      workflow_failure: "工作流失败",
      loadingRuns: "正在加载研究任务...", loadingDetail: "正在加载运行详情...",
      noRuns: "暂无研究任务。", createFirstRun: "创建首个任务",
      retry: "重试", candidates: "候选论文", candidateFilters: "候选论文筛选",
      candidateTable: "检索到的候选文献", paper: "论文", year: "年份",
      source: "来源", score: "评分", status: "状态", noCandidates: "当前筛选条件下没有候选论文。",
      discoveryEmptyTitle: "检索已完成，但没有需要审批的候选论文。",
      discoveryEmptyHint: "当前没有可审批论文。请先查看上方检索摘要，再选择重新检索或用种子语料继续。",
      discoverySummaryTitle: "检索摘要", discoveryReview: "检索需要确认",
      retryDiscovery: "重新检索", retryDiscoveryHint: "在当前研究任务中运行新一轮检索；已有候选论文和审批决定都会保留。",
      runDiscoveryAttempt: "运行本轮检索", discoveryRetryQueued: "重新检索任务已进入队列。",
      customQueries: "自定义检索式", customQueriesPlaceholder: "每行填写一条精确的学术检索式",
      customQueriesHint: "可选。每行一条精确检索式；留空时自动生成四条检索式。",
      retryQueryHint: "可以修改系统建议，也可以每行填写一条精确检索式。",
      queryRequired: "最多填写八条检索式，每行一条。",
      funnelRaw: "原始结果", funnelNormalized: "标准化", funnelDeduplicated: "去重后",
      funnelScreened: "筛选后", funnelNew: "新增候选", discoveryAttempts: "检索轮次",
      attemptSummary: "第 {number} 轮 · {status} · {providers}",
      continueSeedCorpus: "使用种子语料继续",
      discoveryIssue_ok: "检索可用",
      discoveryIssue_not_run: "未运行检索",
      discoveryIssue_running: "正在检索",
      discoveryIssue_zero_candidates: "没有可审批候选",
      discoveryIssue_partial_provider_failure: "检索平台警告",
      discoveryIssue_provider_failure: "检索平台失败",
      discoveryMessage_ok: "自动检索找到了候选论文，可以进入人工筛选。",
      discoveryMessage_not_run: "此任务没有启用自动文献检索。",
      discoveryMessage_running: "自动检索仍在运行。任务完成前，检索结果和候选数量都可能继续变化。",
      discoveryMessage_zero_candidates: "自动检索已经运行，但没有文献通过去重和筛选。工作流已暂停，方便你先确认原因再生成综述。",
      discoveryMessage_zero_candidates_completed: "自动检索已经运行，但没有文献通过去重和筛选。这个旧任务已经完成；新的 0 候选任务会在生成综述前暂停等待确认。",
      discoveryMessage_partial_provider_failure: "检索找到了候选论文，但至少一个平台失败或被限流。继续前建议查看平台细节。",
      discoveryMessage_provider_failure: "所选平台没有返回可用结果。请调整平台或检索式，然后在当前任务中重新检索。",
      providerSummary: "{provider}：{queries} 次查询，{results} 条结果，{failures} 次失败",
      providerError_rate_limited: "最近错误：请求被限流。可以配置 API key 或稍后重试。",
      providerError_network_unavailable: "最近错误：网络不可用。可以稍后重试。",
      providerError_timeout: "最近错误：请求超时。可以稍后重试。",
      providerError_provider_error: "最近错误：检索平台请求失败。",
      providerErrors: "出现过的错误：{errors}",
      providerErrorLabel_rate_limited: "请求限流",
      providerErrorLabel_network_unavailable: "网络不可用",
      providerErrorLabel_timeout: "请求超时",
      providerErrorLabel_provider_error: "平台请求失败",
      recommendation_broaden_topic: "调整为更学术的查询词，或适当放宽主题表述。",
      recommendation_increase_max_results: "调高每条查询的最大结果数。",
      recommendation_try_arxiv_only: "如果 Semantic Scholar 被限流，可以先只用 arXiv。",
      recommendation_review_seed_corpus: "检查种子语料；它可能和当前研究主题不匹配。",
      recommendation_configure_semantic_scholar_key: "配置 SEMANTIC_SCHOLAR_API_KEY，提高 Semantic Scholar 配额。",
      recommendation_retry_discovery_later: "等待平台或网络恢复后重新检索。",
      recommendation_continue_with_seed_corpus: "只有在确认当前种子语料适合主题时，才继续生成综述。",
      selectCandidate: "请选择候选论文", selectCandidateHint: "此处显示论文元数据与审批操作。",
      detailLoadFailed: "无法加载运行详情",
      abstractEvidence: "摘要证据", screeningRecommendation: "筛选建议",
      identifiers: "标识符与来源", approvalMetadata: "审批信息",
      category: "研究类别", contribution: "核心贡献", tags: "标签",
      decisionReason: "审批理由", approve: "批准", defer: "暂缓", reject: "拒绝",
      equivalentCli: "等价 CLI 命令：", close: "关闭", topic: "研究主题", runId: "运行 ID",
      corpusPath: "语料路径", deletePermanently: "永久删除",
      deleteRunScope: "SQLite 历史记录和运行产物将被删除。",
      deleteRunUnaffected: "种子语料库和共享检索平台缓存不受影响。",
      enableDiscovery: "检索更多文献", providers: "检索平台",
      enableFullText: "下载 PDF，并按全文证据核验论断",
      maxResults: "每条查询的最大结果数", startRun: "开始运行",
      evidenceReview: "论断证据审查", claim: "论断", citation: "引用", pages: "页码",
      claimEvidence: "论断证据", noEvidenceClaims: "尚无可审查的论断证据。",
      evidenceSummary: "{documents} 份文档 · {claims} 条论断 · {blocking} 条阻塞",
      verification_supported: "已支持", verification_partially_supported: "部分支持",
      verification_contradicted: "相互矛盾", verification_not_found: "未找到支持证据",
      verification_full_text_unavailable: "全文不可得",
      verification_missing_citation: "缺少引用", noCitation: "无引用",
      requireRevision: "要求修订", acceptRisk: "接受全文不可得风险",
      pdfPath: "本地 PDF 路径", importPdf: "导入并索引 PDF", exportReady: "审计 ZIP 已生成到本地。",
      evidenceDecisionSaved: "证据决定已保存。", pdfImported: "PDF 已导入并完成索引。",
      evidenceDecisionSuperseded: "历史决定仍保留在审计记录中，但因证据已变化，不再适用于当前结果。",
      pending: "待处理", recommended: "推荐", approved: "已批准", all: "全部来源",
      rejected: "已拒绝", deferred: "暂缓", include: "纳入", review: "复核", exclude: "排除",
      waiting: "等待中", active: "运行中", paused: "已暂停", retry_wait: "等待重试",
      running: "运行中", succeeded: "成功", partial: "部分成功",
      failed: "失败", cancelled: "已取消", completed: "已完成",
      waitingApproval: "等待人工审批", candidatesCount: "{count} 篇候选论文",
      deduplicatedCount: "{count} 篇去重候选论文", runMeta: "{id} · {stage} · 语料版本 {version}",
      workflowProgress: "工作流进度：第 {current} 阶段，共 6 阶段", unknown: "未知",
      noAbstract: "暂无摘要。", noIdentifiers: "暂无标识符或来源链接。",
      jobQueued: "任务已进入队列。", jobRunning: "任务正在运行。", jobSucceeded: "任务已完成。",
      jobInterrupted: "工作台后端停止时有任务尚未完成，现已标记为中断。请检查对应运行，并在合适时点击继续运行。",
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
      approval_not_allowed: "仅可在任务等待语料审批时处理候选论文。",
      duplicate_resume_job: "此运行已有继续任务正在执行。",
      run_busy: "此运行仍在执行。请等待执行停止后再删除。",
      run_deletion_busy: "此运行正在删除。请刷新运行列表后重试。",
      run_not_deletable: "仅可删除已取消、已完成或失败的运行。",
      run_deletion_conflict: "删除期间运行状态发生变化，请检查当前状态后重试。",
      runDeleted: "运行已永久删除。",
      deleteCleanupPending: "运行已删除，但产物清理仍在等待完成。",
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
    closeDiscovery: "/close-discovery",
    retryDiscovery: "/retry-discovery"
  });
  const runStatuses = Object.freeze([
    "waiting", "active", "paused", "retry_wait", "failed", "cancelled", "completed"
  ]);
  const selectedRunQueryParam = "run";
  const selectedRunStorageKey = "literature-review-selected-run-id";
  const acknowledgedInterruptedJobStorageKey = "literature-review-interrupted-job-id";
  const state = {
    language: storedLanguage() || browserLanguage(),
    runs: [],
    detail: null,
    candidates: [],
    selectedRunId: storedSelectedRunId(),
    selectedCandidateId: null,
    selectedClaimId: null,
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
    startJobs: new Map(),
    manualSelectionVersion: 0,
    jobTimer: null,
    runTimer: null,
    loadingRuns: false,
    pollingJobs: false,
    deletingRun: false,
    deleteTarget: null,
    suppressDeleteFocusRestore: false,
    stableFeedback: null,
    runReloadPromise: null,
    queuedRunReload: null,
    runReloadGeneration: 0
  };

  const terminalRunStatuses = new Set(runStatuses.slice(4));
  const deletableRunStatuses = new Set(["cancelled", "completed", "failed"]);
  const pollableRunStatuses = new Set(["waiting", "active", "retry_wait"]);
  const terminalJobStatuses = new Set(["succeeded", "failed", "interrupted"]);
  const stageGroups = [
    ["created", "planning"],
    ["discovering", "screening"],
    ["awaiting_corpus_approval", "acquiring_documents", "indexing_evidence"],
    ["drafting", "reviewing", "revising", "polishing", "final_verification"],
    ["claim_verification", "awaiting_evidence_review"],
    ["completed"]
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
        artifactRoot: "",
        providers: []
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

  function urlSelectedRunId() {
    try {
      return new URL(window.location.href).searchParams.get(selectedRunQueryParam) || null;
    } catch (_) {
      return null;
    }
  }

  function storedSelectedRunId() {
    const fromUrl = urlSelectedRunId();
    if (fromUrl) return fromUrl;
    try {
      return localStorage.getItem(selectedRunStorageKey) || null;
    } catch (_) {
      return null;
    }
  }

  function updateSelectedRunUrl(runId) {
    try {
      const url = new URL(window.location.href);
      if (runId) url.searchParams.set(selectedRunQueryParam, runId);
      else url.searchParams.delete(selectedRunQueryParam);
      window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
    } catch (_) {}
  }

  function storeSelectedRunId(runId) {
    try {
      if (runId) localStorage.setItem(selectedRunStorageKey, runId);
      else localStorage.removeItem(selectedRunStorageKey);
    } catch (_) {}
    updateSelectedRunUrl(runId);
  }

  function runHref(runId) {
    try {
      const url = new URL(window.location.href);
      url.searchParams.set(selectedRunQueryParam, runId);
      return `${url.pathname}${url.search}${url.hash}`;
    } catch (_) {
      return `?${selectedRunQueryParam}=${encodeURIComponent(runId)}`;
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

  function renderProviderOptions() {
    const providers = Array.isArray(config.providers) ? config.providers : [];
    [
      ["provider-options", "providers", "provider"],
      ["retry-provider-options", "retry-providers", "retry-provider"]
    ].forEach(([containerId, name, prefix]) => {
      const container = byId(containerId);
      container.replaceChildren();
      providers.forEach((provider) => {
        if (!provider || !provider.id) return;
        const label = document.createElement("label");
        label.className = "check-row";
        const input = document.createElement("input");
        input.type = "checkbox";
        input.name = name;
        input.value = provider.id;
        input.checked = provider.default_enabled !== false;
        input.id = `${prefix}-${provider.id.replaceAll("_", "-")}`;
        const text = document.createElement("span");
        text.textContent = provider.label || provider.id;
        label.htmlFor = input.id;
        label.append(input, text);
        container.append(label);
      });
    });
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
    document.querySelectorAll("[data-i18n-placeholder]").forEach((element) => {
      element.setAttribute("placeholder", t(element.dataset.i18nPlaceholder));
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

  function showFeedback(message, isError = false, options = {}) {
    if (options.background && state.stableFeedback && !isError) return;
    if (!options.background || isError) {
      state.stableFeedback = options.persistent && message
        ? { message, isError, warning: Boolean(options.warning) }
        : null;
    }
    const element = byId("feedback");
    element.textContent = message;
    element.classList.toggle("error", isError);
    element.classList.toggle("warning", Boolean(options.warning));
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
    storeSelectedRunId(runId);
    state.selectedCandidateId = null;
    state.selectedClaimId = null;
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

  async function performRunLoad({ preserveSelection, fallbackToFirst, generation }) {
    state.loadingRuns = true;
    if (!state.runs.length && generation === state.runReloadGeneration) {
      setInitialState("loading");
    }
    try {
      const runs = await api("/api/runs");
      if (generation !== state.runReloadGeneration) return;
      state.runs = Array.isArray(runs) ? runs : [];
      const selectedExists = state.runs.some((run) => run.run_id === state.selectedRunId);
      if (!preserveSelection || (!selectedExists && fallbackToFirst)) {
        beginRunSelection(state.runs[0] ? state.runs[0].run_id : null);
      } else if (state.selectedRunId) {
        if (selectedExists) storeSelectedRunId(state.selectedRunId);
        else beginRunSelection(null);
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
      if (generation === state.runReloadGeneration) {
        setInitialState("error", errorMessage(error));
      }
    } finally {
      state.loadingRuns = false;
    }
  }

  async function loadRuns({
    preserveSelection = true,
    force = false,
    fallbackToFirst = false
  } = {}) {
    if (state.stopped) return;
    if (force) {
      state.runReloadGeneration += 1;
    }
    let request = {
      preserveSelection,
      fallbackToFirst,
      generation: state.runReloadGeneration
    };
    if (state.runReloadPromise) {
      if (force) {
        state.queuedRunReload = request;
      }
      return state.runReloadPromise;
    }
    state.runReloadPromise = (async () => {
      while (request && !state.stopped) {
        state.queuedRunReload = null;
        await performRunLoad(request);
        request = state.queuedRunReload;
      }
    })();
    try {
      await state.runReloadPromise;
    } finally {
      state.runReloadPromise = null;
    }
  }

  async function recoverActiveJobs() {
    try {
      const [jobs, history] = await Promise.all([
        api("/api/jobs?status=active"),
        api("/api/jobs")
      ]);
      if (!Array.isArray(jobs)) throw new Error("invalid active job response");
      if (!Array.isArray(history)) throw new Error("invalid job history response");
      const interrupted = history.slice().reverse().find((job) => (
        job && job.job_id && job.status === "interrupted"
      ));
      if (
        interrupted
        && localStorage.getItem(acknowledgedInterruptedJobStorageKey) !== interrupted.job_id
      ) {
        localStorage.setItem(acknowledgedInterruptedJobStorageKey, interrupted.job_id);
        showFeedback(t("jobInterrupted"), true, { background: true });
      }
      jobs.forEach((job) => {
        if (!job || !job.job_id || !["queued", "running"].includes(job.status)) return;
        state.jobIds.add(job.job_id);
        if (job.kind === "start") {
          state.startJobs.set(job.job_id, {
            topic: "",
            submittedAtMs: Date.now(),
            selectionVersion: state.manualSelectionVersion,
            autoSelected: true,
            resultRunId: null
          });
        }
      });
      if (!state.jobIds.size) return;
      const hasRunningJob = jobs.some((job) => job && job.status === "running");
      showFeedback(
        t(hasRunningJob ? "jobRunning" : "jobQueued"),
        false,
        { background: true }
      );
      scheduleJobPoll(0);
    } catch (error) {
      showFeedback(errorMessage(error), true, { background: true });
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
      const evidenceClaims = detail.evidence && Array.isArray(detail.evidence.claims)
        ? detail.evidence.claims : [];
      if (!evidenceClaims.some((claim) => claim.claim_id === state.selectedClaimId)) {
        state.selectedClaimId = null;
      }
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
    renderDiscoverySummary();
    renderEvidence();
    renderCandidates();
    renderCandidateDetail();
    updateActions();
    renderDeleteRunDialog();
  }

  function renderRuns() {
    const list = byId("runs-list");
    list.replaceChildren();
    state.runs.forEach((run) => {
      const link = document.createElement("a");
      link.href = runHref(run.run_id);
      link.className = "run-button";
      link.classList.toggle("selected", run.run_id === state.selectedRunId);
      if (run.run_id === state.selectedRunId) link.setAttribute("aria-current", "page");
      if (state.pending || state.deletingRun) link.setAttribute("aria-disabled", "true");
      const title = document.createElement("strong");
      title.textContent = run.topic;
      const meta = document.createElement("span");
      const count = Object.values(run.candidate_counts || {}).reduce((sum, value) => sum + Number(value || 0), 0);
      meta.textContent = `${runStatusLabel(run)} · ${t("candidatesCount", { count })}`;
      link.append(title, meta);
      link.addEventListener("click", (event) => {
        if (link.getAttribute("aria-disabled") === "true") {
          event.preventDefault();
          return;
        }
        if (
          event.defaultPrevented
          || event.button !== 0
          || event.metaKey
          || event.ctrlKey
          || event.shiftKey
          || event.altKey
        ) return;
        event.preventDefault();
        selectRun(run.run_id);
      });
      list.append(link);
    });
  }

  function runStatusLabel(run) {
    const counts = run.candidate_counts || (
      state.detail && state.detail.run && state.detail.run.run_id === run.run_id
        ? state.detail.candidate_counts || {}
        : {}
    );
    const count = Object.values(counts).reduce((sum, value) => sum + Number(value || 0), 0);
    if (run.current_stage === "awaiting_corpus_approval" && count === 0) return t("discoveryReview");
    if (run.current_stage === "awaiting_corpus_approval") return t("waitingApproval");
    return t(run.status || "unknown");
  }

  function renderRuntime(runtime) {
    runtime = runtime || {};
    const backend = runtime.backend || "deterministic";
    byId("runtime-backend").textContent = t(`backend_${backend}`);
    byId("runtime-model").textContent = runtimeModelLabel(runtime);
    byId("runtime-executor").textContent = t(`executor_${runtime.current_executor || "workflow_engine"}`);
    byId("runtime-error").textContent = runtime.safe_error_category
      ? t(runtime.safe_error_category)
      : t("error_none");
  }

  function runtimeModelLabel(runtime) {
    const names = Array.isArray(runtime.model_names) ? runtime.model_names : [];
    if (runtime.model_summary === "single_model" && names.length) return names[0];
    if (runtime.model_summary === "multiple_models") return t("model_multiple_models");
    if (runtime.model_summary === "api_configured") return t("model_api_configured");
    return t("model_deterministic");
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
      renderRuntime(null);
      byId("discovery-panel").hidden = true;
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
    renderRuntime(state.detail.runtime);
  }

  function discoverySummary() {
    return state.detail && state.detail.discovery_summary
      ? state.detail.discovery_summary
      : { enabled: false, issue: "not_run", providers: [], recommendations: [] };
  }

  function isZeroCandidateDiscovery() {
    const summary = discoverySummary();
    return summary.enabled && summary.issue === "zero_candidates";
  }

  function isZeroCandidateDiscoveryGate() {
    const run = state.detail && state.detail.run;
    return isZeroCandidateDiscovery()
      && run
      && run.status === "waiting"
      && run.current_stage === "awaiting_corpus_approval";
  }

  function renderDiscoverySummary() {
    const summary = discoverySummary();
    const panel = byId("discovery-panel");
    const shouldShow = Boolean(summary.enabled);
    panel.hidden = !shouldShow;
    if (!shouldShow) return;
    panel.classList.toggle("warning", summary.issue !== "ok");
    byId("discovery-summary-status").textContent = t(`discoveryIssue_${summary.issue || "not_run"}`);
    const run = state.detail && state.detail.run;
    const messageKey = summary.issue === "zero_candidates" && run && run.status === "completed"
      ? "discoveryMessage_zero_candidates_completed"
      : `discoveryMessage_${summary.issue || "not_run"}`;
    byId("discovery-summary-message").textContent = t(messageKey);

    const funnel = byId("discovery-funnel");
    funnel.replaceChildren();
    const funnelValues = summary.funnel || {};
    [
      ["funnelRaw", "raw_results"],
      ["funnelNormalized", "normalized"],
      ["funnelDeduplicated", "deduplicated"],
      ["funnelScreened", "screened"],
      ["funnelNew", "new_candidates"]
    ].forEach(([labelKey, valueKey]) => {
      const item = document.createElement("div");
      const label = document.createElement("dt");
      const value = document.createElement("dd");
      label.textContent = t(labelKey);
      value.textContent = String(Number(funnelValues[valueKey] || 0));
      item.append(label, value);
      funnel.append(item);
    });

    const providers = byId("discovery-provider-list");
    providers.replaceChildren();
    (summary.providers || []).forEach((provider) => {
      const item = document.createElement("div");
      item.className = "discovery-provider";
      const title = document.createElement("strong");
      title.textContent = provider.provider || t("unknown");
      const stats = document.createElement("span");
      stats.textContent = t("providerSummary", {
        provider: provider.provider || t("unknown"),
        queries: provider.queries || 0,
        results: provider.result_count || 0,
        failures: provider.failures || 0
      });
      item.append(title, stats);
      const categories = Array.isArray(provider.error_categories) ? provider.error_categories : [];
      if (categories.length) {
        const categoryLine = document.createElement("span");
        categoryLine.textContent = t("providerErrors", {
          errors: categories.map((category) => t(`providerErrorLabel_${category}`)).join(", ")
        });
        item.append(categoryLine);
      }
      if (provider.last_error_category) {
        const error = document.createElement("span");
        error.textContent = t(`providerError_${provider.last_error_category}`);
        item.append(error);
      }
      providers.append(item);
    });

    const attempts = byId("discovery-attempts");
    attempts.replaceChildren();
    const attemptHistory = state.detail && Array.isArray(state.detail.discovery_attempts)
      ? state.detail.discovery_attempts
      : [];
    if (attemptHistory.length) {
      const heading = document.createElement("strong");
      heading.textContent = t("discoveryAttempts");
      attempts.append(heading);
      attemptHistory.slice().reverse().slice(0, 5).forEach((attempt, index) => {
        const line = document.createElement("span");
        line.textContent = t("attemptSummary", {
          number: attemptHistory.length - index,
          status: t(attempt.status || "unknown"),
          providers: (attempt.providers || []).join(", ") || t("unknown")
        });
        attempts.append(line);
      });
    }

    const recommendations = byId("discovery-recommendations");
    recommendations.replaceChildren();
    (summary.recommendations || []).forEach((key) => {
      const item = document.createElement("li");
      item.textContent = t(`recommendation_${key}`);
      recommendations.append(item);
    });
    recommendations.hidden = recommendations.childElementCount === 0;
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

  function evidenceClaims() {
    return state.detail && state.detail.evidence && Array.isArray(state.detail.evidence.claims)
      ? state.detail.evidence.claims : [];
  }

  function selectedClaim() {
    return evidenceClaims().find((claim) => claim.claim_id === state.selectedClaimId) || null;
  }

  function renderEvidence() {
    const evidence = state.detail && state.detail.evidence;
    const panel = byId("evidence-panel");
    panel.hidden = !evidence || !evidence.enabled;
    if (panel.hidden) return;
    byId("evidence-summary").textContent = t("evidenceSummary", {
      documents: Number(evidence.document_count || 0),
      claims: Number(evidence.claim_count || 0),
      blocking: Number(evidence.blocking_claim_count || 0)
    });
    const metrics = byId("evidence-metrics");
    metrics.textContent = `${Number(evidence.parsed_document_count || 0)}/${Number(evidence.document_count || 0)}`;
    const body = byId("evidence-body");
    body.replaceChildren();
    const claims = evidenceClaims();
    byId("evidence-empty").hidden = claims.length !== 0;
    claims.forEach((claim) => {
      const results = Array.isArray(claim.verifications) ? claim.verifications : [];
      const primary = results.find((item) => item.blocking) || results[0] || {};
      const row = document.createElement("tr");
      row.className = "candidate-row evidence-row";
      row.tabIndex = 0;
      row.classList.toggle("selected", claim.claim_id === state.selectedClaimId);
      row.classList.toggle("blocking", Boolean(claim.blocking));
      row.append(
        labeledCell(claim.text, "claim"),
        labeledCell(primary.citation_key || (claim.citation_keys || []).join(", ") || "—", "citation"),
        labeledCell(
          primary.status
            ? t(`verification_${primary.status}`)
            : String(claim.claim_type || "—").replaceAll("_", " "),
          "status"
        ),
        labeledCell((primary.evidence_pages || []).join(", ") || "—", "pages")
      );
      const select = () => {
        state.selectedClaimId = claim.claim_id;
        state.selectedCandidateId = null;
        renderEvidence();
        renderCandidateDetail();
      };
      row.addEventListener("click", select);
      row.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          select();
        }
      });
      body.append(row);
    });
  }

  function hasDiscoveryActivity() {
    const summary = discoverySummary();
    if (summary.enabled) return true;
    const events = state.detail ? state.detail.events || [] : [];
    return events.some((event) => (
      event.stage === "discovering"
      || event.event_type === "query_started"
      || event.event_type === "query_completed"
      || event.event_type === "provider_failed"
    ));
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
    const showDiscoveryEmpty = candidates.length === 0
      && counts.all === 0
      && ["zero_candidates", "provider_failure"].includes(discoverySummary().issue);
    byId("candidates-empty").hidden = candidates.length !== 0 || showDiscoveryEmpty;
    byId("discovery-empty").hidden = !showDiscoveryEmpty;
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
      state.selectedClaimId = null;
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
    const claim = selectedClaim();
    const run = state.detail && state.detail.run;
    const approvalGateOpen = Boolean(
      run
      && run.status === "waiting"
      && run.current_stage === "awaiting_corpus_approval"
    );
    byId("candidate-empty").hidden = Boolean(candidate || claim);
    byId("candidate-content").hidden = !candidate || Boolean(claim);
    byId("evidence-detail").hidden = !claim;
    byId("approval-form").querySelectorAll("input, textarea, button").forEach((control) => {
      control.disabled = state.pending
        || !candidate
        || candidate.status !== "pending"
        || !approvalGateOpen;
    });
    if (claim) {
      renderClaimDetail(claim, run);
      return;
    }
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

  function renderClaimDetail(claim, run) {
    byId("evidence-claim-text").textContent = claim.text;
    byId("evidence-claim-meta").textContent = `${claim.section} · ${String(claim.claim_type).replaceAll("_", " ")}`;
    const container = byId("evidence-results");
    container.replaceChildren();
    const results = Array.isArray(claim.verifications) ? claim.verifications : [];
    results.forEach((result) => {
      const section = document.createElement("section");
      section.className = `evidence-result ${result.blocking ? "blocking" : "supported"}`;
      const heading = document.createElement("h3");
      heading.textContent = `${result.citation_key || t("noCitation")} · ${t(`verification_${result.status}`)}`;
      const reason = document.createElement("p");
      reason.textContent = result.reason;
      section.append(heading, reason);
      (result.evidence || []).forEach((passage) => {
        const quote = document.createElement("blockquote");
        quote.textContent = passage.text;
        const pages = document.createElement("small");
        pages.textContent = `${t("pages")} ${passage.page_start}${passage.page_end !== passage.page_start ? `–${passage.page_end}` : ""}`;
        section.append(quote, pages);
      });
      container.append(section);
    });
    if (
      Array.isArray(claim.decision_history)
      && claim.decision_history.length
      && !claim.decision
    ) {
      const note = document.createElement("p");
      note.className = "evidence-history-note";
      note.textContent = t("evidenceDecisionSuperseded");
      container.append(note);
    }
    const gateOpen = Boolean(run && run.status === "waiting" && run.current_stage === "awaiting_evidence_review");
    const decisionForm = byId("evidence-decision-form");
    decisionForm.hidden = !claim.blocking || !gateOpen || Boolean(claim.decision);
    decisionForm.querySelectorAll("textarea, button").forEach((control) => {
      control.disabled = state.pending || decisionForm.hidden;
    });
    const canAcceptRisk = results.filter((result) => result.blocking).every(
      (result) => result.status === "full_text_unavailable"
    );
    byId("accept-risk-button").hidden = !canAcceptRisk;
    const unavailable = results.find((result) => result.status === "full_text_unavailable" && result.citation_key);
    const importForm = byId("pdf-import-form");
    importForm.hidden = !gateOpen || !unavailable;
    importForm.dataset.citationKey = unavailable ? unavailable.citation_key : "";
    importForm.querySelectorAll("input, button").forEach((control) => {
      control.disabled = state.pending || importForm.hidden;
    });
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
    const mutationPending = state.pending || state.deletingRun;
    byId("close-discovery-button").textContent = isZeroCandidateDiscoveryGate()
      ? t("continueSeedCorpus")
      : t("closeDiscovery");
    byId("events-button").disabled = !hasRun || mutationPending;
    const hasSurvey = Boolean(state.detail && state.detail.outputs && state.detail.outputs.survey_available);
    byId("preview-run-button").disabled = !hasSurvey || mutationPending;
    byId("download-survey-button").disabled = !hasSurvey || mutationPending;
    byId("export-run-button").disabled = !hasRun || mutationPending;
    byId("cancel-run-button").disabled = !hasRun || mutationPending || terminalRunStatuses.has(run && run.status);
    byId("delete-run-button").disabled =
      !hasRun || mutationPending || !deletableRunStatuses.has(run && run.status);
    byId("resume-run-button").disabled = !hasRun || mutationPending || ["active", "completed", "cancelled"].includes(run && run.status);
    const unresolvedEvidence = hasRun
      && run.current_stage === "awaiting_evidence_review"
      && evidenceClaims().some((claim) => claim.blocking && !claim.decision);
    if (unresolvedEvidence) byId("resume-run-button").disabled = true;
    byId("close-discovery-button").disabled = !hasRun || mutationPending || run.current_stage !== "awaiting_corpus_approval";
    const canRetryDiscovery = hasRun && (
      (run.status === "waiting" && run.current_stage === "awaiting_corpus_approval")
      || (run.status === "retry_wait" && run.current_stage === "discovering")
    );
    byId("retry-discovery-button").disabled = mutationPending || !canRetryDiscovery;
    byId("new-run-button").disabled = mutationPending;
    document.querySelectorAll(".run-button").forEach((link) => {
      const disabled = state.pending || state.deletingRun;
      link.setAttribute("aria-disabled", String(disabled));
      link.classList.toggle("disabled", disabled);
    });
    document.querySelectorAll("[data-filter]").forEach((button) => {
      button.disabled = !hasRun || mutationPending;
    });
  }

  async function selectRun(runId) {
    if (runId === state.selectedRunId) return;
    state.manualSelectionVersion += 1;
    const generation = beginRunSelection(runId);
    await loadRunDetail(runId, generation);
  }

  function matchingStartRun(startJob) {
    if (!startJob) return null;
    return state.runs.find((run) => {
      if (run.run_id === startJob.resultRunId) return true;
      if (run.topic !== startJob.topic) return false;
      const createdAt = new Date(run.created_at).getTime();
      return Number.isFinite(createdAt)
        && createdAt >= startJob.submittedAtMs - 5000;
    }) || null;
  }

  function canAutoSelectStartJob(startJob) {
    return Boolean(startJob)
      && !startJob.autoSelected
      && !state.selectedRunId
      && state.manualSelectionVersion === startJob.selectionVersion;
  }

  async function refreshStartJobRuns(jobId) {
    const startJob = state.startJobs.get(jobId);
    await loadRuns({ preserveSelection: true, force: true });
    if (!canAutoSelectStartJob(startJob)) return;
    const run = matchingStartRun(startJob);
    if (!run) return;
    startJob.autoSelected = true;
    if (run.run_id === state.selectedRunId) return;
    const generation = beginRunSelection(run.run_id);
    await loadRunDetail(run.run_id, generation);
  }

  async function withPending(operation) {
    if (state.pending) return;
    state.pending = true;
    updateActions();
    renderEvidence();
    renderCandidateDetail();
    showFeedback("");
    try {
      await operation();
    } catch (error) {
      showFeedback(errorMessage(error), true);
    } finally {
      state.pending = false;
      updateActions();
      renderEvidence();
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

  async function decideEvidence(action) {
    const claim = selectedClaim();
    const runId = state.selectedRunId;
    if (!claim || !runId) return;
    const reason = byId("evidence-decision-reason").value.trim();
    if (!reason) {
      showFeedback(t("reasonRequired"), true);
      byId("evidence-decision-reason").focus();
      return;
    }
    await withPending(async () => {
      const payload = await api(
        `/api/runs/${encodeURIComponent(runId)}/evidence-decision`,
        { method: "POST", body: { claim_id: claim.claim_id, action, reason } }
      );
      showCommand(payload);
      showFeedback(t("evidenceDecisionSaved"));
      byId("evidence-decision-reason").value = "";
      await refreshRunDetail(runId);
    });
  }

  async function importEvidencePdf(event) {
    event.preventDefault();
    const runId = state.selectedRunId;
    const form = byId("pdf-import-form");
    const citationKey = form.dataset.citationKey;
    const pdfPath = byId("pdf-import-path").value.trim();
    if (!runId || !citationKey || !pdfPath) return;
    await withPending(async () => {
      const payload = await api(
        `/api/runs/${encodeURIComponent(runId)}/import-pdf`,
        { method: "POST", body: { citation_key: citationKey, pdf_path: pdfPath } }
      );
      showCommand(payload);
      showFeedback(t("pdfImported"));
      byId("pdf-import-path").value = "";
      await refreshRunDetail(runId);
    });
  }

  async function exportRun() {
    const runId = state.selectedRunId;
    if (!runId) return;
    await withPending(async () => {
      const payload = await api(
        `/api/runs/${encodeURIComponent(runId)}/export`,
        { method: "POST", body: { include_pdfs: true } }
      );
      showCommand(payload);
      showFeedback(`${t("exportReady")} ${payload.output_path || ""}`);
      downloadRunArtifact("audit");
    });
  }

  function downloadRunArtifact(kind) {
    const runId = state.selectedRunId;
    if (!runId || !["survey", "audit"].includes(kind)) return;
    const link = document.createElement("a");
    link.href = `/api/runs/${encodeURIComponent(runId)}/download/${kind}`;
    link.hidden = true;
    document.body.append(link);
    link.click();
    link.remove();
  }

  function previewSurvey() {
    const outputs = state.detail && state.detail.outputs;
    if (!outputs || !outputs.survey_available) return;
    byId("survey-preview").textContent = outputs.survey_markdown || "";
    openDialog("survey-preview-dialog");
  }

  async function startRun(event) {
    event.preventDefault();
    const discover = byId("new-run-discover").checked;
    const providers = selectedProviders("providers");
    if (discover && providers.length === 0) {
      showFeedback(t("providerRequired"), true);
      return;
    }
    const queries = queryLines("new-run-queries");
    if (queries.length > 8 || queries.some((query) => query.length > 300)) {
      showFeedback(t("queryRequired"), true);
      return;
    }
    const body = {
      topic: byId("new-run-topic").value,
      corpus_path: byId("new-run-corpus").value,
      discover,
      full_text: byId("new-run-full-text").checked,
      providers,
      max_results: Number(byId("new-run-max-results").value),
      queries
    };
    await withPending(async () => {
      const payload = await api("/api/runs", { method: "POST", body });
      showCommand(payload);
      state.jobIds.add(payload.job_id);
      state.startJobs.set(payload.job_id, {
        topic: body.topic,
        submittedAtMs: Date.now(),
        selectionVersion: state.manualSelectionVersion,
        autoSelected: false,
        resultRunId: null
      });
      showFeedback(t("jobQueued"));
      closeDialog("new-run-dialog");
      await refreshStartJobRuns(payload.job_id);
      scheduleJobPoll();
    });
  }

  function selectedProviders(name) {
    return Array.from(document.querySelectorAll(`input[name="${name}"]:checked`))
      .map((input) => input.value);
  }

  function queryLines(id) {
    const queries = byId(id).value
      .split(/\r?\n/)
      .map((query) => query.trim().replace(/\s+/g, " "))
      .filter(Boolean);
    return Array.from(new Set(queries));
  }

  function openRetryDiscoveryDialog() {
    const summary = discoverySummary();
    const latest = summary.latest_attempt || {};
    const preferred = new Set(
      (latest.failed_providers && latest.failed_providers.length)
        ? latest.failed_providers
        : (latest.providers || [])
    );
    document.querySelectorAll('input[name="retry-providers"]').forEach((input) => {
      input.checked = preferred.size ? preferred.has(input.value) : input.checked;
    });
    byId("retry-max-results").value = String(latest.max_results || 10);
    const queries = (latest.query_texts && latest.query_texts.length)
      ? latest.query_texts
      : (summary.suggested_queries || []);
    byId("retry-queries").value = queries.join("\n");
    openDialog("retry-discovery-dialog");
  }

  async function retryDiscovery(event) {
    event.preventDefault();
    const providers = selectedProviders("retry-providers");
    const queries = queryLines("retry-queries");
    if (!providers.length) {
      showFeedback(t("providerRequired"), true);
      return;
    }
    if (queries.length > 8 || queries.some((query) => query.length > 300)) {
      showFeedback(t("queryRequired"), true);
      return;
    }
    const runId = state.selectedRunId;
    if (!runId) return;
    await withPending(async () => {
      const payload = await api(
        `/api/runs/${encodeURIComponent(runId)}${apiPaths.retryDiscovery}`,
        {
          method: "POST",
          body: {
            providers,
            max_results: Number(byId("retry-max-results").value),
            queries
          }
        }
      );
      showCommand(payload);
      state.jobIds.add(payload.job_id);
      showFeedback(t("discoveryRetryQueued"));
      closeDialog("retry-discovery-dialog");
      scheduleJobPoll();
      await refreshRunDetail(runId);
    });
  }

  function renderDeleteRunDialog() {
    const target = state.deleteTarget;
    if (!target) return;
    byId("delete-run-topic").textContent = target.topic;
    byId("delete-run-id").textContent = target.run_id;
    byId("delete-run-status").textContent = t(target.status || "unknown");
    byId("confirm-delete-run-button").disabled = state.deletingRun;
  }

  function openDeleteRunDialog() {
    const run = state.detail && state.detail.run;
    if (!run || state.pending || state.deletingRun || !deletableRunStatuses.has(run.status)) return;
    state.deleteTarget = {
      run_id: run.run_id,
      topic: run.topic,
      status: run.status
    };
    renderDeleteRunDialog();
    openDialog("delete-run-dialog");
    byId("delete-run-close-button").focus();
  }

  function dismissDeleteRunDialog({ restoreFocus = true } = {}) {
    state.suppressDeleteFocusRestore = !restoreFocus;
    closeDialog("delete-run-dialog");
    state.deleteTarget = null;
    if (restoreFocus) byId("delete-run-button").focus();
  }

  function focusPostDeleteTarget() {
    const deleteButton = byId("delete-run-button");
    if (!deleteButton.disabled) {
      deleteButton.focus();
      return;
    }
    const selectedRunButton = document.querySelector('.run-button.selected:not([aria-disabled="true"])');
    if (selectedRunButton) {
      selectedRunButton.focus();
      return;
    }
    if (state.runs.length === 0) {
      byId("empty-new-run-button").focus();
      return;
    }
    byId("new-run-button").focus();
  }

  function isDeleteConflict(error) {
    return error instanceof APIError
      && [
        "run_not_deletable",
        "run_deletion_conflict",
        "run_busy",
        "run_deletion_busy",
        "not_found"
      ].includes(error.code);
  }

  async function deleteRun() {
    const target = state.deleteTarget;
    if (!target || state.deletingRun) return;
    const runId = target.run_id;
    state.deletingRun = true;
    byId("confirm-delete-run-button").disabled = true;
    updateActions();
    let focusAfterFinalization = false;
    try {
      const payload = await api(`/api/runs/${encodeURIComponent(runId)}`, { method: "DELETE" });
      showCommand(payload);
      dismissDeleteRunDialog({ restoreFocus: false });
      beginRunSelection(null);
      await loadRuns({ preserveSelection: false, force: true });
      const feedbackKey = payload.cleanup_pending ? "deleteCleanupPending" : "runDeleted";
      showFeedback(t(feedbackKey), false, {
        persistent: true,
        warning: payload.cleanup_pending
      });
      focusAfterFinalization = true;
    } catch (error) {
      if (isDeleteConflict(error)) {
        dismissDeleteRunDialog({ restoreFocus: false });
        await loadRuns({ preserveSelection: true, force: true });
        focusAfterFinalization = true;
      }
      showFeedback(errorMessage(error), true);
    } finally {
      state.deletingRun = false;
      updateActions();
      renderDeleteRunDialog();
      if (focusAfterFinalization) focusPostDeleteTarget();
    }
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
        if (job.kind === "start" && ["queued", "running"].includes(job.status)) {
          if (!state.startJobs.has(jobId)) {
            state.startJobs.set(jobId, {
              topic: "",
              submittedAtMs: Date.now(),
              selectionVersion: state.manualSelectionVersion,
              autoSelected: true,
              resultRunId: null
            });
          }
          await refreshStartJobRuns(jobId);
        }
        if (job.status === "running") showFeedback(t("jobRunning"), false, { background: true });
        if (terminalJobStatuses.has(job.status)) {
          const startJob = state.startJobs.get(jobId);
          if (startJob && job.result && job.result.run_id) {
            startJob.resultRunId = job.result.run_id;
          }
          const maySelectResult = !startJob
            || (!state.selectedRunId && state.manualSelectionVersion === startJob.selectionVersion);
          state.jobIds.delete(jobId);
          state.startJobs.delete(jobId);
          completed = true;
          showFeedback(
            job.status === "succeeded" ? t("jobSucceeded") : t("jobFailed"),
            job.status === "failed",
            { background: true }
          );
          if (maySelectResult && job.result && job.result.run_id && job.result.run_id !== state.selectedRunId) {
            beginRunSelection(job.result.run_id);
          }
        }
      }
      if (completed) await loadRuns();
    } catch (error) {
      showFeedback(errorMessage(error), true, { background: true });
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
    byId("preview-run-button").addEventListener("click", previewSurvey);
    byId("download-survey-button").addEventListener("click", () => downloadRunArtifact("survey"));
    byId("export-run-button").addEventListener("click", exportRun);
    byId("resume-run-button").addEventListener("click", () => mutateRun("resume", "jobQueued"));
    byId("retry-discovery-button").addEventListener("click", openRetryDiscoveryDialog);
    byId("cancel-run-button").addEventListener("click", () => mutateRun("cancel", "runCancelled"));
    byId("delete-run-button").addEventListener("click", openDeleteRunDialog);
    byId("delete-run-close-button").addEventListener("click", () => dismissDeleteRunDialog());
    byId("confirm-delete-run-button").addEventListener("click", deleteRun);
    byId("delete-run-dialog").addEventListener("close", () => {
      state.deleteTarget = null;
      if (!state.suppressDeleteFocusRestore) byId("delete-run-button").focus();
      state.suppressDeleteFocusRestore = false;
    });
    byId("close-discovery-button").addEventListener("click", () => mutateRun("close-discovery", "discoveryClosed"));
    byId("retry-load-button").addEventListener("click", () => loadRuns({ preserveSelection: false }));
    byId("new-run-form").addEventListener("submit", startRun);
    byId("retry-discovery-form").addEventListener("submit", retryDiscovery);
    byId("approval-form").addEventListener("submit", (event) => {
      event.preventDefault();
      decideCandidate("approve");
    });
    byId("evidence-decision-form").addEventListener("submit", (event) => {
      event.preventDefault();
      decideEvidence("require_revision");
    });
    byId("accept-risk-button").addEventListener("click", () => decideEvidence("accept_risk"));
    byId("pdf-import-form").addEventListener("submit", importEvidencePdf);
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
      byId("new-run-max-results").disabled = !event.target.checked;
      byId("new-run-queries").disabled = !event.target.checked;
    });
    window.addEventListener("pagehide", () => {
      state.stopped = true;
      clearTimeout(state.jobTimer);
      clearTimeout(state.runTimer);
    });
  }

  async function initialize() {
    byId("new-run-corpus").value = config.defaultCorpusPath || "";
    byId("database-path").textContent = config.databasePath || "";
    byId("artifact-root").textContent = config.artifactRoot || "";
    renderProviderOptions();
    bindEvents();
    applyLanguage(state.language);
    await loadRuns({ preserveSelection: true, fallbackToFirst: true });
    await recoverActiveJobs();
  }

  initialize();
})();
