const $ = (id) => document.getElementById(id);

const els = {
  summary: $("summary"), runQueue: $("runQueue"), visibleCount: $("visibleCount"),
  workerProgress: $("workerProgress"), workerProgressText: $("workerProgressText"), workerProgressCounts: $("workerProgressCounts"),
  workerProgressBar: $("workerProgressBar"), workerProgressSample: $("workerProgressSample"),
  jobDrawerToggle: $("jobDrawerToggle"), jobDrawerBadge: $("jobDrawerBadge"), jobDrawer: $("jobDrawer"),
  jobDrawerClose: $("jobDrawerClose"), drawerBackdrop: $("drawerBackdrop"), jobDrawerSummary: $("jobDrawerSummary"),
  jobFilterRow: $("jobFilterRow"), jobList: $("jobList"),
  labelFilter: $("labelFilter"), workflowFilter: $("workflowFilter"), searchInput: $("searchInput"), queue: $("queue"),
  sampleStage: $("sampleStage"), sampleTitle: $("sampleTitle"), sampleMeta: $("sampleMeta"), previous: $("previous"), next: $("next"),
  workflowGuide: $("workflowGuide"), guideCurrent: $("guideCurrent"), copyExportCommand: $("copyExportCommand"), exportCommand: $("exportCommand"),
  toggleQueuePanel: $("toggleQueuePanel"), toggleReviewPanel: $("toggleReviewPanel"), comparisonGrid: $("comparisonGrid"), maskComparisonGrid: $("maskComparisonGrid"),
  emptyState: $("emptyState"), anomalyView: $("anomalyView"), sourceCanvas: $("sourceCanvas"), candidateCanvas: $("candidateCanvas"),
  candidateCaption: $("candidateCaption"), candidateHint: $("candidateHint"), annotationLegend: $("annotationLegend"), qcText: $("qcText"),
  maskView: $("maskView"), maskSourceCanvas: $("maskSourceCanvas"), maskAnnotationLegend: $("maskAnnotationLegend"), editorCanvas: $("editorCanvas"),
  drawTool: $("drawTool"), eraseTool: $("eraseTool"), brushSize: $("brushSize"), brushText: $("brushText"),
  maskOpacity: $("maskOpacity"), opacityText: $("opacityText"), undo: $("undo"), redo: $("redo"), saveMask: $("saveMask"), maskSaveState: $("maskSaveState"),
  reviewTitle: $("reviewTitle"), currentStatus: $("currentStatus"), reasonList: $("reasonList"), comment: $("comment"),
  generationPlanCard: $("generationPlanCard"), generationPlanCount: $("generationPlanCount"), generationPlanBody: $("generationPlanBody"),
  roiSelectionSection: $("roiSelectionSection"), roiSelectionList: $("roiSelectionList"), roiSelectionHint: $("roiSelectionHint"),
  selectReviewableRois: $("selectReviewableRois"), clearRoiSelection: $("clearRoiSelection"),
  promptPreviewBox: $("promptPreviewBox"), promptPreviewSummary: $("promptPreviewSummary"), promptPreviewText: $("promptPreviewText"),
  approve: $("approve"), reject: $("reject"), hold: $("hold"), deleteSample: $("deleteSample"), toast: $("toast"),
  apiSettingsOpen: $("apiSettingsOpen"), apiSettingsModal: $("apiSettingsModal"), apiSettingsBackdrop: $("apiSettingsBackdrop"), apiSettingsClose: $("apiSettingsClose"),
  apiBaseUrl: $("apiBaseUrl"), apiKey: $("apiKey"), coreAdapter: $("coreAdapter"), coreModel: $("coreModel"), coreEndpoint: $("coreEndpoint"), coreQuality: $("coreQuality"), coreTimeout: $("coreTimeout"),
  coreTransportRetries: $("coreTransportRetries"), coreTransportJobRetries: $("coreTransportJobRetries"),
  intelEnabled: $("intelEnabled"), intelModel: $("intelModel"), intelEndpoint: $("intelEndpoint"), intelEffort: $("intelEffort"), intelOrchestrator: $("intelOrchestrator"), intelPlanner: $("intelPlanner"), parallelPlanning: $("parallelPlanning"), intelCritic: $("intelCritic"), intelCriticGate: $("intelCriticGate"), refCandidateCount: $("refCandidateCount"), approvedExampleCount: $("approvedExampleCount"), failedExampleCount: $("failedExampleCount"), intelTimeout: $("intelTimeout"), intelTransportRetries: $("intelTransportRetries"),
  generationReferenceCount: $("generationReferenceCount"), editMinPad: $("editMinPad"), editRatio: $("editRatio"), maxAttempts: $("maxAttempts"), autoRetries: $("autoRetries"), manualReviewAfterRetries: $("manualReviewAfterRetries"),
  agenticGeneration: $("agenticGeneration"), agentCandidateCount: $("agentCandidateCount"), agentFailureMemory: $("agentFailureMemory"), comparativeCritic: $("comparativeCritic"), multiRoiSourceMode: $("multiRoiSourceMode"),
  apiSettingsStatus: $("apiSettingsStatus"), probeCore: $("probeCore"), probeIntelligence: $("probeIntelligence"), saveApiSettings: $("saveApiSettings"),
};

const workflowNames = {
  pending_generation: "待生成", core_not_configured: "CORE未配置", qc_failed: "自动质检失败",
  anomaly_review: "异常图待审", regen_queued: "待重生成", mask_review: "Mask待审",
  normal_review: "正常样本待审", completed: "全部通过", hold: "暂缓", deleted: "已移除",
};

const reasonNames = {
  ANOMALY_TOO_SMALL: "异常面积太小", ANOMALY_TOO_WEAK: "异常不明显", WRONG_LABEL: "异常类型错误",
  WRONG_STRUCTURE: "局部结构不合理", PARTIAL_REMOVAL: "零件未完整移除", BACKGROUND_CHANGED: "背景或无关区域改变",
  COLOR_SHIFT: "灰度/RGB色偏", EDGE_ARTIFACT: "边缘或贴图感", ROI_MISALIGNED: "ROI位置/范围错误",
  OIL_TOO_SMALL: "漏油面积太小", OIL_LOOKS_LIKE_SHADOW: "油迹像阴影", MASK_TOO_COARSE: "Mask过粗",
  MASK_MISSING_AREA: "Mask漏标", MASK_EXTRA_AREA: "Mask过标", MASK_EDGE_INACCURATE: "Mask边缘不准", OTHER: "其他",
};

function readPreference(key, fallback) {
  try { return localStorage.getItem(key) ?? fallback; } catch (_) { return fallback; }
}
function writePreference(key, value) {
  try { localStorage.setItem(key, value); } catch (_) { /* storage can be unavailable */ }
}

const storedComparisonMode = readPreference("review.comparisonMode", "side");
const storedQueueCollapsed = readPreference("review.queueCollapsed", "");
const state = {
  items: [], filtered: [], currentId: null, anomalyReasons: [], maskReasons: [],
  candidate: null, tool: "draw", drawing: false, lastPoint: null, dirty: false,
  editRegionMasks: [],
  undo: [], redo: [], opacity: 0.48, renderToken: 0, worker: {}, jobFilter: "all", drawerOpen: false,
  selectedRois: new Set(), selectionGroupId: null,
  showBoxes: readPreference("review.showBoxes", "true") !== "false",
  showEditRegion: readPreference("review.showEditRegion", "true") !== "false",
  showMask: readPreference("review.showMask", "true") !== "false",
  comparisonMode: ["side", "source", "candidate"].includes(storedComparisonMode) ? storedComparisonMode : "side",
  queueCollapsed: storedQueueCollapsed === "" ? window.matchMedia("(max-width: 1440px)").matches : storedQueueCollapsed === "true",
  reviewCollapsed: readPreference("review.reviewCollapsed", "false") === "true",
  promptPreviewToken: 0, pollTimer: null, pollInFlight: false, workerItemsSignature: "", renderController: null,
};

const editorCtx = els.editorCanvas.getContext("2d", { willReadFrequently: true });
const maskCanvas = document.createElement("canvas");
const maskCtx = maskCanvas.getContext("2d", { willReadFrequently: true });
const overlayCanvas = document.createElement("canvas");
const overlayCtx = overlayCanvas.getContext("2d");

function currentItem() { return state.items.find((item) => item.id === state.currentId) || null; }
function showToast(message) {
  els.toast.textContent = message; els.toast.hidden = false;
  clearTimeout(showToast.timer); showToast.timer = setTimeout(() => { els.toast.hidden = true; }, 3400);
}
async function api(url, options = {}) {
  const response = await fetch(url, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `请求失败 ${response.status}`);
  return payload;
}
function loadImage(url, signal = null) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    let settled = false;
    const cleanup = () => { if (signal) signal.removeEventListener("abort", abort); };
    const finish = (callback, value) => { if (settled) return; settled = true; cleanup(); callback(value); };
    const abort = () => {
      image.onload = null; image.onerror = null; image.src = "";
      const error = new Error("图片加载已取消"); error.name = "AbortError"; finish(reject, error);
    };
    if (signal?.aborted) { abort(); return; }
    if (signal) signal.addEventListener("abort", abort, { once: true });
    image.onload = () => finish(resolve, image);
    image.onerror = () => finish(reject, new Error(`无法加载图片：${url}`));
    image.src = url;
  });
}
function beginRenderCycle() {
  if (state.renderController) state.renderController.abort();
  state.renderController = new AbortController();
  return { token: ++state.renderToken, signal: state.renderController.signal };
}
function reportRenderError(error) { if (error?.name !== "AbortError") showToast(error.message); }
function workflowName(value) { return workflowNames[value] || value; }

