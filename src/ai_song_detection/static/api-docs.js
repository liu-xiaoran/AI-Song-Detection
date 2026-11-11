"use strict";

const uploadForm = document.getElementById("docs-upload-form");
const uploadInput = document.getElementById("docs-audio-file");
const uploadButton = document.getElementById("docs-upload-button");
const healthButton = document.getElementById("docs-health-button");

function setOutput(prefix, status, body, isError = false) {
  const statusElement = document.getElementById(`docs-${prefix}-status`);
  statusElement.textContent = status;
  statusElement.dataset.error = String(isError);
  document.getElementById(`docs-${prefix}-output`).textContent = typeof body === "string" ? body : JSON.stringify(body, null, 2);
}

async function displayResponse(prefix, response) {
  let body;
  const text = await response.text();
  try {
    body = JSON.parse(text);
  } catch {
    body = text || "Empty response body.";
  }
  setOutput(prefix, `HTTP ${response.status} ${response.statusText}`, body, !response.ok);
}

uploadInput.addEventListener("change", () => {
  setOutput("detect", "Ready to send a new request.", "The JSON response will appear here.");
});

uploadForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = uploadInput.files[0];
  if (!file) return;
  if (file.size > 100 * 1024 * 1024) {
    setOutput("detect", "Request not sent.", "Choose a file of 100 MB or less.", true);
    return;
  }
  const body = new FormData();
  body.append("file", file);
  uploadButton.disabled = true;
  uploadInput.disabled = true;
  uploadForm.setAttribute("aria-busy", "true");
  uploadButton.textContent = "Sending request…";
  setOutput("detect", "Uploading and analyzing. Keep this page open.", "Waiting for the server response…");
  try {
    await displayResponse("detect", await fetch("/api/v1/detect", { method: "POST", body, signal: AbortSignal.timeout(180000) }));
  } catch {
    setOutput("detect", "Connection failed.", "Could not reach the server. Check that it is running and try again.", true);
  } finally {
    uploadButton.disabled = false;
    uploadInput.disabled = false;
    uploadForm.setAttribute("aria-busy", "false");
    uploadButton.textContent = "Send request";
  }
});

healthButton.addEventListener("click", async () => {
  healthButton.disabled = true;
  setOutput("health", "Checking service readiness…", "Waiting for the server response…");
  try {
    await displayResponse("health", await fetch("/health", { signal: AbortSignal.timeout(10000) }));
  } catch {
    setOutput("health", "Connection failed.", "Could not reach the server. Check that it is running and try again.", true);
  } finally {
    healthButton.disabled = false;
  }
});
