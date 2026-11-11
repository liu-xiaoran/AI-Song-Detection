// Run with: node --test tests/browser/connection.test.cjs
// Browser-independent workflow regression checks; native browser smoke covers rendering.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../../src/ai_song_detection/static/app.js"), "utf8");
const healthy = { app_id: "ai-song-detection", model_loaded: true, ffmpeg_available: true, instance_id: "instance-1" };
const tick = () => new Promise(setImmediate);
const report = (filename = "track.wav") => ({
  filename, ai_score: 0.81, assessment: "likely_ai_generated", analyzed_duration_seconds: 25,
  audio_duration_seconds: 180, analyzed_start_seconds: 20, analyzed_end_seconds: 45,
  requested_duration_seconds: 25, processing_time_ms: 120, report_id: "report-1",
  analyzed_at: "2026-11-11T08:00:00Z", input_sha256: "a".repeat(64), input_size_bytes: 1000,
  application_version: "0.3.0", model: { name: "detector", version: "1", sha256: "b".repeat(64), upstream_commit: "abc123" },
  decision_policy: { id: "screening", version: "1", human_below: 0.4, ai_above: 0.6, uncertain_inclusive: [0.4, 0.6], validated: false },
  upstream_binary_threshold: 0.5, warnings: []
});
function element(tagName = "div") {
  const classes = new Set();
  return {
    tagName, hidden: false, disabled: false, textContent: "", value: "", style: {}, dataset: {}, children: [],
    listeners: new Map(), attributes: new Map(),
    classList: {
      add: (value) => classes.add(value), remove: (value) => classes.delete(value), contains: (value) => classes.has(value),
      toggle(value, enabled) { if (enabled) classes.add(value); else classes.delete(value); }
    },
    addEventListener(name, listener) { this.listeners.set(name, listener); },
    setAttribute(name, value) { this.attributes.set(name, value); },
    removeAttribute(name) { this.attributes.delete(name); },
    replaceChildren(...items) { this.children = items; },
    append(...items) { this.children.push(...items); },
    click() { return this.listeners.get("click")?.(); }, focus() {}, scrollIntoView() {}
  };
}
function response(body, ok = true, status = 200) { return { ok, status, json: async () => body }; }
function harness(fetch = async () => response(healthy)) {
  const elements = new Map();
  const uploads = [];
  const timers = [];
  const copied = [];
  const get = (id) => { if (!elements.has(id)) elements.set(id, element()); return elements.get(id); };
  get("detection-result").hidden = true;
  get("start-seconds").value = "0";
  get("duration-seconds").value = "300";
  class FakeXHR {
    constructor() { this.upload = {}; }
    open(method, url) { this.method = method; this.url = url; }
    send(body) { this.body = body; uploads.push(this); }
    respond(body, status = 202) { this.status = status; this.responseText = JSON.stringify(body); this.onload(); }
  }
  const context = vm.createContext({
    document: { getElementById: get, createElement: element, hidden: false, addEventListener() {} },
    window: { addEventListener() {}, matchMedia: () => ({ matches: false }) },
    fetch, AbortSignal, XMLHttpRequest: FakeXHR, Blob,
    FormData: class { constructor() { this.fields = []; } append(...args) { this.fields.push(args); } },
    navigator: { clipboard: { writeText: async (value) => copied.push(value) } },
    URL: { createObjectURL: () => "blob:report", revokeObjectURL() {} },
    setTimeout(callback, milliseconds) { timers.push({ callback, milliseconds }); }, setInterval() {}, console
  });
  vm.runInContext(source, context);
  const app = { get, uploads, copied, run: (code) => vm.runInContext(code, context), context,
    submit: () => get("upload-form").listeners.get("submit")({ preventDefault() {} }),
    async timer(milliseconds = 500) {
      const index = timers.findIndex((timer) => timer.milliseconds === milliseconds);
      assert.notEqual(index, -1, `expected a ${milliseconds}ms timer`);
      timers.splice(index, 1)[0].callback();
      await tick();
    }
  };
  return app;
}

test("readiness and application identity gate uploads and share a pending health check", async () => {
  let resolveHealth;
  let requests = 0;
  const app = harness(() => { requests++; return new Promise((resolve) => { resolveHealth = resolve; }); });
  app.run('selectFile({ name: "track.wav", size: 1000 })');
  assert.equal(app.get("analyze-button").disabled, true);
  const pending = app.run("checkHealth()");
  assert.equal(requests, 1);
  resolveHealth(response(healthy));
  await pending;
  assert.equal(app.get("analyze-button").disabled, false);
  app.context.fetch = async () => response({ ...healthy, app_id: "another-application" });
  await app.run("checkHealth()");
  assert.equal(app.get("analyze-button").disabled, true);
  assert.equal(app.uploads.length, 0);
});