const jobStatusNames = { waiting: "等待生成", planning: "并行预规划中", running: "代理生成候选中", retrying: "质检未过，重新规划", transport_retrying: "API传输重试（不计版本）", succeeded: "生成成功", needs_review: "重试耗尽，转人工审核", failed: "生成失败" };
const jobStageNames = {
  waiting: "等待进入生成器", preparing: "准备源图、参考与失败记忆", planning: "视觉代理分析并规划",
  batch_planning: "视觉代理正在批量规划同图多个ROI", batch_plan_ready: "同图批量规划已完成",
  prefetch_planning: "与当前CORE并行：预规划下一组", prefetch_ready: "下一组视觉规划已就绪", prefetch_failed: "预规划失败，将前台回退",
  mask_ready: "语义Mask与硬保护区已生成", core_request: "CORE正在生成候选", core_received: "CORE已返回，正在局部合成",
  candidate_critic: "视觉LLM正在质检候选", candidate_complete: "当前候选质检完成", comparing: "横向比较全部候选",
  saving: "保存最佳候选与审计", retry_wait: "准备按失败诊断重试", transport_retry: "API传输失败，正在重连",
  complete: "本轮完成", failed: "本轮失败",
};
const qcFailureNames = {
  LLM_SEMANTIC_QC_FAILED: "视觉LLM语义质检未通过",
  LLM_CRITIC_ERROR: "视觉LLM质检调用失败",
  EMPTY_CHANGE: "未检测到有效异常变化", CHANGE_TOO_LARGE: "变化面积过大", CHANGE_TOUCHES_BORDER: "变化触碰图片边界",
  SIZE_MISMATCH: "生成尺寸或比例不一致", CORE_NOT_CONFIGURED: "CORE未正确配置", CORE_ERROR: "CORE/API调用失败",
  PIPELINE_ERROR: "生成流程异常",
  CORE_TRANSPORT_ERROR: "API传输失败，未计入图片版本",
};

function openJobDrawer() {
  state.drawerOpen = true; els.jobDrawer.classList.add("open"); els.jobDrawer.setAttribute("aria-hidden", "false"); els.drawerBackdrop.hidden = false;
}
function closeJobDrawer() {
  state.drawerOpen = false; els.jobDrawer.classList.remove("open"); els.jobDrawer.setAttribute("aria-hidden", "true"); els.drawerBackdrop.hidden = true;
}

function combinedJobRows(worker = {}) {
  const batch = new Map((worker.jobs || []).map((job) => [job.id, job]));
  const tasks = state.items.flatMap((item) => item.children?.length ? item.children.map((child) => ({ ...child, relative_json: `${item.relative_json} · ${child.labels.map((row) => row.code).join("/")}` })) : [item]);
  return tasks.map((item) => {
    const job = batch.get(item.id);
    if (job) return { ...job, name: item.relative_json, labels: item.labels, batch: true };
    return {
      id: item.id, name: item.relative_json, labels: item.labels, status: item.workflow,
      workflow: item.workflow, attempt: item.active_attempt, error: item.qc?.error || "",
      failure_codes: item.qc?.failures || [], batch: false,
    };
  });
}

function failureText(row) {
  const codes = (row.failure_codes || []).map((code) => qcFailureNames[code] || code);
  return [codes.join("；"), row.error || ""].filter(Boolean).filter((value, index, values) => values.indexOf(value) === index).join("；");
}

function jobGroup(row) {
  if (row.batch && ["planning", "running", "retrying", "transport_retrying"].includes(row.status)) return "running";
  if (row.batch && row.status === "waiting") return "waiting";
  if (row.batch && ["succeeded", "needs_review", "failed"].includes(row.status)) return "finished";
  return "other";
}

function renderJobDrawer(worker = state.worker) {
  state.worker = worker || {};
  const rows = combinedJobRows(state.worker);
  const running = rows.filter((row) => jobGroup(row) === "running").length;
  const waiting = rows.filter((row) => jobGroup(row) === "waiting").length;
  const succeeded = rows.filter((row) => row.batch && row.status === "succeeded").length;
  const failed = rows.filter((row) => row.batch && row.status === "failed").length;
  els.jobDrawerBadge.textContent = String(running || waiting || rows.filter((row) => row.batch).length || 0);
  els.jobDrawerSummary.innerHTML = [
    [running, "正在生成"], [waiting, "等待"], [succeeded, "本轮成功"], [failed, "本轮失败"],
  ].map(([count, label]) => `<div class="job-metric"><b>${count}</b>${label}</div>`).join("");
  const groups = [
    ["running", "正在生成"], ["waiting", "等待生成"], ["finished", "本轮已完成"], ["other", "其他样本状态"],
  ];
  const visibleGroups = state.jobFilter === "all" ? groups : groups.filter(([key]) => {
    if (state.jobFilter === "active") return key === "running" || key === "waiting";
    return key === state.jobFilter;
  });
  const html = [];
  for (const [groupKey, title] of visibleGroups) {
    const members = rows.filter((row) => jobGroup(row) === groupKey);
    if (!members.length) continue;
    html.push(`<div class="job-group-title"><span>${title}</span><span>${members.length}</span></div>`);
    for (const row of members) {
      const labelText = (row.labels || []).map((label) => typeof label === "string" ? label : `${label.code} · ${label.name}`).join(" / ");
      const statusText = row.batch ? (jobStatusNames[row.status] || workflowName(row.workflow)) : workflowName(row.workflow);
      const failure = failureText(row);
      const retryText = row.retry_count ? ` · 已重试${row.retry_count}次` : "";
      const candidateText = Number.isInteger(row.candidate_index) ? ` · 候选${row.candidate_index + 1}/${row.candidate_count || 1}` : "";
      const phaseText = row.stage ? `${jobStageNames[row.stage] || row.stage}${candidateText}` : "";
      const agentText = row.agentic ? `<br>代理轮次：${row.candidate_count || 1}个CORE候选＋逐候选质检＋横向择优${phaseText ? `<br>当前阶段：${phaseText}` : ""}` : "";
      const visibleStatus = ["running", "retrying", "transport_retrying"].includes(row.status) && phaseText ? phaseText : statusText;
      html.push(`<div class="job-card${["running", "retrying", "transport_retrying"].includes(row.status) ? " current" : ""}"><i class="job-state-dot ${row.status}"></i><div><strong>${row.name || row.path}</strong><small>${labelText || "无标签"}${agentText}${failure ? `<br>失败原因：${failure}` : ""}</small></div><span class="job-card-status">${visibleStatus}${row.attempt ? ` · v${row.attempt}` : ""}${retryText}</span></div>`);
    }
  }
  els.jobList.innerHTML = html.join("") || '<div class="job-empty">当前筛选下没有样本</div>';
}

function renderGuide(item) {
  const workflow = item?.workflow || "";
  let active = "generate", message = "从左侧选择样本开始", done = [];
  if (!item) active = "generate";
  else if (["pending_generation", "regen_queued", "qc_failed", "core_not_configured"].includes(workflow)) {
    active = "generate"; message = workflow === "pending_generation" ? "下一步：生成当前异常" : "下一步：按审核意见重新生成";
  } else if (["anomaly_review", "normal_review"].includes(workflow)) {
    active = "anomaly"; done = ["generate"]; message = workflow === "normal_review" ? "下一步：审核正常样本" : "下一步：对比左右图并审核异常";
  } else if (workflow === "mask_review") {
    active = "mask"; done = ["generate", "anomaly"]; message = "下一步：精修、保存并审核 Mask";
  } else if (workflow === "completed") {
    const allCompleted = state.items.length > 0 && state.items.every((row) => row.workflow === "completed");
    active = allCompleted ? "export" : "complete";
    done = allCompleted ? ["generate", "anomaly", "mask", "complete"] : ["generate", "anomaly", "mask"];
    message = allCompleted ? "全部样本已通过，可以导出最终数据集" : "当前样本已完成，请继续下一条";
  } else if (workflow === "hold") {
    active = "anomaly"; done = ["generate"]; message = "当前样本已暂缓，请修正问题或稍后处理";
  }
  els.guideCurrent.textContent = message;
  for (const step of document.querySelectorAll("[data-guide-step]")) {
    const name = step.dataset.guideStep;
    step.classList.toggle("active", name === active);
    step.classList.toggle("done", done.includes(name));
  }
}

