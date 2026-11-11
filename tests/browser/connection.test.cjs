// Run with: node --test tests/browser/connection.test.cjs
// No browser package is needed for these connection-state regression checks.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../../src/ai_song_detection/static/app.js"), "utf8");
const healthy = { app_id: "ai-song-detection", model_loaded: true, ffmpeg_available: true };
const tick = () => new Promise(setImmediate);

function element() {
  const classes = new Set();
  return {
    hidden: false, disabled: false, textContent: "", value: "", style: {}, dataset: {},
    listeners: new Map(), attributes: new Map(),
    classList: {
      add: (value) => classes.add(value), remove: (value) => classes.delete(value),
      contains: (value) => classes.has(value),
      toggle(value, enabled) {
        if (enabled) classes.add(value); else classes.delete(value);
      }
    },
    addEventListener(name, listener) { this.listeners.set(name, listener); },
    setAttribute(name, value) { this.attributes.set(name, value); },
    removeAttribute(name) { this.attributes.delete(name); },
    replaceChildren() {}, append() {}, focus() {}, scrollIntoView() {}
  };
}

function harness(fetch) {
  const elements = new Map();
  const get = (id) => {
    if (!elements.has(id)) elements.set(id, element());
    return elements.get(id);
  };
  get("detection-result").hidden = true;
  const context = vm.createContext({
    document: { getElementById: get, createElement: element, hidden: false, addEventListener() {} },
    window: { addEventListener() {}, matchMedia: () => ({ matches: false }) },
    fetch, AbortSignal, FormData, TypeError, setInterval() {}, console
  });
  vm.runInContext(source, context);
  return { get, run: (code) => vm.runInContext(code, context), context };
}

function response(body, ok = true, status = 200) {
  return { ok, status, json: async () => body };
}

test("initial readiness and application identity gate analysis", async () => {
  let resolveHealth;
  let requests = 0;
  const app = harness(() => {
    requests += 1;
    return new Promise((resolve) => { resolveHealth = resolve; });
  });
  app.run('selectFile({ name: "track.wav", size: 1000 })');
  assert.equal(app.get("analyze-button").disabled, true);
  const pending = app.run("checkHealth()");
  assert.equal(requests, 1, "pending checks must share one request");
  resolveHealth(response(healthy));
  await pending;
  assert.equal(app.get("analyze-button").disabled, false);
  assert.equal(app.get("service-status").classList.contains("ready"), true);
  app.context.fetch = async () => response({ ...healthy, app_id: "another-application" });
  await app.run("checkHealth()");
  assert.equal(app.get("analyze-button").disabled, true);
});

test("disconnect preserves the selected track and retry restores readiness", async () => {
  let connected = true;
  const app = harness(async () => {
    if (!connected) throw new TypeError("connection refused");
    return response(healthy);
  });
  await tick();
  app.run('selectFile({ name: "my track.mp3", size: 1000 })');
  connected = false;
  await app.run("checkHealth()");
  assert.equal(app.get("analyze-button").disabled, true);
  assert.equal(app.get("connection-notice").hidden, false);
  assert.equal(app.get("file-name").textContent, "my track.mp3");
  assert.equal(app.get("selected-file").hidden, false);
  assert.equal(app.get("service-status").classList.contains("ready"), false);
  connected = true;
  await app.get("retry-connection").listeners.get("click")();
  assert.equal(app.get("analyze-button").disabled, false);
  assert.equal(app.get("connection-notice").hidden, true);
  assert.equal(app.get("service-status").classList.contains("unavailable"), false);
});

test("health recovery cannot enable a busy upload and failed submission clears old results", async () => {
  let rejectDetection;
  const app = harness(async (url) => {
    if (url === "/health") return response(healthy);
    return new Promise((_, reject) => { rejectDetection = reject; });
  });
  await tick();
  app.run('selectFile({ name: "track.wav", size: 1000 })');
  app.get("detection-result").hidden = false;
  const submit = app.get("upload-form").listeners.get("submit")({ preventDefault() {} });
  await tick();
  await app.run("checkHealth()");
  assert.equal(app.get("analyze-button").disabled, true);
  assert.equal(app.get("audio-file").disabled, true);
  rejectDetection(new TypeError("connection reset"));
  await submit;
  assert.equal(app.get("detection-result").hidden, true);
  assert.equal(app.get("error-message").hidden, false);
  assert.equal(app.get("audio-file").disabled, false);
  assert.equal(app.get("analyze-button").disabled, true);
  await app.run("checkHealth()");
  assert.equal(app.get("analyze-button").disabled, false);
});

test("preflight failure sends no audio and keeps the selected track", async () => {
  let ready = true;
  let uploads = 0;
  const app = harness(async (url) => {
    if (url !== "/health") { uploads += 1; return response({}); }
    return response({ ...healthy, model_loaded: ready }, ready, ready ? 200 : 503);
  });
  await tick();
  app.run('selectFile({ name: "track.flac", size: 1000 })');
  ready = false;
  await app.get("upload-form").listeners.get("submit")({ preventDefault() {} });
  assert.equal(uploads, 0);
  assert.equal(app.get("selected-file").hidden, false);
  assert.equal(app.get("analyze-button").disabled, true);
  assert.equal(app.get("detection-result").hidden, true);
  assert.equal(app.get("process-status").textContent, "");
});