test("disconnect and failed preflight keep selected files without sending audio", async () => {
  let connected = true;
  const app = harness(async () => { if (!connected) throw new TypeError("refused"); return response(healthy); });
  await tick();
  app.run('selectFile({ name: "my track.mp3", size: 1000 })');
  connected = false;
  await app.submit();
  assert.equal(app.uploads.length, 0);
  assert.equal(app.get("selected-file").hidden, false);
  assert.equal(app.get("file-name").textContent, "my track.mp3");
  assert.equal(app.get("connection-notice").hidden, false);
  connected = true;
  await app.get("retry-connection").click();
  assert.equal(app.get("analyze-button").disabled, false);
  assert.equal(app.get("connection-notice").hidden, true);
});

test("multiple files run serially, capture window settings, and preserve completed reports", async () => {
  const app = harness();
  await tick();
  app.get("start-seconds").value = "20";
  app.get("duration-seconds").value = "25";
  app.run('addFiles([{ name: "first.wav", size: 1000 }, { name: "second.mp3", size: 2000 }])');
  const submitted = app.submit();
  await tick();
  assert.equal(app.uploads.length, 1);
  assert.match(app.uploads[0].url, /start_seconds=20&duration_seconds=25$/);
  assert.equal(app.get("audio-file").disabled, false, "adding files must remain available during analysis");
  app.get("start-seconds").value = "40";
  app.run('selectFile({ name: "third.wav", size: 1000 })');
  app.uploads[0].upload.onprogress({ lengthComputable: true, loaded: 43, total: 100 });
  assert.match(app.get("queue-list").children[0].children[0].children[1].textContent, /Uploading · 43%/);
  app.uploads[0].respond({ id: "job-1", status: "completed", stage: "complete", result: report("first.wav") });
  await tick();
  assert.equal(app.uploads.length, 2);
  assert.equal(app.get("detection-result").hidden, false);
  assert.equal(app.get("result-file").textContent, "first.wav");
  assert.equal(app.get("history-list").children.length, 1);
  assert.match(app.uploads[1].url, /start_seconds=20&duration_seconds=25$/);
  app.uploads[1].respond({ id: "job-2", status: "completed", stage: "complete", result: report("second.mp3") });
  await tick();
  assert.equal(app.uploads.length, 3);
  assert.match(app.uploads[2].url, /start_seconds=40&duration_seconds=25$/);
  app.uploads[2].respond({ id: "job-3", status: "completed", stage: "complete", result: report("third.wav") });
  await submitted;
  assert.equal(app.get("history-list").children.length, 3);
  app.get("history-list").children[0].children[1].children[0].click();
  assert.equal(app.get("result-file").textContent, "first.wav");
  assert.match(app.get("analyzed-coverage").textContent, /20.0 sec to 45.0 sec/);
  assert.match(app.get("report-policy").textContent, /not independently validated/);
});

test("cancellation waits for the backend terminal state before starting the next track", async () => {
  let state = "running";
  let cancelRequests = 0;
  const app = harness(async (url, options) => {
    if (url === "/health") return response(healthy);
    if (options.method === "POST") { cancelRequests++; state = "cancelling"; }
    return response({ id: "job-1", status: state, stage: "inference", result: null });
  });
  await tick();
  app.run('addFiles([{ name: "first.wav", size: 1000 }, { name: "second.wav", size: 1000 }])');
  const submitted = app.submit();
  await tick();
  app.uploads[0].respond({ id: "job-1", status: "running", stage: "inference" });
  await tick();
  app.get("queue-list").children[0].children[1].children[0].click();
  await app.timer();
  assert.equal(cancelRequests, 1);
  assert.equal(app.uploads.length, 1);
  assert.match(app.get("queue-list").children[0].children[0].children[1].textContent, /Cancelling/);
  state = "cancelled";
  await app.timer();
  assert.equal(app.uploads.length, 2);
  app.uploads[1].respond({ id: "job-2", status: "completed", stage: "complete", result: report("second.wav") });
  await submitted;
  assert.equal(app.run('tracks[0].status'), "cancelled");
});

test("cancelling an upload preserves its response and then cancels the accepted job", async () => {
  let cancelRequests = 0;
  const app = harness(async (url) => {
    if (url === "/health") return response(healthy);
    if (url.endsWith("/cancel")) cancelRequests++;
    return response({ id: "job-1", status: "cancelled", stage: "complete" });
  });
  await tick();
  app.run('selectFile({ name: "track.wav", size: 1000 })');
  const submitted = app.submit();
  await tick();
  app.get("queue-list").children[0].children[1].children[0].click();
  assert.equal(cancelRequests, 0);
  assert.match(app.get("queue-list").children[0].children[0].children[1].textContent, /waiting for upload response/);
  app.uploads[0].respond({ id: "job-1", status: "running", stage: "decoding" });
  await tick();
  await app.timer();
  await submitted;
  assert.equal(cancelRequests, 1);
  assert.equal(app.run('tracks[0].status'), "cancelled");
});

test("polling recovers without uploading accepted audio again", async () => {
  let calls = 0;
  const app = harness(async (url) => {
    if (url === "/health") return response(healthy);
    if (++calls === 1) throw new TypeError("reset");
    return response({ id: "job-1", status: "completed", stage: "complete", result: report() });
  });
  await tick();
  app.run('selectFile({ name: "track.wav", size: 1000 })');
  const submitted = app.submit();
  await tick();
  app.uploads[0].respond({ id: "job-1", status: "running", stage: "decoding" });
  await tick();
  await app.timer();
  assert.equal(app.uploads.length, 1);
  assert.match(app.get("process-status").textContent, /will not be uploaded twice/);
  await app.timer(1500);
  await app.timer();
  await submitted;
  assert.equal(app.uploads.length, 1);
  assert.equal(app.get("detection-result").hidden, false);
});