function isGrouped(item) { return Boolean(item?.children?.length); }
function childrenFor(item) { return isGrouped(item) ? item.children : item ? [item] : []; }
function childStage(child) { return child.stage === "mask" ? "mask" : child.stage === "normal" ? "normal" : "anomaly"; }
function isGenerationQueuedChild(child) {
  return ["pending_generation", "regen_queued", "qc_failed", "core_not_configured"].includes(child.workflow);
}
function isReviewableChild(child) {
  if (!Number(child.active_attempt || 0)) return false;
  if (isGenerationQueuedChild(child)) return false;
  return true;
}
function defaultSelection(item) {
  const children = childrenFor(item);
  let preferred = children.filter(isGenerationQueuedChild);
  if (!preferred.length) preferred = children.filter((child) => child.workflow === "anomaly_review");
  if (!preferred.length) preferred = children.filter((child) => child.workflow === "mask_review");
  if (!preferred.length && children.every((child) => child.workflow === "completed")) preferred = children;
  if (!preferred.length) preferred = children.filter((child) => child.workflow === "hold");
  if (!preferred.length && children.length) preferred = [children[0]];
  return new Set(preferred.map((child) => child.id));
}
function ensureSelection(item) {
  if (!isGrouped(item)) return;
  const valid = new Set(item.children.map((child) => child.id));
  if (state.selectionGroupId !== item.id) {
    state.selectionGroupId = item.id;
    state.selectedRois = defaultSelection(item);
  } else {
    state.selectedRois = new Set([...state.selectedRois].filter((id) => valid.has(id)));
  }
}
function selectedChildren(item) {
  return childrenFor(item).filter((child) => !isGrouped(item) || state.selectedRois.has(child.id));
}
function allTaskChildren() {
  const unique = new Map();
  for (const item of state.items) for (const child of childrenFor(item)) unique.set(child.id, child);
  return [...unique.values()];
}
function queuedChildren(item = null) {
  return (item ? childrenFor(item) : allTaskChildren()).filter(isGenerationQueuedChild);
}
function workerJobFor(childId) {
  return (state.worker?.jobs || []).find((job) => job.id === childId) || null;
}
function childRuntimeState(child, index = 0) {
  const job = workerJobFor(child.id);
  if (!job) return { status: child.workflow, text: workflowName(child.workflow), batch: false, active: false };
  const active = ["running", "retrying", "transport_retrying"].includes(job.status);
  const candidate = Number.isInteger(job.candidate_index) ? ` · 候选${job.candidate_index + 1}/${job.candidate_count || 1}` : "";
  const shortStatus = {
    waiting: "本轮等待", succeeded: "本轮生成完成", needs_review: "重试结束，转人工审核", failed: "本轮失败",
  };
  const text = active
    ? `${jobStageNames[job.stage] || jobStageNames[job.status] || jobStatusNames[job.status] || job.status}${candidate}`
    : (shortStatus[job.status] || jobStatusNames[job.status] || workflowName(job.workflow));
  return {
    status: job.status, text, batch: true, active, attempt: Number(job.attempt || child.active_attempt || 0),
    retryCount: Number(job.retry_count || 0), index,
  };
}
function roiShortName(child, index = 0) {
  const labels = (child.labels || []).map((row) => row.code).join("/") || "未标注";
  const shapeIndexes = (child.annotations || []).filter((row) => row.active).map((row) => Number(row.index) + 1);
  return `ROI ${shapeIndexes.length ? shapeIndexes.join("+") : index + 1} · ${labels}`;
}
function renderGenerationPlan(item = currentItem()) {
  const globalQueued = queuedChildren();
  els.generationPlanCount.textContent = `全局 ${globalQueued.length} 个 ROI`;
  if (!state.worker?.running) els.runQueue.textContent = `生成已排队 ROI（${globalQueued.length}）`;
  if (!item) {
    els.generationPlanBody.textContent = globalQueued.length ? `当前已有 ${globalQueued.length} 个 ROI 等待生成。` : "当前没有待生成 ROI。";
    return;
  }
  const children = childrenFor(item);
  const queued = children.filter(isGenerationQueuedChild);
  const kept = children.filter((child) => !isGenerationQueuedChild(child));
  const queuedHtml = queued.length
    ? queued.map((child, index) => {
      const runtime = childRuntimeState(child, index);
      const action = runtime.batch && runtime.status !== "waiting" ? runtime.text : "将生成";
      return `<span class="plan-roi queued">${action}｜${roiShortName(child, index)}｜${workflowName(child.workflow)}</span>`;
    }).join("")
    : '<span class="plan-roi empty">当前图没有 ROI 进入下一轮生成</span>';
  const keptHtml = kept.length
    ? kept.map((child, index) => `<span class="plan-roi kept">保留现有版本｜${roiShortName(child, index)}｜${workflowName(child.workflow)}</span>`).join("")
    : "";
  els.generationPlanBody.innerHTML = queuedHtml + keptHtml;
}
function selectionBucket(child) { return isGenerationQueuedChild(child) ? "generation" : childStage(child); }
function updateRoiSelection(item, childId, checked) {
  if (!isGrouped(item)) return false;
  if (!checked) { state.selectedRois.delete(childId); return false; }
  const target = item.children.find((child) => child.id === childId); if (!target) return false;
  const bucket = selectionBucket(target);
  const switchedBucket = selectedChildren(item).some((child) => selectionBucket(child) !== bucket);
  if (switchedBucket) state.selectedRois.clear();
  state.selectedRois.add(childId);
  return switchedBucket;
}
function selectedStage(item) {
  const stages = new Set(selectedChildren(item).map(childStage));
  return stages.size === 1 ? [...stages][0] : stages.size ? "mixed" : "none";
}
function commonReviewValues(item, stage) {
  const children = selectedChildren(item);
  if (!children.length) return { reasons: [], comment: "" };
  const reasonKey = stage === "mask" ? "mask_reason_codes" : "anomaly_reason_codes";
  const commentKey = stage === "mask" ? "mask_comment" : "anomaly_comment";
  const reasonTokens = children.map((child) => JSON.stringify([...(child[reasonKey] || [])].sort()));
  const comments = children.map((child) => child[commentKey] || "");
  return {
    reasons: reasonTokens.every((value) => value === reasonTokens[0]) ? JSON.parse(reasonTokens[0]) : [],
    comment: comments.every((value) => value === comments[0]) ? comments[0] : "",
  };
}
function renderRoiSelection(item) {
  els.roiSelectionSection.hidden = !isGrouped(item);
  if (!isGrouped(item)) return;
  els.roiSelectionList.innerHTML = item.children.map((child, index) => {
    const label = child.labels.map((row) => `${row.code} · ${row.name}`).join(" / ");
    const queued = isGenerationQueuedChild(child);
    const runtime = childRuntimeState(child, index);
    const runtimeText = runtime.batch ? runtime.text : (queued ? "已排队，下轮生成" : `不生成，保留 v${child.active_attempt}`);
    return `<label class="roi-choice${runtime.active ? " processing" : ""}"><input type="checkbox" data-roi-id="${child.id}" ${state.selectedRois.has(child.id) ? "checked" : ""}><span><strong>标注目标 ${index + 1}　${label}</strong><small>勾选 = 右侧意见与 Prompt 作用于此 ROI；不会改变排队状态</small></span><span class="roi-choice-status ${queued ? "queued" : "kept"}">${runtimeText}<br>${workflowName(child.workflow)}</span></label>`;
  }).join("");
  const selected = selectedChildren(item);
  const stages = new Set(selected.map(childStage));
  const generationInput = selected.length > 0 && selected.every(isGenerationQueuedChild);
  els.roiSelectionHint.textContent = !state.selectedRois.size ? "请至少选择一个意见目标；排队状态见每行右侧。" : stages.size > 1 ? "所选目标分属不同审核阶段，请只选择同一阶段后提交意见。" : generationInput ? "所选 ROI 的意见会保存进下一轮 Prompt；顶部按钮仍会处理全局全部橙色“已排队”ROI。" : "复选框只选择审核对象；驳回后，该 ROI 才会转为橙色“已排队”。";
}

async function renderPromptPreview(item) {
  const token = ++state.promptPreviewToken;
  const stage = reviewStage(item);
  const children = selectedChildren(item).filter((child) => child.source_mode === "labelme");
  if (!children.length || stage === "mask" || stage === "normal" || stage === "mixed") {
    els.promptPreviewBox.hidden = true; els.promptPreviewText.textContent = ""; return;
  }
  const queued = children.every((child) => ["pending_generation", "regen_queued", "qc_failed", "core_not_configured"].includes(child.workflow));
  els.promptPreviewBox.hidden = false;
  els.promptPreviewSummary.textContent = queued ? `视觉代理规划输入（${children.length}个ROI；CORE短指令将在规划后生成）` : `若驳回：下一轮视觉代理规划输入（${children.length}个ROI）`;
  els.promptPreviewText.textContent = "正在根据所选 ROI 和审核意见组装…";
  try {
    const payload = await api("/api/prompt-preview", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sample_ids: children.map((child) => child.id), reason_codes: selectedReasons(), comment: els.comment.value }),
    });
    if (token !== state.promptPreviewToken) return;
    els.promptPreviewText.textContent = payload.result.items.map((row, index) => {
      const label = row.labels.map((value) => `${value.code} / ${value.name}`).join("，");
      return `===== 所选 ROI ${index + 1}：${label}｜下一逻辑轮次 v${row.attempt} =====\n说明：以下内容交给视觉代理进行整图分析；代理随后会选择参考与Mask，并为每个CORE候选压缩生成独立短Prompt。\n\n${row.prompt}`;
    }).join("\n\n");
  } catch (error) {
    if (token === state.promptPreviewToken) els.promptPreviewText.textContent = `Prompt预览失败：${error.message}`;
  }
}

function schedulePromptPreview() {
  clearTimeout(schedulePromptPreview.timer);
  schedulePromptPreview.timer = setTimeout(() => { const item = currentItem(); if (item) renderPromptPreview(item); }, 180);
}

function toggleRoi(item, childId) {
  if (!isGrouped(item)) return;
  if (state.dirty && reviewStage(item) === "mask") { showToast("请先保存当前 Mask，再切换 ROI"); return; }
  const switchedBucket = updateRoiSelection(item, childId, !state.selectedRois.has(childId));
  selectCurrent(!switchedBucket);
}

function annotationText(annotation) {
  const geometry = annotation.shape_type === "rectangle" ? "矩形" : annotation.shape_type === "polygon" ? "多边形" : annotation.shape_type;
  return `${annotation.code} · ${annotation.name} · ${geometry}`;
}

function renderAnnotationLegend(target, item, includeChange) {
  const annotations = item.annotations || [];
  const chips = annotations.map((row) => {
    const active = isGrouped(item) ? state.selectedRois.has(row.child_id) : row.active;
    return `<button type="button" class="annotation-chip${active ? " active" : ""}" ${row.child_id ? `data-child-id="${row.child_id}"` : ""}>${active ? "已选：" : "未选："}${annotationText(row)}</button>`;
  }).join("");
  target.innerHTML = chips + `<span class="legend-key"><i class="legend-swatch"></i>LabelMe重点关注区</span>` +
    (annotations.some((row) => isGrouped(item) ? !state.selectedRois.has(row.child_id) : !row.active) ? `<span class="legend-key"><i class="legend-swatch context"></i>其他标注目标</span>` : "") +
    `<span class="legend-key"><i class="legend-swatch edit-region"></i>CORE上下文编辑区</span>` +
    (includeChange ? `<span class="legend-key"><i class="legend-swatch change"></i>实际变化/精细Mask</span>` : "");
}

