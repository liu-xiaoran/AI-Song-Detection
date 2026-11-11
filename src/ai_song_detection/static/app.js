"use strict";

const form = document.getElementById("upload-form");
const fileInput = document.getElementById("audio-file");
const dropZone = document.getElementById("drop-zone");
const selectedFile = document.getElementById("selected-file");
const analyzeButton = document.getElementById("analyze-button");
const removeButton = document.getElementById("remove-file");
const errorMessage = document.getElementById("error-message");
const processStatus = document.getElementById("process-status");
const resultPanel = document.getElementById("result-panel");
const emptyResult = document.getElementById("empty-result");
const result = document.getElementById("detection-result");
const allowedExtensions = new Set(["mp3", "wav", "flac", "m4a", "aac", "ogg", "opus", "aiff", "aif", "wma"]);
const maxBytes = 100 * 1024 * 1024;
let currentFile = null;
let busy = false;

function showError(message) {
  errorMessage.textContent = message;
  errorMessage.hidden = false;
}

function clearError() {
  errorMessage.hidden = true;
  errorMessage.textContent = "";
}

function hideResult() {
  result.hidden = true;
  emptyResult.hidden = false;
  resultPanel.removeAttribute("data-assessment");
  document.getElementById("empty-title").textContent = "Every track has a signature.";
  document.getElementById("empty-description").textContent = "Your result will appear here once the audio has been analyzed.";
}

function selectFile(file) {
  if (busy) return;
  clearError();
  hideResult();
  processStatus.textContent = "";
  currentFile = null;
  selectedFile.hidden = true;
  analyzeButton.disabled = true;
  if (!file) return;
  const extension = file.name.split(".").pop().toLowerCase();
  if (!allowedExtensions.has(extension)) {
    fileInput.value = "";
    showError("Choose a supported audio file: MP3, WAV, FLAC, M4A, AAC, OGG, OPUS, AIFF, or WMA.");
    return;
  }
  if (file.size === 0) {
    fileInput.value = "";
    showError("This file is empty. Choose another audio file.");
    return;
  }
  if (file.size > maxBytes) {
    fileInput.value = "";
    showError("This file is larger than 100 MB. Choose a smaller audio file.");
    return;
  }
  currentFile = file;
  document.getElementById("file-name").textContent = file.name;
  document.getElementById("file-size").textContent = file.size < 1024 * 1024
    ? `${Math.max(1, Math.round(file.size / 1024))} KB`
    : `${(file.size / 1024 / 1024).toFixed(1)} MB`;
  selectedFile.hidden = false;
  analyzeButton.disabled = false;
}

fileInput.addEventListener("change", () => selectFile(fileInput.files[0]));
removeButton.addEventListener("click", () => {
  fileInput.value = "";
  selectFile(null);
  fileInput.focus();
});

for (const eventName of ["dragenter", "dragover"]) {
  dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    if (!busy) dropZone.classList.add("dragging");
  });
}
for (const eventName of ["dragleave", "drop"]) {
  dropZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    dropZone.classList.remove("dragging");
  });
}
dropZone.addEventListener("drop", (event) => {
  if (busy) return;
  const files = event.dataTransfer.files;
  if (files.length !== 1) {
    showError("Choose one audio file at a time.");
    return;
  }
  fileInput.value = "";
  selectFile(files[0]);
});

function setBusy(value) {
  busy = value;
  analyzeButton.disabled = value || !currentFile;
  analyzeButton.classList.toggle("processing", value);
  fileInput.disabled = value;
  removeButton.disabled = value;
  dropZone.classList.toggle("disabled", value);
  resultPanel.setAttribute("aria-busy", String(value));
  document.getElementById("button-label").textContent = value ? "Analyzing track…" : "Analyze track";
  document.getElementById("button-arrow").hidden = value;
  document.getElementById("button-spinner").hidden = !value;
}

function duration(seconds) {
  if (!Number.isFinite(seconds)) return "Unavailable";
  if (seconds < 60) return `${seconds.toFixed(1)} sec`;
  const rounded = Math.round(seconds);
  const minutes = Math.floor(rounded / 60);
  return `${minutes} min ${String(rounded % 60).padStart(2, "0")} sec`;
}

