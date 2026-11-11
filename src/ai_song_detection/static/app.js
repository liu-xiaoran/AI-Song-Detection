"use strict";

const byId = (id) => document.getElementById(id);
const form = byId("upload-form");
const fileInput = byId("audio-file");
const dropZone = byId("drop-zone");
const analyzeButton = byId("analyze-button");
const errorMessage = byId("error-message");
const processStatus = byId("process-status");
const resultPanel = byId("result-panel");
const result = byId("detection-result");
const retryConnection = byId("retry-connection");
const allowedExtensions = new Set(["mp3", "wav", "flac", "m4a", "aac", "ogg", "opus", "aiff", "aif", "wma"]);
const terminalStates = new Set(["completed", "failed", "cancelled"]);
const maxBytes = 100 * 1024 * 1024;
const tracks = [];
let nextId = 1;
let activeItem = null;
let selectedReport = null;
let queueStarted = false;
let runnerBusy = false;
let queueBlocked = false;
let blockedInstance = null;
let serverInstance = null;
let serviceReady = false;
let healthCheck = null;

function showError(message) {
  errorMessage.textContent = message;
  errorMessage.hidden = false;
}
function clearError() {
  errorMessage.hidden = true;
  errorMessage.textContent = "";
}
function duration(seconds) {
  if (!Number.isFinite(seconds)) return "Unavailable";
  if (seconds < 60) return `${seconds.toFixed(1)} sec`;
  const rounded = Math.round(seconds);
  return `${Math.floor(rounded / 60)} min ${String(rounded % 60).padStart(2, "0")} sec`;
}
function windowLabel(item) {
  return `${duration(item.start)} start · ${duration(item.duration)} requested`;
}
function settings() {
  const start = Number(byId("start-seconds").value);
  const length = Number(byId("duration-seconds").value);
  if (byId("start-seconds").value.trim() === "" || byId("duration-seconds").value.trim() === "" || !Number.isFinite(start) || start < 0 || !Number.isFinite(length) || length < 10 || length > 300) {
    throw new Error("Choose a start time of 0 or later and an analysis duration between 10 and 300 seconds.");
  }
  return { start, duration: length };
}
function addFiles(files) {
  clearError();
  let options;
  try { options = settings(); } catch (error) { showError(error.message); return; }
  const errors = [];
  for (const file of files) {
    const extension = file.name.split(".").pop().toLowerCase();
    if (!allowedExtensions.has(extension)) errors.push(`${file.name}: unsupported audio format.`);
    else if (file.size === 0) errors.push(`${file.name}: this file is empty.`);
    else if (file.size > maxBytes) errors.push(`${file.name}: exceeds the 100 MB limit.`);
    else tracks.push({ id: nextId++, file, name: file.name, size: file.size, ...options, status: "queued", jobId: null, result: null, error: null, cancelRequested: false, cancelSent: false, progress: 0, stage: "queued", reconnecting: false });
  }
  fileInput.value = "";
  if (errors.length) showError(errors.join(" "));
  renderTracks();
  if (queueStarted) void runQueue();
}
// Kept as a small entry point for integrations that select one track.
function selectFile(file) { if (file) addFiles([file]); }
function makeButton(text, handler, disabled = false) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "small-button";
  button.textContent = text;
  button.disabled = disabled;
  button.addEventListener("click", handler);
  return button;
}
function statusText(item) {
  if (item.reconnecting) return "Connection interrupted · checking job";
  if (item.cancelRequested && !terminalStates.has(item.status)) return item.jobId ? "Cancelling · waiting for the detector" : "Cancel requested · waiting for upload response";
  if (item.status === "uploading") return item.progress >= 100 ? "Upload sent · waiting for detector" : `Uploading · ${item.progress}%`;
  const stages = { queued: "Queued on detector", hashing: "Checking input", decoding: "Decoding audio", preprocessing: "Preparing audio", inference: "Running detection", complete: "Complete" };
  if (item.status === "running") return stages[item.stage] || "Analyzing";
  return { queued: "Queued", completed: "Completed", failed: "Failed", cancelled: "Cancelled" }[item.status] || "Cancelling";
}
function renderRow(item, history) {
  const cacheKey = history ? "historyRow" : "queueRow";
  if (item[cacheKey]) {
    const cached = item[cacheKey];
    cached.row.classList.toggle("selected", selectedReport === item);
    cached.row.dataset.status = item.status;
    cached.detail.textContent = `${statusText(item)} · ${windowLabel(item)}`;
    cached.error.textContent = item.error?.message || "";
    cached.error.hidden = !item.error;
    cached.progress.hidden = item.status !== "uploading";
    cached.progress.value = item.progress;
    if (cached.cancel) cached.cancel.disabled = item.cancelRequested;
    if (cached.retry) cached.retry.disabled = queueBlocked || !item.file;
    return cached.row;
  }
  const row = document.createElement("li");
  row.className = `track-row${selectedReport === item ? " selected" : ""}`;
  row.dataset.status = item.status;
  const info = document.createElement("div");
  info.className = "track-info";
  const title = document.createElement("span");
  title.className = "track-name";
  title.textContent = item.name;
  const detail = document.createElement("span");
  detail.className = "track-detail";
  detail.textContent = `${statusText(item)} · ${windowLabel(item)}`;
  info.append(title, detail);
  const error = document.createElement("span");
  error.className = "track-error";
  error.textContent = item.error?.message || "";
  error.hidden = !item.error;
  const progress = document.createElement("progress");
  progress.max = 100;
  progress.value = item.progress;
  progress.hidden = item.status !== "uploading";
  progress.setAttribute("aria-label", `Upload progress for ${item.name}`);
  info.append(error, progress);
  const actions = document.createElement("div");
  actions.className = "track-actions";
  let retry;
  let cancel;
  if (history) {
    actions.append(makeButton("View", () => selectReport(item)));
    if (item.status === "failed") {
      retry = makeButton("Retry", () => retryItem(item), queueBlocked || !item.file);
      actions.append(retry);
    }
  } else {
    cancel = makeButton("Cancel", () => cancelItem(item), item.cancelRequested);
    actions.append(cancel);
  }
  row.append(info, actions);
  item[cacheKey] = { row, detail, error, progress, retry, cancel };
  return row;
}
function updateList(list, rows) {
  // Keep existing nodes in place during polling so keyboard focus stays on actions.
  if (list.children.length !== rows.length || rows.some((row, index) => list.children[index] !== row)) list.replaceChildren(...rows);
}
function renderTracks() {
  const pending = tracks.filter((item) => !terminalStates.has(item.status));
  const history = tracks.filter((item) => terminalStates.has(item.status));
  updateList(byId("queue-list"), pending.map((item) => renderRow(item, false)));
  updateList(byId("history-list"), history.map((item) => renderRow(item, true)));
  byId("queue-section").hidden = pending.length === 0;
  byId("history-section").hidden = history.length === 0;
  const waiting = tracks.filter((item) => item.status === "queued" && item !== activeItem);
  byId("selected-file").hidden = waiting.length === 0;
  byId("file-name").textContent = waiting.length === 1 ? waiting[0].name : `${waiting.length} tracks queued`;
  const bytes = waiting.reduce((total, item) => total + item.size, 0);
  byId("file-size").textContent = `${(bytes / 1024 / 1024).toFixed(1)} MB total`;
  byId("clear-queued").disabled = waiting.length === 0;
  analyzeButton.disabled = runnerBusy || queueBlocked || waiting.length === 0 || !serviceReady;
  analyzeButton.classList.toggle("processing", runnerBusy);
  byId("button-label").textContent = runnerBusy ? "Processing queue…" : "Start queue";
  byId("button-arrow").hidden = runnerBusy;
  byId("button-spinner").hidden = !runnerBusy;
  resultPanel.setAttribute("aria-busy", String(Boolean(activeItem)));
}
function cancelItem(item) {
  if (item === activeItem) {
    item.cancelRequested = true;
    processStatus.textContent = "Cancellation requested. The next track waits until this job has stopped.";
  } else if (item.status === "queued") {
    item.status = "cancelled";
    item.file = null;
  }
  renderTracks();
}
function clearQueued() {
  for (let index = tracks.length - 1; index >= 0; index--) {
    if (tracks[index].status === "queued" && tracks[index] !== activeItem) tracks.splice(index, 1);
  }
  renderTracks();
}
function retryItem(item) {
  if (item.status !== "failed" || queueBlocked || !item.file) return;
  // A retry is a new attempt. Keep the failed report available in history.
  tracks.push({ ...item, id: nextId++, status: "queued", jobId: null, result: null, error: null, cancelRequested: false, cancelSent: false, progress: 0, stage: "queued", reconnecting: false, queueRow: null, historyRow: null });
  renderTracks();
  if (queueStarted) void runQueue();
}
function hideResult() {
  result.hidden = true;
  byId("empty-result").hidden = false;
  byId("report-actions").hidden = true;
  resultPanel.removeAttribute("data-assessment");
  byId("empty-title").textContent = "Every track has a signature.";
  byId("empty-description").textContent = "Choose a completed report from this session or start the queue.";
}
function validateResult(data) {
  if (!data || !Number.isFinite(data.ai_score) || data.ai_score < 0 || data.ai_score > 1 || !["likely_ai_generated", "likely_human_created", "uncertain"].includes(data.assessment)) throw new Error("The detector returned an invalid report.");
}
function showResult(data) {
  validateResult(data);
  const assessments = {
    likely_ai_generated: ["Likely AI-generated", "The analyzed window shows patterns associated with AI generators this model was trained to detect."],
    likely_human_created: ["Likely human-created", "The model found fewer of the AI patterns it recognizes in this window. This does not rule out AI use."],
    uncertain: ["Uncertain", "The score falls in the review range. The detector cannot make a clear assessment of this window."]
  };
  byId("result-file").textContent = data.filename || selectedReport?.name || "Audio report";
  byId("assessment-label").textContent = assessments[data.assessment][0];
  byId("assessment-description").textContent = assessments[data.assessment][1];
  byId("score-value").textContent = data.ai_score.toFixed(3);
  byId("score-fill").style.width = `${data.ai_score * 100}%`;
  byId("score-meter").setAttribute("aria-valuenow", String(data.ai_score));
  byId("score-meter").setAttribute("aria-valuetext", `${data.ai_score.toFixed(3)} out of 1. Uncalibrated model score.`);
  byId("analyzed-duration").textContent = duration(data.analyzed_duration_seconds);
  byId("processing-time").textContent = Number.isFinite(data.processing_time_ms) ? `${(data.processing_time_ms / 1000).toFixed(2)} sec` : "Unavailable";
  const start = Number.isFinite(data.analyzed_start_seconds) ? data.analyzed_start_seconds : 0;
  const end = Number.isFinite(data.analyzed_end_seconds) ? data.analyzed_end_seconds : start + data.analyzed_duration_seconds;
  const fullCoverage = start === 0 && Number.isFinite(data.audio_duration_seconds) && end >= data.audio_duration_seconds - 0.01;
  byId("analyzed-coverage").textContent = `Coverage: ${duration(start)} to ${duration(end)} of ${duration(data.audio_duration_seconds)}. ${fullCoverage ? "The full track was screened." : "The rest of the track was not screened."}`;
  byId("report-id").textContent = data.report_id || "Unavailable";
  byId("input-sha256").textContent = data.input_sha256 || "Unavailable";
  byId("report-model").textContent = `${data.model?.name || "Unknown"} ${data.model?.version || ""}`.trim();
  const policy = data.decision_policy;
  byId("report-policy").textContent = policy ? `${policy.id} ${policy.version} · human below ${policy.human_below}, AI above ${policy.ai_above} · ${policy.validated ? "validated" : "not independently validated"}` : "Unavailable";
  byId("report-time").textContent = data.analyzed_at || "Unavailable";
  const warnings = Array.isArray(data.warnings) ? data.warnings.filter((item) => typeof item === "string") : [];
  byId("result-warnings").replaceChildren(...warnings.map((warning) => {
    const item = document.createElement("li"); item.textContent = warning; return item;
  }));
  byId("result-warnings").hidden = warnings.length === 0;
  resultPanel.dataset.assessment = data.assessment;
  byId("empty-result").hidden = true;
  result.hidden = false;
}
function selectReport(item) {
  selectedReport = item;
  byId("export-status").textContent = "";
  if (item.result) showResult(item.result);
  else {
    hideResult();
    byId("empty-title").textContent = item.status === "cancelled" ? "Analysis cancelled" : "Analysis failed";
    byId("empty-description").textContent = `${item.name}: ${item.error?.message || "No detection result was produced."}`;
  }
  byId("report-actions").hidden = false;
  renderTracks();
}
function pauseUnknown(item, message) {
  queueBlocked = true;
  blockedInstance = item.serverInstance || serverInstance;
  queueStarted = false;
  item.status = "failed";
  item.error = { code: "job_state_unknown", message };
  processStatus.textContent = "Queue paused: the job state is unknown. Restart the detector, then retry connection. No audio will be uploaded again automatically.";
  showError(processStatus.textContent);
}
function uploadItem(item) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api/v1/jobs?start_seconds=${encodeURIComponent(item.start)}&duration_seconds=${encodeURIComponent(item.duration)}`);
    xhr.timeout = 120000;
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) item.progress = Math.min(100, Math.round(event.loaded / event.total * 100));
      renderTracks();
    };
    const ambiguous = (message) => { const error = new Error(message); error.ambiguous = true; reject(error); };
    xhr.onerror = () => ambiguous("The upload connection was lost. The detector may have accepted this track.");
    xhr.ontimeout = () => ambiguous("The upload response timed out. The detector may have accepted this track.");
    xhr.onabort = () => ambiguous("The upload was interrupted. The detector may have accepted this track.");
    xhr.onload = () => {
      let data;
      try { data = JSON.parse(xhr.responseText); } catch {
        if (xhr.status >= 200 && xhr.status < 300) ambiguous("The upload response was unreadable. The job state is unknown.");
        else reject(new Error(`Upload failed (HTTP ${xhr.status}).`));
        return;
      }
      if (xhr.status < 200 || xhr.status >= 300) {
        const detail = data.detail;
        reject(new Error(typeof detail === "string" ? detail : detail?.message || `Upload failed (HTTP ${xhr.status}).`));
      } else if (typeof data.id !== "string") ambiguous("The detector did not return a job ID. The job state is unknown.");
      else resolve(data);
    };
    const body = new FormData();
    body.append("file", item.file);
    xhr.send(body);
  });
}
const delay = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));
async function jobRequest(item, cancel = false) {
  const response = await fetch(`/api/v1/jobs/${encodeURIComponent(item.jobId)}${cancel ? "/cancel" : ""}`, { method: cancel ? "POST" : "GET", cache: "no-store", signal: AbortSignal.timeout(5000) });
  if (response.status === 404) { const error = new Error("This job is no longer available on the detector."); error.ambiguous = true; throw error; }
  if (!response.ok) throw new Error(`Could not ${cancel ? "cancel" : "check"} the job (HTTP ${response.status}).`);
  const job = await response.json();
  if (job.id !== item.jobId || !["queued", "running", "cancelling", "completed", "failed", "cancelled"].includes(job.status)) throw new Error("The detector returned an invalid job status.");
  return job;
}
async function waitForJob(item, initial) {
  let job = initial;
  while (true) {
    item.status = job.status === "queued" ? "running" : job.status;
    item.stage = job.stage;
    item.reconnecting = false;
    if (terminalStates.has(job.status)) return job;
    renderTracks();
    await delay(500);
    try {
      if (item.cancelRequested && !item.cancelSent) {
        job = await jobRequest(item, true);
        item.cancelSent = true;
        if (terminalStates.has(job.status)) continue;
      }
      job = await jobRequest(item);
    } catch (error) {
      if (error.ambiguous) throw error;
      item.reconnecting = true;
      setConnection(false, "Connection interrupted");
      processStatus.textContent = "Connection interrupted. Checking the accepted job again; your audio will not be uploaded twice.";
      renderTracks();
      await delay(1500);
    }
  }
}
async function runQueue() {
  if (runnerBusy || !queueStarted || queueBlocked) return;
  runnerBusy = true;
  renderTracks();
  try {
    while (queueStarted && !queueBlocked) {
      const item = tracks.find((track) => track.status === "queued");
      if (!item) break;
      if (!await checkHealth()) {
        queueStarted = false;
        processStatus.textContent = "Queue paused. Retry the connection, then start the queue. Your files are still selected.";
        break;
      }
      if (!tracks.includes(item) || item.status !== "queued") continue;
      activeItem = item;
      item.serverInstance = serverInstance;
      item.status = "uploading";
      processStatus.textContent = "Tracks are processed one at a time. You can add more files while this job runs.";
      renderTracks();
      try {
        const accepted = await uploadItem(item);
        item.jobId = accepted.id;
        const job = await waitForJob(item, accepted);
        item.status = job.status;
        item.error = job.error;
        if (job.status === "completed") { validateResult(job.result); item.result = job.result; }
        if (job.status !== "failed") item.file = null;
      } catch (error) {
        if (error.ambiguous) pauseUnknown(item, error.message);
        else { item.status = "failed"; item.error = { code: "client_error", message: error.message || "Analysis failed." }; }
      }
      activeItem = null;
      item.reconnecting = false;
      selectReport(item);
    }
  } finally {
    activeItem = null;
    runnerBusy = false;
    if (!queueBlocked && queueStarted && !tracks.some((item) => item.status === "queued")) {
      queueStarted = false;
      processStatus.textContent = "Queue complete. Select a report below or add more tracks.";
    }
    renderTracks();
  }
}
function reportData(item) {
  return item.result || { filename: item.name, status: item.status, job_id: item.jobId, requested_start_seconds: item.start, requested_duration_seconds: item.duration, input_size_bytes: item.size, error: item.error };
}
function csvCell(value) {
  let text = value == null ? "" : String(value);
  // Quote every field and neutralize formulas, including leading spaces/control characters.
  if (/^[\s\u0000-\u001f]|^[=+\-@]/u.test(text)) text = `'${text}`;
  return `"${text.replaceAll('"', '""')}"`;
}
function reportsCSV(items) {
  const headers = ["filename", "status", "assessment", "ai_score", "analyzed_start_seconds", "analyzed_end_seconds", "analyzed_duration_seconds", "audio_duration_seconds", "requested_duration_seconds", "processing_time_ms", "report_id", "analyzed_at", "input_sha256", "input_size_bytes", "application_version", "model_name", "model_version", "model_sha256", "upstream_commit", "decision_policy", "policy_validated", "human_below", "ai_above", "uncertain_inclusive", "upstream_binary_threshold", "warnings", "error"];
  const rows = items.map((item) => {
    const data = reportData(item);
    return [item.name, item.status, data.assessment, data.ai_score, data.analyzed_start_seconds ?? item.start, data.analyzed_end_seconds, data.analyzed_duration_seconds, data.audio_duration_seconds, data.requested_duration_seconds ?? item.duration, data.processing_time_ms, data.report_id, data.analyzed_at, data.input_sha256, data.input_size_bytes ?? item.size, data.application_version, data.model?.name, data.model?.version, data.model?.sha256, data.model?.upstream_commit, data.decision_policy ? `${data.decision_policy.id}:${data.decision_policy.version}` : "", data.decision_policy?.validated, data.decision_policy?.human_below, data.decision_policy?.ai_above, data.decision_policy?.uncertain_inclusive?.join("–"), data.upstream_binary_threshold, data.warnings?.join(" | "), data.error?.message];
  });
  return [headers, ...rows].map((row) => row.map(csvCell).join(",")).join("\r\n") + "\r\n";
}
function exportText(items, format, all = false) {
  if (format === "csv") return reportsCSV(items);
  return JSON.stringify(all ? { schema_version: 1, exported_at: new Date().toISOString(), reports: items.map(reportData) } : reportData(items[0]), null, 2);
}
function downloadReport(format, all = false) {
  const items = all ? tracks.filter((item) => terminalStates.has(item.status)) : selectedReport ? [selectedReport] : [];
  if (!items.length) return;
  const blob = new Blob([exportText(items, format, all)], { type: format === "csv" ? "text/csv;charset=utf-8" : "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `ai-song-detection-${all ? "session" : selectedReport.id}.${format}`;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  byId("export-status").textContent = `${all ? "Session reports" : "Report"} downloaded as ${format.toUpperCase()}.`;
}
async function copyReport(format) {
  if (!selectedReport) return;
  try {
    await navigator.clipboard.writeText(exportText([selectedReport], format));
    byId("export-status").textContent = `${format.toUpperCase()} copied.`;
  } catch {
    byId("export-status").textContent = "Clipboard unavailable. Use Download instead.";
  }
}
function setConnection(ready, message) {
  serviceReady = ready;
  byId("service-status").classList.toggle("ready", ready);
  byId("service-status").classList.toggle("unavailable", !ready);
  byId("service-label").textContent = message;
  byId("connection-notice").hidden = ready;
  renderTracks();
}
function checkHealth() {
  if (healthCheck) return healthCheck;
  retryConnection.disabled = true;
  healthCheck = (async () => {
    try {
      const response = await fetch("/health", { cache: "no-store", signal: AbortSignal.timeout(4000) });
      const health = await response.json();
      const ready = response.ok && health.app_id === "ai-song-detection" && health.model_loaded === true && health.ffmpeg_available === true;
      if (ready && queueBlocked && blockedInstance && health.instance_id && health.instance_id !== blockedInstance) {
        queueBlocked = false;
        clearError();
        processStatus.textContent = "Detector restarted. You can retry failed tracks or start the remaining queue.";
      }
      if (ready) serverInstance = health.instance_id || serverInstance;
      setConnection(Boolean(ready), ready ? "Detector ready" : "Detector unavailable");
      return Boolean(ready);
    } catch {
      setConnection(false, "Connection unavailable");
      return false;
    } finally { retryConnection.disabled = false; healthCheck = null; }
  })();
  return healthCheck;
}
fileInput.addEventListener("change", () => addFiles(Array.from(fileInput.files)));
byId("remove-file").addEventListener("click", clearQueued);
byId("clear-queued").addEventListener("click", clearQueued);
for (const name of ["dragenter", "dragover"]) dropZone.addEventListener(name, (event) => { event.preventDefault(); dropZone.classList.add("dragging"); });
for (const name of ["dragleave", "drop"]) dropZone.addEventListener(name, (event) => { event.preventDefault(); dropZone.classList.remove("dragging"); });
dropZone.addEventListener("drop", (event) => addFiles(Array.from(event.dataTransfer.files)));
form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (runnerBusy || queueBlocked || !serviceReady) return;
  clearError();
  queueStarted = true;
  await runQueue();
});
byId("clear-history").addEventListener("click", () => {
  for (let index = tracks.length - 1; index >= 0; index--) if (terminalStates.has(tracks[index].status)) tracks.splice(index, 1);
  selectedReport = null;
  hideResult();
  renderTracks();
});
for (const format of ["json", "csv"]) {
  byId(`download-${format}`).addEventListener("click", () => downloadReport(format));
  byId(`copy-${format}`).addEventListener("click", () => copyReport(format));
  byId(`download-all-${format}`).addEventListener("click", () => downloadReport(format, true));
}
retryConnection.addEventListener("click", checkHealth);
window.addEventListener("online", checkHealth);
window.addEventListener("focus", checkHealth);
document.addEventListener("visibilitychange", () => { if (!document.hidden) void checkHealth(); });
setInterval(() => { if (!document.hidden) void checkHealth(); }, 5000);
renderTracks();
void checkHealth();