function renderLegendWithToolbar(target, item, includeChange) {
  renderAnnotationLegend(target, item, includeChange);
  target.insertAdjacentHTML("beforeend",
    `<div class="view-toolbar" aria-label="图像显示控制">` +
      `<button type="button" class="view-toggle${state.showBoxes ? " active" : ""}" data-view-action="boxes" aria-pressed="${state.showBoxes}">标注框</button>` +
      `<button type="button" class="view-toggle${state.showEditRegion ? " active" : ""}" data-view-action="edit-region" aria-pressed="${state.showEditRegion}">CORE编辑区</button>` +
      `<button type="button" class="view-toggle${state.showMask ? " active" : ""}" data-view-action="mask" aria-pressed="${state.showMask}">实际Mask</button>` +
      `<i class="toolbar-divider"></i>` +
      `<button type="button" class="view-toggle${state.comparisonMode === "side" ? " active" : ""}" data-compare-mode="side">并排</button>` +
      `<button type="button" class="view-toggle${state.comparisonMode === "source" ? " active" : ""}" data-compare-mode="source">仅正常</button>` +
      `<button type="button" class="view-toggle${state.comparisonMode === "candidate" ? " active" : ""}" data-compare-mode="candidate">仅异常</button>` +
    `</div>`);
}

function applyLayoutState() {
  document.body.classList.toggle("queue-collapsed", state.queueCollapsed);
  document.body.classList.toggle("review-collapsed", state.reviewCollapsed);
  for (const grid of [els.comparisonGrid, els.maskComparisonGrid]) {
    grid.classList.toggle("mode-source", state.comparisonMode === "source");
    grid.classList.toggle("mode-candidate", state.comparisonMode === "candidate");
  }
  els.toggleQueuePanel.classList.toggle("active", !state.queueCollapsed);
  els.toggleReviewPanel.classList.toggle("active", !state.reviewCollapsed);
  els.toggleQueuePanel.setAttribute("aria-pressed", String(!state.queueCollapsed));
  els.toggleReviewPanel.setAttribute("aria-pressed", String(!state.reviewCollapsed));
  els.toggleQueuePanel.textContent = state.queueCollapsed ? "显示队列" : "隐藏队列";
  els.toggleReviewPanel.textContent = state.reviewCollapsed ? "显示审核" : "隐藏审核";
}

async function refreshCurrentVisuals() {
  const item = currentItem(); if (!item) return;
  const cycle = beginRenderCycle();
  const renderToken = cycle.token;
  applyLayoutState();
  const stage = reviewStage(item);
  if (stage === "mask" && !els.maskView.hidden) {
    renderLegendWithToolbar(els.maskAnnotationLegend, item, true);
    renderCanvas();
    try { await renderAnnotatedImage(els.maskSourceCanvas, item.images.source, item, "", renderToken, cycle.signal, editRegionUrls(item)); } catch (error) { reportRenderError(error); }
    return;
  }
  const generated = Boolean(item.images.candidate);
  renderLegendWithToolbar(els.annotationLegend, item, generated);
  try {
    await Promise.all([
      renderAnnotatedImage(els.sourceCanvas, item.images.source, item, "", renderToken, cycle.signal, editRegionUrls(item)),
      renderAnnotatedImage(els.candidateCanvas, item.images.candidate || item.images.source, item, generated ? item.images.mask : "", renderToken, cycle.signal, editRegionUrls(item)),
    ]);
  } catch (error) { reportRenderError(error); }
}

function setViewOption(action) {
  if (action === "boxes") {
    state.showBoxes = !state.showBoxes;
    writePreference("review.showBoxes", String(state.showBoxes));
  } else if (action === "edit-region") {
    state.showEditRegion = !state.showEditRegion;
    writePreference("review.showEditRegion", String(state.showEditRegion));
  } else if (action === "mask") {
    state.showMask = !state.showMask;
    writePreference("review.showMask", String(state.showMask));
  }
  refreshCurrentVisuals();
}

function setComparisonMode(mode) {
  if (!["side", "source", "candidate"].includes(mode)) return;
  state.comparisonMode = mode;
  writePreference("review.comparisonMode", mode);
  refreshCurrentVisuals();
}

function traceShape(ctx, annotation) {
  const points = (annotation.points || []).map((point) => ({ x: Number(point[0]), y: Number(point[1]) }));
  if (points.length < 2) return false;
  ctx.beginPath();
  if (annotation.shape_type === "rectangle") {
    const xs = points.map((point) => point.x), ys = points.map((point) => point.y);
    ctx.rect(Math.min(...xs), Math.min(...ys), Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys));
  } else if (annotation.shape_type === "circle") {
    const radius = Math.hypot(points[1].x - points[0].x, points[1].y - points[0].y);
    ctx.arc(points[0].x, points[0].y, radius, 0, Math.PI * 2);
  } else {
    ctx.moveTo(points[0].x, points[0].y);
    points.slice(1).forEach((point) => ctx.lineTo(point.x, point.y));
    if (!new Set(["line", "linestrip"]).has(annotation.shape_type)) ctx.closePath();
  }
  return true;
}

function drawAnnotations(ctx, item, width, height) {
  const annotations = [...(item.annotations || [])].sort((a, b) => Number(isGrouped(item) ? state.selectedRois.has(a.child_id) : a.active) - Number(isGrouped(item) ? state.selectedRois.has(b.child_id) : b.active));
  const base = Math.max(1, Math.min(width, height));
  const fontSize = Math.max(17, Math.round(base * 0.016));
  for (const annotation of annotations) {
    const active = isGrouped(item) ? state.selectedRois.has(annotation.child_id) : Boolean(annotation.active);
    ctx.save();
    ctx.strokeStyle = active ? "#55ff77" : "#4adbe8";
    ctx.lineWidth = active ? Math.max(3, base * 0.003) : Math.max(2, base * 0.002);
    ctx.globalAlpha = active ? 1 : 0.68;
    if (traceShape(ctx, annotation)) ctx.stroke();
    const points = annotation.points || [];
    if (points.length) {
      const x = Math.max(2, Math.min(...points.map((point) => Number(point[0]))));
      const y = Math.max(fontSize + 8, Math.min(...points.map((point) => Number(point[1]))));
      const text = active ? `${annotation.code}｜${annotation.name}` : annotation.code;
      ctx.font = `700 ${fontSize}px "Microsoft YaHei", sans-serif`;
      const boxWidth = ctx.measureText(text).width + 14;
      ctx.fillStyle = active ? "rgba(7, 56, 22, .88)" : "rgba(7, 43, 52, .78)";
      ctx.fillRect(x, y - fontSize - 7, boxWidth, fontSize + 8);
      ctx.fillStyle = active ? "#c8ffd2" : "#bceff4";
      ctx.fillText(text, x + 7, y - 6);
    }
    ctx.restore();
  }
}

function drawTintOverlay(ctx, mask, width, height, color, alpha) {
  const temp = document.createElement("canvas"); temp.width = width; temp.height = height;
  const tempCtx = temp.getContext("2d");
  tempCtx.drawImage(mask, 0, 0, width, height);
  // A grayscale mask multiplied by the tint is black outside the mask and
  // colored inside it.  Screen-compositing then leaves black pixels inert.
  // This replaces a JavaScript loop over several million pixels with native
  // canvas operations and keeps soft mask edges proportional.
  tempCtx.globalCompositeOperation = "multiply";
  tempCtx.fillStyle = `rgb(${color[0]}, ${color[1]}, ${color[2]})`;
  tempCtx.fillRect(0, 0, width, height);
  tempCtx.globalCompositeOperation = "source-over";
  ctx.save();
  ctx.globalCompositeOperation = "screen";
  ctx.globalAlpha = Math.max(0, Math.min(1, alpha / 255));
  ctx.drawImage(temp, 0, 0);
  ctx.restore();
}

function editRegionUrls(item) {
  if (!item) return [];
  if (isGrouped(item)) return selectedChildren(item).map((child) => child.images?.edit_region).filter(Boolean);
  return item.images?.edit_region ? [item.images.edit_region] : [];
}

function showCanvasLoading(canvas, item, text = "正在加载图片…") {
  const width = Math.max(320, Number(item?.width || 960));
  const height = Math.max(240, Number(item?.height || 640));
  canvas.width = width; canvas.height = height;
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#0b1117"; ctx.fillRect(0, 0, width, height);
  ctx.fillStyle = "#91a4b5";
  ctx.font = `600 ${Math.max(18, Math.round(Math.min(width, height) * 0.018))}px "Microsoft YaHei", sans-serif`;
  ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText(text, width / 2, height / 2);
}

async function renderAnnotatedImage(canvas, imageUrl, item, maskUrl = "", renderToken = null, signal = null, editUrls = []) {
  const maskPromise = maskUrl && state.showMask ? loadImage(maskUrl, signal) : Promise.resolve(null);
  const editPromise = state.showEditRegion ? Promise.all(editUrls.map((url) => loadImage(url, signal))) : Promise.resolve([]);
  const image = await loadImage(imageUrl, signal);
  if (renderToken !== null && renderToken !== state.renderToken) return false;
  canvas.width = image.naturalWidth || image.width; canvas.height = image.naturalHeight || image.height;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  const redraw = (mask = null, editMasks = []) => {
    ctx.clearRect(0, 0, canvas.width, canvas.height); ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
    for (const editMask of editMasks) drawTintOverlay(ctx, editMask, canvas.width, canvas.height, [255, 176, 40], 42);
    if (mask) drawTintOverlay(ctx, mask, canvas.width, canvas.height, [255, 42, 64], 92);
    if (state.showBoxes) drawAnnotations(ctx, item, canvas.width, canvas.height);
  };
  // Change the visible sample as soon as its base pixels arrive.  Optional
  // overlays are applied in a second pass and can no longer leave the old
  // sample frozen on screen while a large edit-region mask is calculated.
  redraw();
  const [mask, editMasks] = await Promise.all([maskPromise, editPromise]);
  if (renderToken !== null && renderToken !== state.renderToken) return false;
  redraw(mask, editMasks);
  return true;
}