function showResult(data) {
  if (!Number.isFinite(data.ai_score) || data.ai_score < 0 || data.ai_score > 1) {
    throw new Error("The detector returned an invalid score. Please try again.");
  }
  const assessments = {
    likely_ai_generated: ["Likely AI-generated", "The audio shows patterns associated with the AI generators this model was trained to detect."],
    likely_human_created: ["Likely human-created", "The model found fewer of the AI patterns it recognizes. This does not rule out AI use."],
    uncertain: ["Uncertain", "The score falls in the review range. The detector cannot make a clear assessment of this track."]
  };
  if (!Object.hasOwn(assessments, data.assessment)) {
    throw new Error("The detector returned an unknown assessment. Please try again.");
  }
  const [label, description] = assessments[data.assessment];
  document.getElementById("result-file").textContent = data.filename || currentFile.name;
  document.getElementById("assessment-label").textContent = label;
  document.getElementById("assessment-description").textContent = description;
  document.getElementById("score-value").textContent = data.ai_score.toFixed(3);
  document.getElementById("score-fill").style.width = `${data.ai_score * 100}%`;
  document.getElementById("score-meter").setAttribute("aria-valuenow", String(data.ai_score));
  document.getElementById("score-meter").setAttribute("aria-valuetext", `${data.ai_score.toFixed(3)} out of 1. Uncalibrated model score.`);
  document.getElementById("analyzed-duration").textContent = duration(data.analyzed_duration_seconds);
  document.getElementById("processing-time").textContent = Number.isFinite(data.processing_time_ms)
    ? data.processing_time_ms < 1000
      ? `${Math.max(1, Math.round(data.processing_time_ms))} ms`
      : `${(data.processing_time_ms / 1000).toFixed(2)} sec`
    : "Unavailable";
  const warnings = Array.isArray(data.warnings) ? data.warnings.filter((item) => typeof item === "string") : [];
  if (data.truncated && !warnings.some((item) => /300|truncat|first/i.test(item))) {
    warnings.push("Only the first 300 seconds were analyzed. Later parts of this track were not screened.");
  }
  const warningList = document.getElementById("result-warnings");
  warningList.replaceChildren();
  for (const warning of warnings) {
    const item = document.createElement("li");
    item.textContent = warning;
    warningList.append(item);
  }
  warningList.hidden = warnings.length === 0;
  resultPanel.dataset.assessment = data.assessment;
  emptyResult.hidden = true;
  result.hidden = false;
  processStatus.textContent = "Analysis complete. You can choose another track.";
  document.getElementById("assessment-label").focus({ preventScroll: true });
  if (window.matchMedia("(max-width: 760px)").matches) {
    resultPanel.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth", block: "start" });
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!currentFile || busy) return;
  clearError();
  hideResult();
  setBusy(true);
  processStatus.textContent = "Uploading and analyzing audio. Keep this page open.";
  document.getElementById("empty-title").textContent = "Reading the audio signature…";
  document.getElementById("empty-description").textContent = "Processing time depends on the track and this server. No result is available yet.";
  const body = new FormData();
  body.append("file", currentFile);
  try {
    const response = await fetch("/api/v1/detect", { method: "POST", body });
    let data;
    try {
      data = await response.json();
    } catch {
      throw new Error(response.status === 413 ? "This file exceeds the server's upload limit." : "The server returned an unreadable response. Please try again.");
    }
    if (!response.ok) {
      const message = typeof data.detail === "string" ? data.detail : data.detail?.message;
      throw new Error(message || `Analysis failed (HTTP ${response.status}). Please try again.`);
    }
    showResult(data);
  } catch (error) {
    hideResult();
    processStatus.textContent = "";
    showError(error instanceof TypeError ? "Could not reach the detector. Check that the server is running and try again." : error.message || "Analysis failed. Please try again.");
  } finally {
    setBusy(false);
  }
});

async function checkHealth() {
  const status = document.getElementById("service-status");
  const label = document.getElementById("service-label");
  try {
    const response = await fetch("/health", { signal: AbortSignal.timeout(10000) });
    const health = await response.json();
    if (health.model_loaded && health.ffmpeg_available === false) {
      status.classList.add("unavailable");
      label.textContent = "Limited format support";
    } else if (response.ok && health.model_loaded) {
      status.classList.add("ready");
      label.textContent = "Detector ready";
    } else {
      status.classList.add("unavailable");
      label.textContent = "Detector unavailable";
    }
  } catch {
    status.classList.add("unavailable");
    label.textContent = "Connection unavailable";
  }
}

checkHealth();