test("an ambiguous upload pauses all new uploads until a detector restart is observed", async () => {
  let instance = "instance-1";
  const app = harness(async () => response({ ...healthy, instance_id: instance }));
  await tick();
  app.run('addFiles([{ name: "first.wav", size: 1000 }, { name: "second.wav", size: 1000 }])');
  const submitted = app.submit();
  await tick();
  app.uploads[0].onerror();
  await submitted;
  assert.equal(app.uploads.length, 1);
  assert.equal(app.get("analyze-button").disabled, true);
  assert.match(app.get("process-status").textContent, /job state is unknown/);
  await app.run("checkHealth()");
  assert.equal(app.get("analyze-button").disabled, true);
  instance = "instance-2";
  await app.run("checkHealth()");
  assert.equal(app.get("analyze-button").disabled, false);
  assert.equal(app.uploads.length, 1, "recovery must not automatically resubmit audio");
});

test("failed tracks do not stop the queue and retry retains the failed report", async () => {
  const app = harness();
  await tick();
  app.run('addFiles([{ name: "bad.wav", size: 1000 }, { name: "good.wav", size: 1000 }])');
  const submitted = app.submit();
  await tick();
  app.uploads[0].respond({ detail: { message: "Could not decode audio" } }, 422);
  await tick();
  assert.equal(app.uploads.length, 2);
  app.uploads[1].respond({ id: "job-2", status: "completed", stage: "complete", result: report("good.wav") });
  await submitted;
  const failedRow = app.get("history-list").children[0];
  failedRow.children[1].children[1].click();
  assert.equal(app.get("history-list").children.length, 2);
  assert.equal(app.get("queue-list").children.length, 1);
  assert.equal(app.get("detection-result").hidden, false, "retry must retain the previous displayed report");
  assert.equal(app.run('tracks[0].error.message'), "Could not decode audio");
});

test("JSON includes provenance and CSV neutralizes malicious names and error messages", async () => {
  const app = harness();
  await tick();
  app.context.savedReport = report('=HYPERLINK("bad")\n曲目.wav');
  app.run('tracks.push({ id: 1, name: savedReport.filename, status: "completed", start: 20, duration: 25, size: 1000, result: savedReport }); selectReport(tracks[0])');
  await app.get("copy-json").click();
  const json = JSON.parse(app.copied[0]);
  assert.equal(json.input_sha256, "a".repeat(64));
  assert.equal(json.model.upstream_commit, "abc123");
  assert.equal(json.decision_policy.validated, false);
  await app.get("copy-csv").click();
  const csv = app.copied[1];
  assert.ok(csv.includes('"\'=HYPERLINK(""bad"")\n曲目.wav"'));
  assert.ok(csv.includes('"input_sha256"'));
  assert.ok(csv.includes('"policy_validated"'));
  assert.equal(app.run('csvCell("\t=1+1")'), '"\'\t=1+1"');
  assert.equal(app.run('csvCell("  @SUM(A1)")'), '"\'  @SUM(A1)"');
  assert.equal(app.run('csvCell("-10")'), '"\'-10"');
  app.run('tracks.push({ name: "bad.wav", status: "failed", start: 0, duration: 300, size: 100, error: { message: "+CMD" } })');
  assert.ok(app.run('reportsCSV(tracks)').includes('"\'+CMD"'));
});

test("clear queued and clear history preserve the active job", async () => {
  const app = harness();
  await tick();
  app.run('addFiles([{ name: "first.wav", size: 1000 }, { name: "second.wav", size: 1000 }])');
  const submitted = app.submit();
  await tick();
  app.get("clear-queued").click();
  app.get("clear-history").click();
  assert.equal(app.run("tracks.length"), 1);
  assert.equal(app.uploads.length, 1);
  app.uploads[0].respond({ id: "job-1", status: "completed", stage: "complete", result: report("first.wav") });
  await submitted;
  assert.equal(app.get("history-list").children.length, 1);
});

test("invalid window settings and invalid files do not discard valid queue entries", async () => {
  const app = harness();
  await tick();
  app.run('selectFile({ name: "valid.wav", size: 1000 })');
  app.get("duration-seconds").value = "9";
  app.run('selectFile({ name: "bad-window.wav", size: 1000 })');
  assert.equal(app.run("tracks.length"), 1);
  assert.match(app.get("error-message").textContent, /between 10 and 300/);
  app.get("duration-seconds").value = "300";
  app.run('addFiles([{ name: "empty.wav", size: 0 }, { name: "image.png", size: 100 }, { name: "more.wav", size: 1000 }])');
  assert.equal(app.run("tracks.length"), 2);
  assert.match(app.get("error-message").textContent, /empty/);
  assert.equal(app.get("detection-result").hidden, true);
});