function updateSummary(counts = {}) {
  const keys = ["pending_generation", "normal_review", "anomaly_review", "regen_queued", "qc_failed", "mask_review", "completed", "hold"];
  els.summary.innerHTML = keys.map((key) => `<span>${workflowName(key)}<b>${counts[key] || 0}</b></span>`).join("");
  renderGenerationPlan();
}

function populateFilters() {
  const currentLabel = els.labelFilter.value;
  const labels = [...new Set(state.items.flatMap((item) => item.labels.map((label) => label.code)))].sort();
  els.labelFilter.innerHTML = '<option value="">全部标签</option>' + labels.map((label) => `<option value="${label}">${label}</option>`).join("");
  els.labelFilter.value = labels.includes(currentLabel) ? currentLabel : "";
  const currentWorkflow = els.workflowFilter.value;
  const workflows = [...new Set(state.items.map((item) => item.workflow))].sort();
  els.workflowFilter.innerHTML = '<option value="">全部流程</option>' + workflows.map((value) => `<option value="${value}">${workflowName(value)}</option>`).join("");
  els.workflowFilter.value = workflows.includes(currentWorkflow) ? currentWorkflow : "";
}

function applyFilters(renderSelection = true) {
  if (typeof renderSelection !== "boolean") renderSelection = true;
  const label = els.labelFilter.value;
  const workflow = els.workflowFilter.value;
  const search = els.searchInput.value.trim().toLowerCase();
  state.filtered = state.items.filter((item) => {
    if (label && !item.labels.some((row) => row.code === label)) return false;
    if (workflow && item.workflow !== workflow) return false;
    const haystack = `${item.relative_json} ${item.labels.map((row) => `${row.code} ${row.name}`).join(" ")}`.toLowerCase();
    return !search || haystack.includes(search);
  });
  els.visibleCount.textContent = String(state.filtered.length);
  if (!state.filtered.some((item) => item.id === state.currentId)) state.currentId = state.filtered[0]?.id || null;
  renderQueue(); if (renderSelection) selectCurrent();
}

function liveQueueState(item) {
  const details = childrenFor(item).map((child, index) => ({ child, ...childRuntimeState(child, index) }));
  const batch = details.filter((detail) => detail.batch);
  if (!batch.length) return null;
  const priority = ["running", "transport_retrying", "retrying", "waiting", "failed", "needs_review", "succeeded"];
  const status = priority.find((value) => batch.some((detail) => detail.status === value)) || batch[0].status;
  const active = batch.find((detail) => detail.status === status) || batch[0];
  const finished = batch.filter((detail) => ["succeeded", "needs_review", "failed"].includes(detail.status)).length;
  const running = batch.filter((detail) => detail.active).length;
  const waiting = batch.filter((detail) => detail.status === "waiting").length;
  const failed = batch.filter((detail) => detail.status === "failed").length;
  const parts = [`本轮 ROI ${finished}/${batch.length}`];
  if (running) parts.push(`进行中 ${running}`);
  if (waiting) parts.push(`等待 ${waiting}`);
  if (failed) parts.push(`失败 ${failed}`);
  return {
    status,
    text: parts.join(" · "), stageText: active.text, details,
    attempt: Math.max(...batch.map((detail) => detail.attempt)),
    retryCount: Math.max(...batch.map((detail) => detail.retryCount)),
  };
}

function renderQueue() {
  els.queue.innerHTML = "";
  for (const item of state.filtered) {
    const button = document.createElement("button");
    const live = liveQueueState(item);
    button.className = `queue-item${item.id === state.currentId ? " active" : ""}${["running", "retrying", "transport_retrying"].includes(live?.status) ? " processing" : ""}`;
    const roiCount = item.children?.length ? ` · ${item.children.length}个标注目标` : "";
    const statusText = live?.text || workflowName(item.workflow);
    const version = live?.attempt || item.active_attempt;
    const retryText = live?.retryCount ? ` · 重试${live.retryCount}` : "";
    const roiProgress = isGrouped(item) ? `<span class="queue-roi-progress">${childrenFor(item).map((child, index) => {
      const runtime = live?.details?.[index] || childRuntimeState(child, index);
      const code = (child.labels || []).map((label) => label.code).join("/") || "未标注";
      return `<span class="queue-roi-row ${runtime.status}${runtime.active ? " active" : ""}"><i></i><b>ROI ${index + 1} · ${code}</b><em>${runtime.text}</em></span>`;
    }).join("")}</span>` : "";
    const activeStage = live?.stageText && ["running", "retrying", "transport_retrying"].includes(live.status)
      ? `<br><span class="queue-active-stage">当前：${live.stageText}</span>` : "";
    button.innerHTML = `<span class="row"><strong>${item.relative_json}</strong><span class="workflow-dot ${live?.status || item.workflow}"></span></span><small>${item.labels.map((row) => `${row.code} · ${row.name}`).join(" / ") || "无有效标签"}<br><b class="queue-live-status">${statusText}</b>${roiCount} · v${version}${retryText}${activeStage}${roiProgress}</small>`;
    button.onclick = () => { state.currentId = item.id; renderQueue(); selectCurrent(); };
    els.queue.appendChild(button);
  }
}

function reviewStage(item) { return isGrouped(item) ? selectedStage(item) : (item.stage === "mask" ? "mask" : item.stage === "normal" ? "normal" : "anomaly"); }

async function selectCurrent(preserveDraft = false) {
  const cycle = beginRenderCycle();
  const renderToken = cycle.token;
  const item = currentItem();
  const hasItem = Boolean(item);
  els.emptyState.hidden = hasItem;
  els.anomalyView.hidden = true; els.maskView.hidden = true;
  [els.approve, els.reject, els.hold, els.deleteSample, els.previous, els.next].forEach((button) => { button.disabled = !hasItem; });
  if (!item) {
    els.sampleTitle.textContent = "请选择样本"; els.sampleMeta.textContent = ""; els.reasonList.innerHTML = ""; els.roiSelectionSection.hidden = true; els.promptPreviewBox.hidden = true; renderGuide(null); return;
  }
  applyLayoutState();
  ensureSelection(item);
  renderGuide(item);
  const stage = reviewStage(item);
  const selected = selectedChildren(item);
  const selectionValid = selected.length > 0 && stage !== "mixed" && stage !== "none";
  const reviewable = selectionValid && selected.every(isReviewableChild);
  const generationInput = selectionValid && selected.every(isGenerationQueuedChild);
  els.sampleStage.textContent = generationInput ? "待生成输入" : stage === "mask" ? "Mask审核" : stage === "normal" ? "正常样本审核" : stage === "mixed" ? "目标阶段冲突" : "异常图审核";
  els.sampleTitle.textContent = item.relative_json;
  const roiMeta = isGrouped(item) ? ` · ${item.children.length}个标注目标，已选${selected.length}个` : "";
  els.sampleMeta.textContent = `${item.width}×${item.height}${roiMeta} · ${item.labels.map((row) => `${row.code} / ${row.name}`).join("，")} · 最高版本 ${item.active_attempt}`;
  els.reviewTitle.textContent = generationInput ? "所选标注目标的下一轮生成要求" : stage === "mask" ? "所选目标的 Mask 审核意见" : stage === "normal" ? "正常样本审核意见" : stage === "mixed" ? "请只选择同一阶段的目标" : "所选目标的异常图审核意见";
  els.reject.textContent = stage === "mask" ? "Mask不通过" : stage === "normal" ? "标记不合格" : "驳回重生成";
  els.reject.title = stage === "mask" ? `驳回所选 ${selected.length} 个 Mask` : `驳回所选 ${selected.length} 个 ROI 并加入重生成队列`;
  els.approve.textContent = generationInput ? "保存生成要求" : "通过";
  els.approve.title = generationInput ? `保存所选 ${selected.length} 个 ROI 的下一轮生成要求` : `通过所选 ${selected.length} 个 ROI`;
  els.reject.hidden = generationInput; els.hold.hidden = generationInput;
  els.approve.closest(".decision-grid").classList.toggle("queued-editing", generationInput);
  els.currentStatus.textContent = `${workflowName(item.workflow)}${isGrouped(item) ? ` · 已选${selected.length}/${item.children.length}` : ""}`;
  renderRoiSelection(item);
  renderGenerationPlan(item);
  const reviewValues = preserveDraft ? { reasons: selectedReasons(), comment: els.comment.value } : commonReviewValues(item, stage);
  els.comment.value = reviewValues.comment;
  renderReasons(stage === "mask" ? "mask" : "anomaly", reviewValues.reasons);
  renderPromptPreview(item);
  els.approve.disabled = generationInput ? !selectionValid : (!reviewable || (stage === "anomaly" && selected.some((child) => child.qc && child.qc.passed === false)));
  els.reject.disabled = generationInput || !reviewable; els.hold.disabled = generationInput || !reviewable;
  if (stage === "mask" && item.images.mask && item.images.candidate) {
    els.maskView.hidden = false;
    showCanvasLoading(els.maskSourceCanvas, item, "正在加载原图…");
    showCanvasLoading(els.editorCanvas, item, "正在加载异常图与 Mask…");
    try { await loadMaskEditor(item, renderToken, cycle.signal); } catch (error) { reportRenderError(error); }
  } else {
    els.anomalyView.hidden = false;
    showCanvasLoading(els.sourceCanvas, item, "正在加载原图…");
    showCanvasLoading(els.candidateCanvas, item, "正在加载生成结果…");
    const generated = Boolean(item.images.candidate);
    els.candidateCaption.textContent = generated ? (isGrouped(item) ? "右：多异常分层合成结果" : "右：CORE生成结果") : "右：生成输入预览";
    els.candidateHint.textContent = generated ? "绿色=重点，橙色=可编辑上下文，红色=实际变化" : "绿色LabelMe框负责定位；橙色区域允许异常自然越框并重建相邻结构";
    renderLegendWithToolbar(els.annotationLegend, item, generated);
    try {
      await Promise.all([
        renderAnnotatedImage(els.sourceCanvas, item.images.source, item, "", renderToken, cycle.signal, editRegionUrls(item)),
        renderAnnotatedImage(els.candidateCanvas, item.images.candidate || item.images.source, item, generated ? item.images.mask : "", renderToken, cycle.signal, editRegionUrls(item)),
      ]);
      if (renderToken !== state.renderToken) return;
    } catch (error) { reportRenderError(error); }
    els.qcText.textContent = JSON.stringify({ warnings: item.warnings, selected_rois: selected.map((child) => ({ id: child.id, labels: child.labels, workflow: child.workflow, qc: child.qc })), qc: item.qc }, null, 2);
  }
}

function renderReasons(stage, selected) {
  const reasons = stage === "mask" ? state.maskReasons : state.anomalyReasons;
  const chosen = new Set(selected || []);
  els.reasonList.innerHTML = reasons.map((code) => `<label class="reason-option"><input type="checkbox" value="${code}" ${chosen.has(code) ? "checked" : ""}><span>${reasonNames[code] || code}</span></label>`).join("");
}
function selectedReasons() { return [...els.reasonList.querySelectorAll('input:checked')].map((input) => input.value); }

async function loadMaskEditor(item, renderToken = null, signal = null) {
  const [candidate, mask, editMasks] = await Promise.all([
    loadImage(item.images.candidate, signal), loadImage(item.images.mask, signal),
    Promise.all(editRegionUrls(item).map((url) => loadImage(url, signal))),
  ]);
  if (renderToken !== null && renderToken !== state.renderToken) return false;
  state.candidate = candidate;
  state.editRegionMasks = editMasks;
  const { width, height } = candidate;
  for (const canvas of [els.editorCanvas, maskCanvas, overlayCanvas]) { canvas.width = width; canvas.height = height; }
  const temp = document.createElement("canvas"); temp.width = width; temp.height = height;
  const tempCtx = temp.getContext("2d", { willReadFrequently: true }); tempCtx.drawImage(mask, 0, 0, width, height);
  const pixels = tempCtx.getImageData(0, 0, width, height);
  for (let i = 0; i < pixels.data.length; i += 4) {
    const alpha = Math.max(pixels.data[i], pixels.data[i + 1], pixels.data[i + 2]);
    pixels.data[i] = 255; pixels.data[i + 1] = 255; pixels.data[i + 2] = 255; pixels.data[i + 3] = alpha;
  }
  maskCtx.clearRect(0, 0, width, height); maskCtx.putImageData(pixels, 0, 0);
  renderLegendWithToolbar(els.maskAnnotationLegend, item, true);
  await renderAnnotatedImage(els.maskSourceCanvas, item.images.source, item, "", renderToken, signal, editRegionUrls(item));
  if (renderToken !== null && renderToken !== state.renderToken) return false;
  state.undo = []; state.redo = []; state.dirty = false; els.maskSaveState.textContent = "已加载";
  renderCanvas();
}

function renderCanvas() {
  if (!state.candidate) return;
  editorCtx.clearRect(0, 0, els.editorCanvas.width, els.editorCanvas.height);
  editorCtx.drawImage(state.candidate, 0, 0, els.editorCanvas.width, els.editorCanvas.height);
  if (state.showEditRegion) {
    for (const editMask of state.editRegionMasks || []) {
      drawTintOverlay(editorCtx, editMask, els.editorCanvas.width, els.editorCanvas.height, [255, 176, 40], 42);
    }
  }
  overlayCtx.clearRect(0, 0, overlayCanvas.width, overlayCanvas.height);
  overlayCtx.drawImage(maskCanvas, 0, 0);
  overlayCtx.globalCompositeOperation = "source-in";
  overlayCtx.fillStyle = "#ff3245";
  overlayCtx.fillRect(0, 0, overlayCanvas.width, overlayCanvas.height);
  overlayCtx.globalCompositeOperation = "source-over";
  if (state.showMask) { editorCtx.save(); editorCtx.globalAlpha = state.opacity; editorCtx.drawImage(overlayCanvas, 0, 0); editorCtx.restore(); }
  const item = currentItem(); if (item && state.showBoxes) drawAnnotations(editorCtx, item, els.editorCanvas.width, els.editorCanvas.height);
}

function canvasPoint(event) {
  const rect = els.editorCanvas.getBoundingClientRect();
  return { x: (event.clientX - rect.left) * els.editorCanvas.width / rect.width, y: (event.clientY - rect.top) * els.editorCanvas.height / rect.height };
}
function displayCanvasPoint(canvas, event) {
  const rect = canvas.getBoundingClientRect();
  return { x: (event.clientX - rect.left) * canvas.width / rect.width, y: (event.clientY - rect.top) * canvas.height / rect.height };
}
function pointInPolygon(point, points) {
  let inside = false;
  for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
    const a = points[i], b = points[j];
    const intersects = ((a.y > point.y) !== (b.y > point.y)) && (point.x < (b.x - a.x) * (point.y - a.y) / ((b.y - a.y) || 1e-9) + a.x);
    if (intersects) inside = !inside;
  }
  return inside;
}
function annotationContains(annotation, point) {
  const points = (annotation.points || []).map((value) => ({ x: Number(value[0]), y: Number(value[1]) }));
  if (points.length < 2) return false;
  if (annotation.shape_type === "rectangle") {
    const xs = points.map((value) => value.x), ys = points.map((value) => value.y);
    return point.x >= Math.min(...xs) && point.x <= Math.max(...xs) && point.y >= Math.min(...ys) && point.y <= Math.max(...ys);
  }
  if (annotation.shape_type === "circle") {
    return Math.hypot(point.x - points[0].x, point.y - points[0].y) <= Math.hypot(points[1].x - points[0].x, points[1].y - points[0].y);
  }
  return points.length >= 3 && pointInPolygon(point, points);
}
function toggleRoiAtCanvas(canvas, event) {
  const item = currentItem(); if (!isGrouped(item)) return;
  const point = displayCanvasPoint(canvas, event);
  const annotation = [...(item.annotations || [])].reverse().find((row) => annotationContains(row, point));
  if (annotation?.child_id) toggleRoi(item, annotation.child_id);
}
function snapshot() { state.undo.push(maskCanvas.toDataURL("image/png")); if (state.undo.length > 30) state.undo.shift(); state.redo = []; }
function drawSegment(from, to) {
  const size = Number(els.brushSize.value);
  maskCtx.save(); maskCtx.lineCap = "round"; maskCtx.lineJoin = "round"; maskCtx.lineWidth = size;
  maskCtx.globalCompositeOperation = state.tool === "erase" ? "destination-out" : "source-over";
  maskCtx.strokeStyle = "white"; maskCtx.fillStyle = "white";
  maskCtx.beginPath(); maskCtx.moveTo(from.x, from.y); maskCtx.lineTo(to.x, to.y); maskCtx.stroke();
  maskCtx.beginPath(); maskCtx.arc(to.x, to.y, size / 2, 0, Math.PI * 2); maskCtx.fill(); maskCtx.restore();
  state.dirty = true; els.maskSaveState.textContent = "未保存"; renderCanvas();
}
async function restoreSnapshot(url) { const image = await loadImage(url); maskCtx.clearRect(0, 0, maskCanvas.width, maskCanvas.height); maskCtx.drawImage(image, 0, 0); renderCanvas(); }
async function undo() { if (!state.undo.length) return; state.redo.push(maskCanvas.toDataURL("image/png")); await restoreSnapshot(state.undo.pop()); state.dirty = true; }
async function redo() { if (!state.redo.length) return; state.undo.push(maskCanvas.toDataURL("image/png")); await restoreSnapshot(state.redo.pop()); state.dirty = true; }

async function saveMask(quiet = false) {
  const item = currentItem(); if (!item || reviewStage(item) !== "mask") return false;
  const output = document.createElement("canvas"); output.width = maskCanvas.width; output.height = maskCanvas.height;
  const ctx = output.getContext("2d"); ctx.fillStyle = "black"; ctx.fillRect(0, 0, output.width, output.height); ctx.drawImage(maskCanvas, 0, 0);
  els.maskSaveState.textContent = "保存中…";
  try {
    await api("/api/mask", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ sample_id: item.id, png: output.toDataURL("image/png") }) });
    state.dirty = false; els.maskSaveState.textContent = "已保存"; if (!quiet) showToast("Mask 已保存"); return true;
  } catch (error) { els.maskSaveState.textContent = "保存失败"; showToast(error.message); return false; }
}

async function saveGenerationFeedback() {
  const item = currentItem(); if (!item) return;
  const children = selectedChildren(item);
  if (!children.length) { showToast("请至少选择一个待生成 ROI"); return; }
  if (!children.every(isGenerationQueuedChild)) { showToast("当前选择包含无需重生成的 ROI，请重新选择"); return; }
  try {
    await api("/api/generation-feedback", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sample_ids: children.map((child) => child.id), reason_codes: selectedReasons(), comment: els.comment.value }),
    });
    showToast(`已保存 ${children.length} 个 ROI 的下一轮生成要求`);
    await reload();
  } catch (error) { showToast(error.message); }
}

async function submitReview(status) {
  const item = currentItem(); if (!item) return;
  const stage = reviewStage(item); const reasons = selectedReasons();
  const children = selectedChildren(item);
  if (!children.length) { showToast("请至少选择一个 ROI"); return; }
  if (["mixed", "none"].includes(stage)) { showToast("请只选择处于同一审核阶段的 ROI"); return; }
  if (!children.every(isReviewableChild)) { showToast("所选 ROI 尚未生成完成，暂不能提交审核"); return; }
  if (status === "rejected" && !reasons.length) { showToast("驳回时请至少选择一个问题类型"); return; }
  if (stage === "mask" && state.dirty && !(await saveMask(true))) return;
  try {
    const grouped = isGrouped(item);
    const endpoint = grouped ? "/api/review-batch" : "/api/review";
    const body = grouped
      ? { sample_ids: children.map((child) => child.id), stage, status, reason_codes: reasons, comment: els.comment.value }
      : { sample_id: item.id, stage, status, reason_codes: reasons, comment: els.comment.value };
    await api(endpoint, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const rejectedText = stage === "anomaly" ? `已将所选 ${children.length} 个 ROI 驳回并加入生成队列` : `所选 ${children.length} 个 Mask 未通过`;
    showToast(status === "approved" ? `所选 ${children.length} 个 ROI 已通过` : status === "rejected" ? rejectedText : `所选 ${children.length} 个 ROI 已暂缓`);
    await reload();
  } catch (error) { showToast(error.message); }
}

async function deleteSample() {
  const item = currentItem(); if (!item) return;
  const confirmation = prompt(`此操作会移动当前整个LabelMe样本目录。请输入sample_id确认：\n${item.id}`);
  if (confirmation !== item.id) return;
  try {
    const payload = await api("/api/delete-sample", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ sample_id: item.id, confirmation }) });
    showToast(`已移入回收目录，影响 ${payload.result.affected_samples} 个条目`); state.currentId = null; await reload();
  } catch (error) { showToast(error.message); }
}

async function runQueue() {
  try {
    const payload = await api("/api/run-queue", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
    showToast(payload.result.started ? `生成任务已启动，共 ${payload.result.total || 0} 个样本` : "生成任务正在运行");
    openJobDrawer();
    pollWorker(true);
  } catch (error) { showToast(error.message); }
}
function renderWorker(worker = {}) {
  state.worker = worker;
  const running = Boolean(worker.running), total = Number(worker.total || 0), completed = Number(worker.completed || 0);
  const currentJob = (worker.jobs || []).find((job) => job.id === worker.current_id);
  const currentStage = jobStageNames[worker.current_stage] || worker.current_stage || "正在准备下一阶段";
  const batchSize = Number(currentJob?.batch_size || (worker.current_batch_ids || []).length || 0);
  const batchText = worker.current_stage === "batch_planning" && batchSize > 1 ? ` · 同图 ${batchSize} 个ROI` : "";
  const stageStartedAt = Number(worker.current_stage_started_at || 0);
  const elapsedSeconds = stageStartedAt > 0 ? Math.max(0, Math.floor(Date.now() / 1000 - stageStartedAt)) : 0;
  const elapsedText = running && stageStartedAt > 0 ? ` · 已用时 ${Math.floor(elapsedSeconds / 60)}:${String(elapsedSeconds % 60).padStart(2, "0")}` : "";
  const candidateText = Number.isInteger(currentJob?.candidate_index)
    ? ` · 候选 ${currentJob.candidate_index + 1}/${currentJob.candidate_count || 1}`
    : "";
  const parallel = worker.parallel_planning || {};
  const parallelText = parallel.active
    ? ` · 并行规划 ${Number(parallel.sample_ids?.length || 0)} 个ROI`
    : parallel.status === "ready" ? " · 下一组规划已就绪" : "";
  els.runQueue.disabled = running;
  els.runQueue.textContent = running ? `正在生成 ${completed}/${total}` : `生成已排队 ROI（${queuedChildren().length}）`;
  els.workerProgress.hidden = !running;
  els.workerProgressBar.max = Math.max(1, total); els.workerProgressBar.value = completed;
  els.workerProgressText.textContent = running ? `${currentStage}${batchText}${candidateText}${parallelText}${elapsedText}` : "生成结束";
  els.workerProgressCounts.textContent = `${completed} / ${total}　成功 ${worker.succeeded || 0}　失败 ${worker.failed || 0}`;
  const labels = (worker.current_labels || []).join(" / ");
  els.workerProgressSample.textContent = worker.current_path
    ? `${labels ? `[${labels}] ` : ""}${worker.current_path}${batchText}`
    : "正在准备下一个样本…";
  renderJobDrawer(worker);
  renderQueue();
  const current = currentItem();
  if (current) {
    renderGenerationPlan(current);
    if (isGrouped(current)) renderRoiSelection(current);
  }
  const live = current ? liveQueueState(current) : null;
  if (live) els.currentStatus.textContent = `${live.text}${live.attempt ? ` · v${live.attempt}` : ""}${live.retryCount ? ` · 重试${live.retryCount}` : ""}`;
}
function workerItemsSignature(worker = {}) {
  // Only transitions that can change persisted sample data trigger /api/items.
  // Fine-grained stage/candidate changes are rendered directly from worker
  // state, avoiding a heavy full queue reload every 1.5 seconds.
  const jobs = (worker.jobs || []).map((job) => `${job.id}:${job.status}:${job.workflow}:${job.attempt}:${job.retry_count || 0}`).join(";");
  return [worker.running, worker.completed, worker.succeeded, worker.failed, worker.current_id, jobs].join("|");
}
function scheduleWorkerPoll(delay = 1500) {
  clearTimeout(state.pollTimer);
  state.pollTimer = setTimeout(() => pollWorker(true), delay);
}
async function pollWorker(announceCompletion = true) {
  if (state.pollInFlight) return;
  state.pollInFlight = true;
  try {
    const payload = await api("/api/worker-status");
    const signature = workerItemsSignature(payload);
    const itemsChanged = signature !== state.workerItemsSignature;
    renderWorker(payload);
    if (payload.running) {
      if (itemsChanged) await refreshItemsSilently();
      state.workerItemsSignature = signature;
      scheduleWorkerPoll();
    } else {
      clearTimeout(state.pollTimer); state.pollTimer = null;
      const wasRunning = Boolean(state.workerItemsSignature);
      state.workerItemsSignature = "";
      if (announceCompletion && wasRunning) {
        await reload();
        showToast(payload.last_error || `生成队列处理完成：成功 ${payload.succeeded || 0}，失败 ${payload.failed || 0}`);
      }
    }
  } catch (error) {
    scheduleWorkerPoll(3000);
    showToast(`生成状态刷新失败：${error.message}`);
  } finally {
    state.pollInFlight = false;
  }
}

function navigate(delta) {
  const index = state.filtered.findIndex((item) => item.id === state.currentId);
  if (index < 0 || !state.filtered.length) return;
  state.currentId = state.filtered[(index + delta + state.filtered.length) % state.filtered.length].id;
  renderQueue(); selectCurrent();
}

async function reload() {
  const payload = await api("/api/items");
  state.items = payload.items; state.anomalyReasons = payload.anomaly_reasons; state.maskReasons = payload.mask_reasons;
  updateSummary(payload.counts); populateFilters(); applyFilters();
  renderWorker(payload.worker || {});
  if (payload.worker?.running) {
    state.workerItemsSignature = workerItemsSignature(payload.worker);
    scheduleWorkerPoll();
  } else {
    clearTimeout(state.pollTimer); state.pollTimer = null; state.workerItemsSignature = "";
  }
}

async function refreshItemsSilently() {
  const previousId = state.currentId;
  const previous = currentItem();
  const previousVersion = previous ? `${previous.workflow}|${previous.active_attempt}|${previous.updated_at || ""}` : "";
  const payload = await api("/api/items");
  state.items = payload.items; state.anomalyReasons = payload.anomaly_reasons; state.maskReasons = payload.mask_reasons;
  updateSummary(payload.counts); populateFilters(); applyFilters(false); renderJobDrawer(state.worker);
  const current = currentItem();
  const currentVersion = current ? `${current.workflow}|${current.active_attempt}|${current.updated_at || ""}` : "";
  if (state.currentId !== previousId || currentVersion !== previousVersion) await selectCurrent(state.currentId === previousId);
}

function apiSettingsPayload() {
  return {
    api_key: els.apiKey.value.trim(),
    core: {
      adapter: els.coreAdapter.value, base_url: els.apiBaseUrl.value.trim(), endpoint: els.coreEndpoint.value.trim(),
      model: els.coreModel.value.trim(), quality: els.coreQuality.value, timeout_seconds: Number(els.coreTimeout.value),
      transport_retries: Number(els.coreTransportRetries.value), transport_job_retries: Number(els.coreTransportJobRetries.value),
    },
    intelligence: {
      enabled: els.intelEnabled.checked, model: els.intelModel.value.trim(), endpoint: els.intelEndpoint.value.trim(),
      reasoning_effort: els.intelEffort.value, orchestrator: els.intelOrchestrator.checked,
      parallel_planning: els.parallelPlanning.checked,
      planner: els.intelPlanner.checked, critic: els.intelCritic.checked, critic_gate: els.intelCriticGate.checked,
      reference_candidate_count: Number(els.refCandidateCount.value), approved_example_count: Number(els.approvedExampleCount.value),
      failed_example_count: Number(els.failedExampleCount.value),
      agentic_generation: els.agenticGeneration.checked, candidate_count: Number(els.agentCandidateCount.value),
      recent_failure_memory: Number(els.agentFailureMemory.value), comparative_critic: els.comparativeCritic.checked,
      timeout_seconds: Number(els.intelTimeout.value), transport_retries: Number(els.intelTransportRetries.value),
    },
    generation: {
      reference_count: Number(els.generationReferenceCount.value), edit_context_min_padding_px: Number(els.editMinPad.value),
      edit_context_padding_ratio: Number(els.editRatio.value), max_attempts: Number(els.maxAttempts.value),
      max_auto_retries_per_sample_per_run: Number(els.autoRetries.value),
      manual_review_after_retry_exhausted: els.manualReviewAfterRetries.checked,
      multi_roi_source_mode: els.multiRoiSourceMode.value,
    },
  };
}

function fillApiSettings(settings) {
  const core = settings.core || {}, intel = settings.intelligence || {}, generation = settings.generation || {};
  els.apiBaseUrl.value = core.base_url || ""; els.apiKey.value = "";
  els.apiKey.placeholder = core.api_key_configured ? "已配置；留空保持不变" : "尚未配置，请输入API Key";
  els.coreAdapter.value = core.adapter || "openai_image_edits"; els.coreModel.value = core.model || "gpt-image-2";
  els.coreEndpoint.value = core.endpoint || "/v1/images/edits"; els.coreQuality.value = core.quality || "high";
  els.coreTimeout.value = core.timeout_seconds || 900;
  els.coreTransportRetries.value = core.transport_retries || 4; els.coreTransportJobRetries.value = core.transport_job_retries ?? 2;
  els.intelEnabled.checked = Boolean(intel.enabled); els.intelModel.value = intel.model || "gpt-5.6-sol";
  els.intelEndpoint.value = intel.endpoint || "/v1/responses"; els.intelEffort.value = intel.reasoning_effort || "high";
  els.intelOrchestrator.checked = Boolean(intel.orchestrator); els.intelPlanner.checked = Boolean(intel.planner);
  els.parallelPlanning.checked = intel.parallel_planning !== false;
  els.intelCritic.checked = Boolean(intel.critic); els.intelCriticGate.checked = Boolean(intel.critic_gate);
  els.refCandidateCount.value = intel.reference_candidate_count || 5; els.approvedExampleCount.value = intel.approved_example_count ?? 2;
  els.failedExampleCount.value = intel.failed_example_count ?? 1;
  els.agenticGeneration.checked = intel.agentic_generation !== false; els.agentCandidateCount.value = intel.candidate_count || 3;
  els.agentFailureMemory.value = intel.recent_failure_memory ?? 4; els.comparativeCritic.checked = intel.comparative_critic !== false;
  els.intelTimeout.value = intel.timeout_seconds || 180; els.intelTransportRetries.value = intel.transport_retries || 4;
  els.generationReferenceCount.value = generation.reference_count || 2; els.editMinPad.value = generation.edit_context_min_padding_px || 96;
  els.editRatio.value = generation.edit_context_padding_ratio || 0.35; els.maxAttempts.value = generation.max_attempts || 30;
  els.autoRetries.value = generation.max_auto_retries_per_sample_per_run ?? 25;
  els.manualReviewAfterRetries.checked = generation.manual_review_after_retry_exhausted !== false;
  els.multiRoiSourceMode.value = generation.multi_roi_source_mode || "sequential_success";
  els.apiSettingsStatus.textContent = `密钥：${core.api_key_configured ? "已配置" : "未配置"}\n配置文件：${core.credential_file || "—"}`;
}

async function openApiSettings() {
  els.apiSettingsModal.hidden = false; els.apiSettingsBackdrop.hidden = false;
  els.apiSettingsStatus.textContent = "正在读取本机配置…";
  try { const payload = await api("/api/api-settings"); fillApiSettings(payload.result); }
  catch (error) { els.apiSettingsStatus.textContent = `读取失败：${error.message}`; }
}
function closeApiSettings() { els.apiSettingsModal.hidden = true; els.apiSettingsBackdrop.hidden = true; }
async function saveApiSettingsFromForm(quiet = false) {
  els.saveApiSettings.disabled = true; els.apiSettingsStatus.textContent = "正在保存并重新加载API客户端…";
  try {
    const payload = await api("/api/api-settings", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(apiSettingsPayload())});
    fillApiSettings(payload.result); if (!quiet) showToast("API与智能策略已保存并立即应用"); return true;
  } catch (error) { els.apiSettingsStatus.textContent = `保存失败：${error.message}`; return false; }
  finally { els.saveApiSettings.disabled = false; }
}
async function probeApi(target) {
  const saved = await saveApiSettingsFromForm(true); if (!saved) return;
  els.apiSettingsStatus.textContent = target === "core" ? "正在检查图像CORE协议与模型…" : "正在发送最小视觉LLM文本探测…";
  try {
    const payload = await api("/api/api-probe", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({target})});
    els.apiSettingsStatus.textContent = JSON.stringify(payload.result, null, 2);
  } catch (error) { els.apiSettingsStatus.textContent = `测试失败：${error.message}`; }
}

function configurePlatformCommands() {
  const clientPlatform = String(
    (navigator.userAgentData && navigator.userAgentData.platform)
      || navigator.platform
      || navigator.userAgent
      || ""
  );
  const commandKey = /windows|win32|win64/i.test(clientPlatform) ? "windowsCommand" : "posixCommand";
  const command = els.exportCommand.dataset[commandKey];
  if (command) els.exportCommand.textContent = command;
}

function bind() {
  configurePlatformCommands();
  applyLayoutState();
  for (const element of [els.labelFilter, els.workflowFilter]) element.addEventListener("change", applyFilters);
  els.searchInput.addEventListener("input", applyFilters);
  els.previous.onclick = () => navigate(-1); els.next.onclick = () => navigate(1);
  els.approve.onclick = () => {
    const item = currentItem();
    if (item && selectedChildren(item).length && selectedChildren(item).every(isGenerationQueuedChild)) saveGenerationFeedback();
    else submitReview("approved");
  };
  els.reject.onclick = () => submitReview("rejected"); els.hold.onclick = () => submitReview("hold");
  els.deleteSample.onclick = deleteSample; els.runQueue.onclick = runQueue; els.saveMask.onclick = () => saveMask(); els.undo.onclick = undo; els.redo.onclick = redo;
  els.jobDrawerToggle.onclick = openJobDrawer; els.jobDrawerClose.onclick = closeJobDrawer; els.drawerBackdrop.onclick = closeJobDrawer;
  els.apiSettingsOpen.onclick = openApiSettings; els.apiSettingsClose.onclick = closeApiSettings; els.apiSettingsBackdrop.onclick = closeApiSettings;
  els.saveApiSettings.onclick = () => saveApiSettingsFromForm(false); els.probeCore.onclick = () => probeApi("core"); els.probeIntelligence.onclick = () => probeApi("intelligence");
  els.toggleQueuePanel.onclick = () => {
    state.queueCollapsed = !state.queueCollapsed;
    writePreference("review.queueCollapsed", String(state.queueCollapsed));
    applyLayoutState();
  };
  els.toggleReviewPanel.onclick = () => {
    state.reviewCollapsed = !state.reviewCollapsed;
    writePreference("review.reviewCollapsed", String(state.reviewCollapsed));
    applyLayoutState();
  };
  els.jobFilterRow.addEventListener("click", (event) => {
    const button = event.target.closest("[data-job-filter]"); if (!button) return;
    state.jobFilter = button.dataset.jobFilter;
    els.jobFilterRow.querySelectorAll("[data-job-filter]").forEach((row) => row.classList.toggle("active", row === button));
    renderJobDrawer();
  });
  els.roiSelectionList.addEventListener("change", (event) => {
    const input = event.target.closest("[data-roi-id]"); if (!input) return;
    const item = currentItem(); if (!isGrouped(item)) return;
    const switchedBucket = updateRoiSelection(item, input.dataset.roiId, input.checked);
    selectCurrent(!switchedBucket);
  });
  els.selectReviewableRois.onclick = () => { const item = currentItem(); if (!isGrouped(item)) return; state.selectedRois = defaultSelection(item); selectCurrent(true); };
  els.clearRoiSelection.onclick = () => { state.selectedRois.clear(); selectCurrent(true); };
  for (const legend of [els.annotationLegend, els.maskAnnotationLegend]) legend.addEventListener("click", (event) => {
    const viewAction = event.target.closest("[data-view-action]");
    if (viewAction) { setViewOption(viewAction.dataset.viewAction); return; }
    const comparison = event.target.closest("[data-compare-mode]");
    if (comparison) { setComparisonMode(comparison.dataset.compareMode); return; }
    const chip = event.target.closest("[data-child-id]"); if (!chip) return; const item = currentItem(); toggleRoi(item, chip.dataset.childId);
  });
  els.reasonList.addEventListener("change", schedulePromptPreview);
  els.comment.addEventListener("input", schedulePromptPreview);
  for (const canvas of [els.sourceCanvas, els.candidateCanvas, els.maskSourceCanvas]) canvas.addEventListener("click", (event) => toggleRoiAtCanvas(canvas, event));
  els.drawTool.onclick = () => { state.tool = "draw"; els.drawTool.classList.add("active"); els.eraseTool.classList.remove("active"); };
  els.eraseTool.onclick = () => { state.tool = "erase"; els.eraseTool.classList.add("active"); els.drawTool.classList.remove("active"); };
  els.brushSize.oninput = () => { els.brushText.textContent = els.brushSize.value; };
  els.copyExportCommand.onclick = async () => {
    try { await navigator.clipboard.writeText(els.exportCommand.textContent); showToast("最终导出命令已复制"); }
    catch (_) { showToast("复制失败，请手动选择命令文本"); }
  };
  els.maskOpacity.oninput = () => { state.opacity = Number(els.maskOpacity.value) / 100; els.opacityText.textContent = `${els.maskOpacity.value}%`; renderCanvas(); };
  els.editorCanvas.addEventListener("pointerdown", (event) => { if (!currentItem()) return; snapshot(); state.drawing = true; state.lastPoint = canvasPoint(event); els.editorCanvas.setPointerCapture(event.pointerId); drawSegment(state.lastPoint, state.lastPoint); });
  els.editorCanvas.addEventListener("pointermove", (event) => { if (!state.drawing) return; const point = canvasPoint(event); drawSegment(state.lastPoint, point); state.lastPoint = point; });
  const stop = () => { state.drawing = false; state.lastPoint = null; };
  els.editorCanvas.addEventListener("pointerup", stop); els.editorCanvas.addEventListener("pointercancel", stop);
  window.addEventListener("keydown", (event) => { if (event.key === "Escape" && state.drawerOpen) { closeJobDrawer(); return; } if (event.target.matches("input, textarea, select")) return; if (event.key === "ArrowLeft") navigate(-1); if (event.key === "ArrowRight") navigate(1); });
}

bind(); reload().catch((error) => showToast(error.message));
