import {
  FIELDS,
  bytes,
  changeParam,
  chooseModel,
  createScope,
  serialQueue,
  savedPreset,
  modelTransition,
} from "./core.js?v=m3.3";
import { renderIcons, icon } from "./icons.js";
import { createViewer } from "./viewer.js?v=m3.4";
import { createPainting } from "./painting.js";

const $ = (id) => document.getElementById(id);
const scope = createScope(),
  queue = serialQueue();
const state = {
  id: null,
  project: null,
  params: null,
  editor: null,
  models: [],
  defaults: null,
  projects: [],
  ready: false,
  view: "3d",
  panel: "adjust",
  layer: "mask",
  tool: "remove",
  brushRadius: 6,
  brushStrength: 100,
  flattenLevel: 0.5,
  compare: false,
  saving: false,
  segmentation: null,
  exporting: null,
  lastExport: null,
};
let paramTimer = null,
  paramVersion = 0,
  queued = 0,
  previewSequence = 0,
  previewTimer = null,
  planSequence = 0,
  imageURL = null,
  librarySequence = 0,
  retryAction = null,
  toastAction = null,
  confirmResolve = null;
const viewer = createViewer($("viewer"));
const painting = createPainting({
  canvas: $("editor-canvas"),
  cursor: $("brush-cursor"),
  getState: () => state,
  submit: (stroke) =>
    mutate("/editor/stroke", stroke, "Saving correction").catch(() => {}),
  selectionReady: () => {
    $("isolate-selection").hidden = false;
    message("Selection ready. Choose Isolate selected area.");
  },
});
renderIcons();
$("brand-mark")?.replaceChildren();
document.querySelector(".brand-mark").innerHTML = icon("layers");
for (const button of document.querySelectorAll(".navigation button"))
  if (!button.hasAttribute("aria-label"))
    button.setAttribute(
      "aria-label",
      button.textContent.trim().replace(/\s+/g, " ") || button.title,
    );

async function api(path, options = {}) {
  const { json, ...rest } = options;
  if (json !== undefined) {
    rest.body = JSON.stringify(json);
    rest.headers = { ...rest.headers, "Content-Type": "application/json" };
  }
  const response = await fetch(path, rest);
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const data = await response.json();
      detail = Array.isArray(data.detail)
        ? data.detail.map((v) => v.msg).join("; ")
        : data.detail || data.error || detail;
    } catch {}
    const error = new Error(detail);
    error.status = response.status;
    throw error;
  }
  return response;
}
const json = async (path, options) => await (await api(path, options)).json();
const session = (path) => `/api/sessions/${state.id}${path}`;
function message(value) {
  $("editor-message").textContent = value;
}
function fail(error, retry = null, retryLabel = "Retry") {
  $("error-text").textContent = error.message || String(error);
  $("error-banner").hidden = false;
  retryAction = retry;
  $("retry-action").hidden = !retry;
  if (/history|journal|gestures|size limit/i.test(error.message || "")) {
    retryAction = () => openHistory();
    $("retry-action").textContent = "Manage history";
    $("retry-action").hidden = false;
  } else $("retry-action").textContent = retryLabel;
}
function clearError() {
  $("error-banner").hidden = true;
  retryAction = null;
}
function toast(text, action = null, label = "Undo") {
  $("toast-text").textContent = text;
  toastAction = action;
  $("toast-action").hidden = !action;
  $("toast-action").textContent = label;
  $("toast").hidden = false;
}
function updateSaving() {
  state.saving = queued > 0 || paramTimer !== null;
  $("save-state").textContent = state.id
    ? state.saving
      ? "Saving changes…"
      : "Saved on this computer"
    : "Everything stays on your computer";
  $("inspector-status").textContent = state.saving
    ? "Saving…"
    : "Changes save automatically";
}
function modal(id) {
  $(id).showModal();
}
async function confirm(title, text, label = "Continue") {
  if (confirmResolve) confirmResolve(false);
  $("confirm-title").textContent = title;
  $("confirm-message").textContent = text;
  $("confirm-accept").textContent = label;
  modal("confirm-dialog");
  return new Promise((resolve) => {
    confirmResolve = resolve;
  });
}
function finishConfirm(value) {
  $("confirm-dialog").close();
  if (confirmResolve) {
    confirmResolve(value);
    confirmResolve = null;
  }
}
$("confirm-cancel").onclick = () => finishConfirm(false);
$("confirm-accept").onclick = () => finishConfirm(true);
$("confirm-dialog").addEventListener("cancel", (event) => {
  event.preventDefault();
  finishConfirm(false);
});
for (const button of document.querySelectorAll("[data-close]"))
  button.onclick = () => button.closest("dialog").close();
$("dismiss-error").onclick = clearError;
$("toast-close").onclick = () => {
  $("toast").hidden = true;
};
$("retry-action").onclick = () => {
  const action = retryAction;
  queue.clearError();
  clearError();
  action?.();
};
$("toast-action").onclick = async () => {
  const action = toastAction;
  $("toast").hidden = true;
  try {
    await action?.();
  } catch (e) {
    fail(e);
  }
};

function theme(value) {
  const dark = value !== "light";
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  try {
    localStorage.setItem("relief-theme", dark ? "dark" : "light");
  } catch {}
  viewer.theme(dark);
  $("theme-label").textContent = dark ? "Dark appearance" : "Light appearance";
  $("theme-toggle").setAttribute(
    "aria-label",
    `Switch to ${dark ? "light" : "dark"} appearance`,
  );
  $("theme-toggle").querySelector("[data-icon]").innerHTML = icon(
    dark ? "moon" : "sun",
  );
  for (const b of document.querySelectorAll("[data-theme-choice]"))
    b.setAttribute(
      "aria-pressed",
      String(b.dataset.themeChoice === (dark ? "dark" : "light")),
    );
}
$("theme-toggle").onclick = () =>
  theme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
for (const b of document.querySelectorAll("[data-theme-choice]"))
  b.onclick = () => theme(b.dataset.themeChoice);
theme(document.documentElement.dataset.theme);
$("nav-toggle").onclick = () =>
  $("app-shell").classList.toggle("nav-collapsed");
$("inspector-toggle").onclick = () =>
  $("app-shell").classList.toggle("inspector-collapsed");

function buildField(field, target) {
  const block = document.createElement("div");
  block.className = "field";
  block.dataset.field = field.id;
  const description = `${field.id}-description`;
  if (field.type === "checkbox")
    block.innerHTML = `<label class="check-row"><input type="checkbox" id="${field.id}" aria-describedby="${description}" />${field.label}</label><p id="${description}" class="hint" hidden>${field.tip}</p>`;
  else if (field.type === "select")
    block.innerHTML = `<label for="${field.id}">${field.label}</label><select id="${field.id}" aria-describedby="${description}">${field.options.map((v) => `<option value="${v}">${field.id === "resolution" ? { 512: "Standard · 512", 1024: "High · 1024", 2048: "Maximum · 2048" }[v] : v.toUpperCase()}</option>`).join("")}</select><p id="${description}" class="hint">${field.tip}</p>`;
  else
    block.innerHTML = `<div class="field-head"><label for="${field.id}-number">${field.label}<button type="button" class="info-button" title="${field.tip}" aria-label="Explain ${field.label}" aria-expanded="false">?</button></label><div class="number-unit"><input type="number" id="${field.id}-number" min="${field.min}" max="${field.max}" step="any" aria-label="${field.label} value" aria-describedby="${description}" /><span>${field.unit || ""}</span></div></div><input type="range" id="${field.id}" min="${field.min}" max="${field.max}" step="${field.step}" aria-label="${field.label} slider" aria-describedby="${description}" /><p id="${description}" class="hint" hidden>${field.tip}</p>`;
  target.append(block);
  const tip = block.querySelector(".info-button");
  if (tip)
    tip.onclick = (event) => {
      event.preventDefault();
      const p = $(description);
      p.hidden = !p.hidden;
      tip.setAttribute("aria-expanded", String(!p.hidden));
    };
  const apply = (value) => {
    try {
      state.params = changeParam(state.params, field.id, value);
      paramVersion++;
      syncParams();
      invalidateExport();
      scheduleParams();
    } catch (e) {
      fail(e);
      syncParams();
    }
  };
  const input = $(field.id);
  if (field.type === "checkbox") input.onchange = () => apply(input.checked);
  else if (field.type === "select") input.onchange = () => apply(input.value);
  else {
    input.oninput = () => apply(input.value);
    const numeric = $(`${field.id}-number`);
    numeric.onchange = () => apply(numeric.value);
  }
}
for (const field of FIELDS.filter((f) => f.type !== "model"))
  buildField(
    field,
    $(field.group === "export" ? "export-fields" : `${field.group}-fields`),
  );
for (const field of [
  {
    id: "sculpt_strength",
    label: "Sculptural smoothing",
    min: 0,
    max: 1,
    step: 0.05,
    tip: "Optional multiscale smoothing of narrow ridges. It cannot reconstruct missing anatomy.",
  },
  {
    id: "texture_guard",
    label: "Restrain photo grooves",
    min: 0,
    max: 1,
    step: 0.05,
    tip: "Limits strong brightness-derived texture such as shadows and reflections.",
  },
]) {
  const div = document.createElement("div");
  div.className = "field";
  div.innerHTML = `<div class="field-head"><label for="${field.id}">${field.label}</label><output id="${field.id}-value">0</output></div><input type="range" id="${field.id}" min="0" max="1" step=".05" aria-label="${field.label}" /><p class="hint">${field.tip}</p>`;
  $("quality-fields").append(div);
  $(field.id).onchange = () =>
    mutate(
      "/editor",
      { [field.id]: Number($(field.id).value) },
      "Saving surface settings",
      "PUT",
    ).catch(() => {});
}
for (const container of document.querySelectorAll("[data-brush-controls]")) {
  for (const [key, label, min, max, step] of [
    ["brushRadius", "Brush radius", 0.1, 50, 0.1],
    ["brushStrength", "Brush strength", 1, 100, 1],
  ]) {
    const div = document.createElement("div");
    div.className = "field";
    div.innerHTML = `<div class="field-head"><label>${label} <span class="muted">%</span></label><div class="number-unit"><input data-brush-number="${key}" type="number" min="${min}" max="${max}" step="any" aria-label="${label} value" /></div></div><input type="range" data-brush="${key}" min="${min}" max="${max}" step="${step}" aria-label="${label}" />`;
    container.append(div);
    const change = (value) => {
      const number = Number(value);
      if (!Number.isFinite(number)) return;
      state[key] = Math.max(min, Math.min(max, number));
      syncBrush();
    };
    div.querySelector("[data-brush]").oninput = (e) => change(e.target.value);
    div.querySelector("[data-brush-number]").onchange = (e) =>
      change(e.target.value);
  }
}
const tools = {
  mask: [
    ["keep", "Keep"],
    ["remove", "Remove"],
    ["rectangle", "Select area"],
  ],
  depth: [
    ["raise", "Raise"],
    ["lower", "Lower"],
    ["smooth", "Smooth"],
    ["flatten", "Flatten"],
  ],
};
function toolButton(tool, label, inline = false) {
  const button = document.createElement("button");
  button.type = "button";
  button.dataset.tool = tool;
  button.setAttribute(
    "aria-label",
    `${label} ${tools.mask.some((v) => v[0] === tool) ? "subject" : "depth"}`,
  );
  button.innerHTML = icon(tool) + `<span>${label}</span>`;
  button.title = label;
  button.onclick = () => setTool(tool);
  return button;
}
for (const layer of ["mask", "depth"])
  for (const [tool, label] of tools[layer])
    $(layer === "mask" ? "mask-tools" : "depth-tools").append(
      toolButton(tool, label),
    );
function syncTools() {
  $("inline-tools").replaceChildren(
    ...tools[state.layer].map(([t, l]) => toolButton(t, l, true)),
  );
  for (const button of document.querySelectorAll("[data-tool]")) {
    button.setAttribute(
      "aria-pressed",
      String(button.dataset.tool === state.tool),
    );
    button.disabled = !state.ready || state.compare || state.saving;
  }
  for (const b of document.querySelectorAll("[data-layer]"))
    b.setAttribute("aria-pressed", String(b.dataset.layer === state.layer));
  $("flatten-control").hidden = state.tool !== "flatten";
  const channel = state.layer,
    undo = Boolean(state.editor?.[channel + "_undo"]),
    redo = Boolean(state.editor?.[channel + "_redo"]);
  $("editor-undo").disabled = !undo || state.saving || state.compare;
  $("editor-redo").disabled = !redo || state.saving || state.compare;
  $("editor-undo").setAttribute("aria-label", `Undo ${channel}`);
  $("editor-redo").setAttribute("aria-label", `Redo ${channel}`);
  $("sculpt-undo").disabled =
    !state.editor?.depth_undo || state.saving || state.compare;
  $("sculpt-redo").disabled =
    !state.editor?.depth_redo || state.saving || state.compare;
}
function syncBrush() {
  for (const input of document.querySelectorAll(
    "[data-brush],[data-brush-number]",
  ))
    input.value = state[input.dataset.brush || input.dataset.brushNumber];
  $("flatten-level").value = state.flattenLevel;
}
syncBrush();
function syncParams() {
  if (!state.params) return;
  for (const field of FIELDS) {
    const input = $(field.id);
    if (!input) continue;
    input.disabled =
      state.compare ||
      (field.id === "depth_model" && (state.saving || !state.ready));
    if (field.type === "checkbox") input.checked = state.params[field.id];
    else input.value = state.params[field.id];
    const number = $(`${field.id}-number`);
    if (number) {
      if (document.activeElement !== number)
        number.value = state.params[field.id];
      number.disabled = state.compare;
    }
  }
  $("export-quality").value = state.params.resolution;
  $("export-quality").disabled = state.compare;
  const meta = state.project?.image;
  if (meta?.w && meta?.h) {
    const width =
        state.params.model_width_mm + 2 * state.params.border_frame_mm,
      height =
        (state.params.model_width_mm * meta.h) / meta.w +
        2 * state.params.border_frame_mm,
      total = state.params.base_thickness_mm + state.params.relief_height_mm;
    const text = `${width.toFixed(1)} × ${height.toFixed(1)} × ${total.toFixed(1)} mm`;
    $("physical-size").textContent = text;
    $("export-dimensions").textContent = text;
  }
  const model = state.models.find(
    (m) => m.model_id === state.params.depth_model,
  );
  $("model-status").textContent = model?.setup_reason || "";
  if (state.editor)
    $("preset").value = savedPreset(state.project, state.params, state.editor);
}
function syncEditor() {
  const editor = state.editor;
  if (!editor) return;
  $("mask-enabled").checked = editor.mask_enabled;
  $("mask-feather").value = editor.mask_feather_mm;
  $("mask-transition").value = editor.mask_transition_mm;
  for (const id of ["sculpt_strength", "texture_guard"]) {
    $(id).value = editor[id];
    $(`${id}-value`).textContent = Number(editor[id]).toFixed(2);
  }
  const list = $("editor-source"),
    aiOption = new Option(
      editor.ai_available === false
        ? "Original AI prediction · unavailable"
        : "Original AI prediction",
      "ai",
    );
  aiOption.disabled = editor.ai_available === false;
  list.replaceChildren(aiOption);
  for (const item of editor.imports || [])
    list.append(new Option(item.filename, `imported:${item.id}`));
  list.value =
    editor.depth_source === "ai" ? "ai" : `imported:${editor.imported.id}`;
  $("depth-export-source").querySelector('[value="ai"]').disabled =
    editor.ai_available === false;
  $("depth-export-source").querySelector('[value="imported"]').disabled =
    !editor.imported;
  if ($("depth-export-source").selectedOptions[0]?.disabled)
    $("depth-export-source").value = "working";
  for (const id of ["depth-export-png", "depth-export-npy"])
    $(id).disabled = !state.ready;
  $("depth-source-summary").textContent =
    editor.depth_source === "ai"
      ? editor.ai_available === false
        ? "Import a depth map"
        : "Original AI"
      : editor.imported?.filename || "Imported";
  for (const id of [
    "mask-enabled",
    "mask-feather",
    "mask-transition",
    "sculpt_strength",
    "texture_guard",
    "preset",
    "editor-source",
    "remove-background",
    "quick-remove-background",
    "reset-mask",
    "reset-depth",
    "restore-ai",
    "create-checkpoint",
    "reset-adjustments",
    "depth-file",
    "depth-white-far",
    "depth-stretch",
  ])
    $(id).disabled =
      state.saving ||
      state.compare ||
      (!state.ready &&
        ![
          "editor-source",
          "depth-file",
          "depth-white-far",
          "depth-stretch",
        ].includes(id));
  $("undo-preset").hidden = !state.project?.preset_undo;
  $("undo-preset").disabled = state.compare || state.saving;
  syncTools();
  syncParams();
}
function invalidateExport() {
  state.lastExport = null;
  $("download-mesh").hidden = true;
  $("export-result").textContent = "";
}
function syncProject() {
  $("inspector").inert = !state.params;
  $("project-title").textContent = state.project?.name || "New project";
  $("project-title").disabled = !state.id;
  $("welcome").hidden = Boolean(state.id);
  $("workspace").hidden = !state.id;
  $("inspector").hidden = !state.id;
  $("open-export").disabled = !state.ready || !state.id;
  $("compare-original").disabled =
    !state.ready || state.editor?.ai_available === false;
  $("compare-original").setAttribute("aria-pressed", String(state.compare));
  $("comparison-note").hidden = !state.compare;
  $("export-comparison-note").hidden = !state.compare;
  $("export-build").disabled =
    !state.ready ||
    state.compare ||
    Boolean(state.exporting) ||
    !state.plan?.allowed;
  $("preset").disabled = !state.params || state.compare || state.saving;
  updateSaving();
  syncParams();
  syncEditor();
}

async function action(fn, label = "Saving changes") {
  if (state.compare) {
    const error = new Error(
      "Original AI comparison is read-only. Return to edited before making changes.",
    );
    fail(error);
    throw error;
  }
  const token = scope.capture();
  queued++;
  updateSaving();
  syncTools();
  message(label);
  return queue.run(async () => {
    if (!scope.current(token)) {
      queued--;
      updateSaving();
      return;
    }
    try {
      const value = await fn(token);
      if (!scope.current(token)) return;
      message("Saved");
      return value;
    } catch (error) {
      if (scope.current(token)) {
        if (error.status === 409) {
          try {
            state.editor = await json(session("/editor"));
            syncEditor();
          } catch {}
          fail(error, () => reloadProject());
        } else fail(error, () => reloadProject());
      }
      throw error;
    } finally {
      queued--;
      updateSaving();
      syncTools();
      syncEditor();
    }
  });
}
async function mutate(path, body, label = "Saving changes", method = "POST") {
  return action(async (token) => {
    const editor = await json(`/api/sessions/${token.id}${path}`, {
      method,
      json: { ...body, expected_revision: state.editor.revision },
    });
    if (!scope.current(token)) return;
    state.editor = editor;
    invalidateExport();
    syncEditor();
    schedulePreview(0);
    planExport();
    refreshLibrary();
    if (editor.segmentation)
      toast(`${editor.segmentation.method}. ${editor.segmentation.note}`);
    return editor;
  }, label);
}
function scheduleParams() {
  clearTimeout(paramTimer);
  paramTimer = setTimeout(() => {
    paramTimer = null;
    saveParams().catch(() => {});
  }, 300);
  updateSaving();
}
async function saveParams() {
  if (!state.id || !state.params) return;
  clearTimeout(paramTimer);
  paramTimer = null;
  const snapshot = { ...state.params },
    version = paramVersion;
  return action(async (token) => {
    const saved = await json(`/api/sessions/${token.id}/params`, {
      method: "PUT",
      json: snapshot,
    });
    if (!scope.current(token)) return;
    if (version === paramVersion) state.params = saved;
    syncParams();
    invalidateExport();
    const project = await json(`/api/projects/${token.id}`);
    if (!scope.current(token)) return;
    state.project = project;
    const editor = await json(`/api/sessions/${token.id}/editor`);
    if (!scope.current(token)) return;
    state.editor = editor;
    syncEditor();
    if (
      snapshot.depth_model !== state.readyModel &&
      state.editor?.depth_source !== "imported"
    ) {
      state.ready = false;
      waitForDepth(token).catch((e) => fail(e));
    } else schedulePreview();
    planExport();
    refreshLibrary();
  });
}
async function flush() {
  if (paramTimer !== null) await saveParams();
  await queue.flush();
}
async function reloadProject() {
  const id = state.id;
  queue.clearError();
  clearTimeout(paramTimer);
  paramTimer = null;
  await queue.settled();
  await openProject(id, true);
  clearError();
}

async function refreshLibrary() {
  const serial = ++librarySequence;
  try {
    const data = await json("/api/projects");
    if (serial !== librarySequence) return;
    state.projects = data.projects;
    renderLibrary();
  } catch (e) {
    fail(e, refreshLibrary);
  }
}
function modified(iso) {
  const date = new Date(iso),
    days = Math.floor((Date.now() - date) / 86400000);
  return days === 0
    ? "Today"
    : days === 1
      ? "Yesterday"
      : date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
function renderLibrary() {
  $("project-count").textContent = state.projects.length;
  $("no-projects").hidden = state.projects.length > 0;
  $("recent-projects").replaceChildren();
  $("library-projects").replaceChildren();
  const query = $("project-search").value.toLowerCase();
  for (const project of state.projects) {
    const recent = document.createElement("button");
    recent.className =
      "recent-project" + (state.id === project.id ? " active" : "");
    recent.title = project.name;
    recent.setAttribute("aria-label", `Open ${project.name}`);
    const thumb = document.createElement("img");
    thumb.className = "project-thumb";
    thumb.src = project.thumbnail;
    thumb.alt = "";
    thumb.loading = "lazy";
    thumb.onerror = () => {
      thumb.hidden = true;
    };
    const text = document.createElement("span"),
      name = document.createElement("span"),
      when = document.createElement("span");
    name.className = "project-name";
    name.textContent = project.name;
    when.className = "project-modified";
    when.textContent = project.issues.length
      ? "Needs attention"
      : modified(project.updated_at);
    text.append(name, when);
    recent.append(thumb, text);
    recent.onclick = () =>
      openProject(project.id).catch((e) => fail(e, () => reloadProject()));
    $("recent-projects").append(recent);
    if (!project.name.toLowerCase().includes(query)) continue;
    const card = document.createElement("article");
    card.className = "library-project";
    const open = recent.cloneNode(true);
    open.className = "";
    open.onclick = () => {
      openProject(project.id)
        .then(() => $("library-dialog").close())
        .catch((e) => fail(e));
    };
    const more = document.createElement("button");
    more.className = "icon-button";
    more.innerHTML = icon("more");
    more.setAttribute("aria-label", `Manage ${project.name}`);
    more.onclick = () => {
      openProject(project.id)
        .then(() => {
          $("library-dialog").close();
          openProjectSettings();
        })
        .catch((e) => fail(e));
    };
    card.append(open, more);
    $("library-projects").append(card);
  }
  if (!state.projects.length) {
    const p = document.createElement("p");
    p.className = "muted";
    p.textContent = "Upload a photo to create your first project.";
    $("library-projects").append(p);
  }
}
$("project-search").oninput = renderLibrary;
$("open-library").onclick = () => {
  refreshLibrary();
  refreshDeleted();
  modal("library-dialog");
};
async function refreshDeleted() {
  try {
    const result = await json("/api/projects/deleted");
    $("deleted-projects").hidden = !result.projects.length;
    $("deleted-project-list").replaceChildren();
    for (const project of result.projects) {
      const row = document.createElement("div");
      row.className = "checkpoint-row";
      const label = document.createElement("span");
      label.textContent = project.name;
      const button = document.createElement("button");
      button.className = "button";
      button.textContent = "Restore";
      button.setAttribute("aria-label", `Restore ${project.name}`);
      button.onclick = async () => {
        try {
          await json(`/api/projects/${project.id}/restore`, { method: "POST" });
          await refreshLibrary();
          await refreshDeleted();
          toast("Project restored.");
        } catch (e) {
          fail(e);
        }
      };
      row.append(label, button);
      $("deleted-project-list").append(row);
    }
  } catch (e) {
    fail(e);
  }
}
function setPanel(panel) {
  state.panel = panel;
  for (const button of document.querySelectorAll("[data-panel]"))
    button.setAttribute(
      "aria-selected",
      String(button.dataset.panel === panel),
    );
  for (const section of document.querySelectorAll("[data-panel-content]"))
    section.hidden = section.dataset.panelContent !== panel;
}
for (const button of document.querySelectorAll("[data-panel]"))
  button.onclick = () => setPanel(button.dataset.panel);
function setView(view) {
  state.view = view;
  previewSequence++;
  $("preview-busy").hidden = true;
  for (const button of document.querySelectorAll("[data-view]"))
    button.setAttribute("aria-selected", String(button.dataset.view === view));
  $("viewer").hidden = view !== "3d";
  $("image-pane").hidden = !["photo", "depth"].includes(view);
  $("paint-pane").hidden = view !== "edit";
  $("edit-toolbar").hidden = view !== "edit";
  $("camera-tools").hidden = view !== "3d";
  viewer.visible(view === "3d" && state.ready);
  $("view-note").textContent =
    view === "3d"
      ? "Drag to rotate · scroll to zoom · right-drag to pan"
      : view === "edit"
        ? `${state.layer === "mask" ? "Editing subject mask" : "Editing relief depth"} · Ctrl/Cmd Z to undo`
        : view === "photo"
          ? "Original photograph"
          : "White is higher · black is lower";
  schedulePreview(0);
  syncTools();
}
for (const button of document.querySelectorAll("[data-view]"))
  button.onclick = () => setView(button.dataset.view);
function setTool(tool) {
  state.tool = tool;
  state.layer = tools.mask.some((t) => t[0] === tool) ? "mask" : "depth";
  state.brushStrength =
    state.layer === "mask"
      ? 100
      : ["smooth", "flatten"].includes(tool)
        ? 60
        : 6;
  setPanel(state.layer === "mask" ? "background" : "sculpt");
  setView("edit");
  syncBrush();
  syncTools();
}
for (const button of document.querySelectorAll("[data-layer]"))
  button.onclick = () =>
    setTool(button.dataset.layer === "mask" ? "remove" : "raise");
async function compare(value) {
  try {
    await flush();
  } catch (error) {
    fail(error, () => reloadProject());
    return;
  }
  state.compare = value;
  painting.cancel();
  if (value && state.view === "edit") setView("3d");
  syncProject();
  schedulePreview(0);
  planExport();
}
$("compare-original").onclick = () => compare(!state.compare);
$("return-edited").onclick = () => compare(false);
$("export-return-edited").onclick = () => compare(false);
function schedulePreview(delay = 220) {
  clearTimeout(previewTimer);
  if (state.id && state.ready && ["3d", "depth"].includes(state.view)) {
    $("preview-busy").hidden = false;
    $("preview-busy-label").textContent = state.compare
      ? "Loading original AI"
      : "Updating relief";
  }
  previewTimer = setTimeout(
    () =>
      refreshPreview().catch((e) => {
        fail(e, () => schedulePreview(0));
      }),
    delay,
  );
}
async function refreshPreview() {
  if (!state.id || !state.ready) return;
  const token = scope.capture(),
    sequence = ++previewSequence,
    view = state.view;
  if (view === "photo") {
    $("preview-image").src = `/api/sessions/${token.id}/source`;
    $("preview-image").alt = "Original photograph";
    return;
  }
  if (view === "edit") {
    await painting.render();
    return;
  }
  $("preview-busy").hidden = false;
  $("preview-busy-label").textContent = state.compare
    ? "Loading original AI"
    : "Updating relief";
  try {
    if (view === "3d") {
      const response = await api(
        `/api/sessions/${token.id}/preview/mesh?original=${state.compare}`,
        { method: "POST", json: state.params },
      );
      const buffer = await response.arrayBuffer();
      if (
        !scope.current(token) ||
        sequence !== previewSequence ||
        state.view !== view
      )
        return;
      await viewer.load(buffer);
      viewer.visible(true);
    } else {
      const response = await api(
        `/api/sessions/${token.id}/preview/heightmap?grayscale=true&original=${state.compare}`,
      );
      const blob = await response.blob();
      if (
        !scope.current(token) ||
        sequence !== previewSequence ||
        state.view !== view
      )
        return;
      if (imageURL) URL.revokeObjectURL(imageURL);
      imageURL = URL.createObjectURL(blob);
      $("preview-image").src = imageURL;
      $("preview-image").alt = state.compare
        ? "Original AI shaped depth"
        : "Edited relief heightmap";
    }
  } finally {
    if (scope.current(token) && sequence === previewSequence)
      $("preview-busy").hidden = true;
  }
}
function processing(title, detail, retry = false) {
  $("canvas-message").hidden = false;
  $("canvas-message-title").textContent = title;
  $("canvas-message-detail").textContent = detail;
  $("canvas-message").querySelector(".spinner").hidden = retry;
  $("generation-retry").hidden = !retry;
  $("generation-retry").textContent = chooseModel(
    state.models,
    state.defaultModel,
  )
    ? "Retry generation"
    : "Import a depth map";
}
async function waitForDepth(token, fresh = false) {
  processing(
    "Estimating depth",
    "Processing on this computer. This first step can take a little while.",
  );
  while (scope.current(token)) {
    const status = await json(`/api/sessions/${token.id}/status`);
    if (!scope.current(token)) return;
    if (status.status === "error") {
      processing(
        "Depth estimation paused",
        status.error ||
          "The model could not finish. Retry, or import a depth map.",
        true,
      );
      state.ready = false;
      syncProject();
      return;
    }
    if (
      status.status === "ready" &&
      status.model_id === state.params.depth_model
    ) {
      state.ready = true;
      state.readyModel = state.params.depth_model;
      if (
        fresh &&
        state.segmentation?.source_alpha &&
        state.editor.mask_operations === 0
      ) {
        const editor = await json(
          `/api/sessions/${token.id}/editor/automatic-mask`,
          {
            method: "POST",
            json: { method: "alpha", expected_revision: state.editor.revision },
          },
        );
        if (!scope.current(token)) return;
        state.editor = editor;
      }
      $("canvas-message").hidden = true;
      syncProject();
      schedulePreview(0);
      planExport();
      refreshLibrary();
      return;
    }
    if (status.status === "created") {
      processing(
        "This project needs a depth source",
        "Import a depth map, or complete local model setup before generating.",
        true,
      );
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 650));
  }
}
async function openProject(id, reload = false, fresh = false) {
  if (!reload) await flush();
  const token = scope.enter(id);
  clearError();
  state.id = id;
  state.ready = false;
  state.compare = false;
  state.project = null;
  state.editor = null;
  state.params = null;
  state.plan = null;
  state.lastExport = null;
  state.readyModel = null;
  paramVersion++;
  previewSequence++;
  clearTimeout(previewTimer);
  painting.clear();
  viewer.clear();
  $("preview-image").removeAttribute("src");
  $("download-mesh").hidden = true;
  processing("Opening project", "Reading saved work from this computer.");
  syncProject();
  const project = await json(`/api/projects/${id}`).catch((e) => {
    if (scope.current(token)) throw e;
    return null;
  });
  if (!scope.current(token)) return;
  state.project = project;
  if (project.issues.length) {
    syncProject();
    processing("This project needs attention", project.issues.join(" "), true);
    fail(new Error(project.issues.join(" ")), () => repairProject(id));
    $("retry-action").textContent = "Repair project";
    return;
  }
  const [params, editor, segmentation] = await Promise.all([
    json(`/api/sessions/${id}/params`),
    json(`/api/sessions/${id}/editor`),
    json(`/api/sessions/${id}/segmentation`),
  ]);
  if (!scope.current(token)) return;
  Object.assign(state, { params, editor, segmentation });
  try {
    localStorage.setItem("p2r_session_id", id);
  } catch {}
  history.replaceState(null, "", `?session=${id}`);
  setupSegmentation();
  syncProject();
  setPanel("adjust");
  setView("3d");
  renderLibrary();
  if (editor.depth_source === "imported") {
    state.ready = true;
    state.readyModel = params.depth_model;
    $("canvas-message").hidden = true;
    syncProject();
    schedulePreview(0);
    planExport();
  } else if (project.interrupted) {
    processing(
      "Previous processing was interrupted",
      "Your saved image and corrections are safe. Retry generation to continue.",
      true,
    );
  } else
    waitForDepth(token, fresh).catch((e) => {
      if (scope.current(token)) {
        fail(e, () => retryGeneration());
        processing("Could not finish", e.message, true);
      }
    });
  if (innerWidth <= 800) $("app-shell").classList.add("inspector-collapsed");
}
async function newProject() {
  try {
    await flush();
    scope.enter(null);
    state.id = null;
    state.project = null;
    state.params = null;
    state.editor = null;
    state.ready = false;
    state.compare = false;
    viewer.clear();
    painting.clear();
    previewSequence++;
    clearTimeout(previewTimer);
    syncProject();
    history.replaceState(null, "", location.pathname);
    try {
      localStorage.removeItem("p2r_session_id");
    } catch {}
    clearError();
    renderLibrary();
  } catch (e) {
    fail(e, () => reloadProject());
  }
}
$("new-project").onclick = newProject;
async function upload(file) {
  if (!file) return;
  try {
    await flush();
    clearError();
    $("dropzone").setAttribute("aria-busy", "true");
    $("dropzone").querySelector("strong").textContent =
      "Creating your project…";
    const model = chooseModel(state.models, state.defaultModel);
    const form = new FormData();
    form.append("image", file);
    const project = await json(
      "/api/projects/upload" + (model ? `?model_id=${model}` : ""),
      { method: "POST", body: form },
    );
    await refreshLibrary();
    await openProject(project.id, true, true);
  } catch (e) {
    fail(e, () => $("photo-file").click(), "Choose another image");
  } finally {
    $("dropzone").removeAttribute("aria-busy");
    $("dropzone").querySelector("strong").textContent = "Drop a photo here";
    $("photo-file").value = "";
  }
}
$("dropzone").onclick = () => $("photo-file").click();
$("dropzone").onkeydown = (e) => {
  if (["Enter", " "].includes(e.key)) {
    e.preventDefault();
    $("photo-file").click();
  }
};
$("photo-file").onchange = (e) => upload(e.target.files[0]);
for (const event of ["dragenter", "dragover"])
  $("dropzone").addEventListener(event, (e) => {
    e.preventDefault();
    $("dropzone").classList.add("drag-over");
  });
for (const event of ["dragleave", "drop"])
  $("dropzone").addEventListener(event, (e) => {
    e.preventDefault();
    $("dropzone").classList.remove("drag-over");
  });
$("dropzone").addEventListener("drop", (e) => upload(e.dataTransfer.files[0]));
async function retryGeneration() {
  if (!chooseModel(state.models, state.defaultModel)) {
    openSource();
    return;
  }
  const token = scope.capture();
  try {
    await json(`/api/projects/${token.id}/retry`, { method: "POST" });
    if (scope.current(token)) waitForDepth(token).catch((e) => fail(e));
  } catch (e) {
    if (scope.current(token)) {
      fail(e, () => modal("source-dialog"));
      processing(
        "Local model setup is incomplete",
        "Your image is saved. You can import an existing depth map from Depth maps.",
        true,
      );
    }
  }
}
$("generation-retry").onclick = retryGeneration;

// Project management, presets, tools, exchange and exports use the same serialized document context.
function openProjectSettings() {
  if (!state.project) return;
  $("project-name").value = state.project.name;
  modal("project-dialog");
}
$("project-title").onclick = openProjectSettings;
$("project-menu").onclick = openProjectSettings;
$("rename-form").onsubmit = async (event) => {
  event.preventDefault();
  try {
    await flush();
    const token = scope.capture(),
      project = await json(`/api/projects/${token.id}`, {
        method: "PATCH",
        json: { name: $("project-name").value },
      });
    if (!scope.current(token)) return;
    state.project = project;
    $("project-dialog").close();
    syncProject();
    refreshLibrary();
  } catch (e) {
    fail(e);
  }
};
$("delete-project").onclick = async () => {
  const project = state.project;
  if (!project) return;
  if (
    !(await confirm(
      "Delete this project?",
      `“${project.name}” will leave your library. A local recovery copy is kept. Shared models and other projects are untouched.`,
      "Delete project",
    ))
  )
    return;
  try {
    await flush();
    await json(`/api/projects/${project.id}`, { method: "DELETE" });
    $("project-dialog").close();
    await newProject();
    await refreshLibrary();
    toast(
      "Project deleted. A recovery copy is kept.",
      async () => {
        await json(`/api/projects/${project.id}/restore`, { method: "POST" });
        await refreshLibrary();
        await openProject(project.id);
      },
      "Restore",
    );
  } catch (e) {
    fail(e);
  }
};
async function repairProject(id) {
  if (
    !(await confirm(
      "Repair project information?",
      "A copy of existing metadata and settings is kept. Damaged shaping settings return to defaults. Original photographs and brush history are preserved.",
      "Repair project",
    ))
  )
    return;
  try {
    await json(`/api/projects/${id}/repair`, {
      method: "POST",
      json: { reset_settings: true },
    });
    queue.clearError();
    await openProject(id, true);
    await refreshLibrary();
  } catch (e) {
    fail(e);
  }
}
async function preset(name, undo = false) {
  try {
    await flush();
    await action(async (token) => {
      const result = await json(
        `/api/projects/${token.id}/${undo ? "undo-preset" : "preset"}`,
        {
          method: "POST",
          json: undo
            ? undefined
            : { name, expected_revision: state.editor.revision },
        },
      );
      if (!scope.current(token)) return;
      Object.assign(state, {
        project: result.project,
        params: result.params,
        editor: result.editor,
      });
      paramVersion++;
      invalidateExport();
      syncProject();
      schedulePreview(0);
      planExport();
      toast(
        undo
          ? "Previous shaping settings restored."
          : "Preset applied. Painted depth and masks are kept.",
      );
    });
  } catch (e) {
    fail(e);
  }
}
$("preset").onchange = (e) => preset(e.target.value);
$("undo-preset").onclick = () => preset(null, true);
$("reset-adjustments").onclick = async () => {
  if (
    !(await confirm(
      "Restore adjustment defaults?",
      "This resets size, shaping and export settings. Painted depth, masks, imported versions and original AI are kept.",
      "Restore defaults",
    ))
  )
    return;
  state.params = {
    ...state.defaults,
    depth_model:
      chooseModel(state.models, state.defaults.depth_model) ||
      state.params.depth_model,
  };
  paramVersion++;
  syncParams();
  saveParams().catch(() => {});
};
$("depth_model").onchange = async (event) => {
  const model = state.models.find((m) => m.model_id === event.target.value);
  if (!model?.selectable) {
    syncParams();
    return;
  }
  const transition = modelTransition(
    state.params.depth_model,
    model.model_id,
    state.editor.depth_source,
    state.ready,
  );
  if (!transition.changed) {
    syncParams();
    return;
  }
  state.params = { ...state.params, depth_model: model.model_id };
  paramVersion++;
  state.ready = transition.ready;
  syncProject();
  saveParams().catch(() => {});
};
$("export-quality").onchange = () => {
  state.params = changeParam(
    state.params,
    "resolution",
    $("export-quality").value,
  );
  paramVersion++;
  syncParams();
  invalidateExport();
  scheduleParams();
};
function setupSegmentation() {
  const seg = state.segmentation;
  if (!seg) return;
  $("mask-method").querySelector("[value=alpha]").disabled = !seg.source_alpha;
  $("mask-method").querySelector("[value=u2netp]").disabled = !seg.available;
  $("segmentation-availability").textContent = seg.source_alpha
    ? "Your image has an existing cutout. Automatic uses that shape; no additional model is needed."
    : seg.available
      ? "U2NETP is installed locally. GrabCut is also available."
      : "GrabCut is available. The optional U2NETP model is not installed.";
  $("segmentation-note").textContent = seg.source_alpha
    ? "Uses the cutout already present in your image. Refinements stay reversible."
    : "Runs locally. Inspect the result, then use keep/remove for corrections.";
}
async function removeBackground(rectangle = null) {
  if (!state.ready) return;
  if (
    state.editor.mask_operations > 0 &&
    !(await confirm(
      "Replace the current automatic mask?",
      "A new mask becomes the current result. Your existing mask and painted corrections remain available through Undo mask.",
      "Replace mask",
    ))
  )
    return;
  try {
    const result = await mutate(
      "/editor/automatic-mask",
      { method: $("mask-method").value, rectangle },
      "Isolating subject",
    );
    message(result?.segmentation?.method || "Subject mask saved");
    setPanel("background");
  } catch {}
}
$("quick-remove-background").onclick = () => removeBackground();
$("remove-background").onclick = () => removeBackground();
$("isolate-selection").onclick = () => {
  const rectangle = painting.rectangle();
  if (rectangle) removeBackground(rectangle);
};
for (const [id, field] of [
  ["mask-enabled", "mask_enabled"],
  ["mask-feather", "mask_feather_mm"],
  ["mask-transition", "mask_transition_mm"],
])
  $(id).onchange = () =>
    mutate(
      "/editor",
      { [field]: id === "mask-enabled" ? $(id).checked : Number($(id).value) },
      "Saving subject settings",
      "PUT",
    ).catch(() => {});
$("flatten-level").onchange = () => {
  const value = Number($("flatten-level").value);
  state.flattenLevel = Number.isFinite(value)
    ? Math.max(0, Math.min(1, value))
    : 0.5;
  syncBrush();
};
const historyAction = (channel, action) =>
  mutate(
    "/editor/history",
    { channel, action },
    `${action === "reset" ? "Reset" : action === "undo" ? "Undid" : "Redid"} ${channel} correction`,
  ).catch(() => {});
$("editor-undo").onclick = () => historyAction(state.layer, "undo");
$("editor-redo").onclick = () => historyAction(state.layer, "redo");
$("sculpt-undo").onclick = () => historyAction("depth", "undo");
$("sculpt-redo").onclick = () => historyAction("depth", "redo");
$("reset-depth").onclick = () => historyAction("depth", "reset");
$("reset-mask").onclick = () => historyAction("mask", "reset");
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    painting.cancel();
    message("Stroke cancelled.");
  }
  if (
    state.view !== "edit" ||
    document.querySelector("dialog[open]") ||
    ["INPUT", "SELECT", "TEXTAREA"].includes(event.target.tagName)
  )
    return;
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") {
    event.preventDefault();
    if (!state.compare && !state.saving)
      historyAction(state.layer, event.shiftKey ? "redo" : "undo");
  }
});
$("camera-fit").onclick = () => viewer.fit();
$("camera-reset").onclick = () => viewer.reset();
$("camera-top").onclick = () => viewer.top();
$("camera-zoom-in").onclick = () => viewer.zoom(0.83);
$("camera-zoom-out").onclick = () => viewer.zoom(1.2);

function openSource() {
  if (!state.id) return;
  syncEditor();
  $("source-message").textContent = "";
  modal("source-dialog");
}
$("open-depth-source").onclick = openSource;
$("source-shortcut").onclick = openSource;
$("editor-source").onchange = () => {
  const value = $("editor-source").value;
  mutate(
    "/editor",
    value === "ai"
      ? { depth_source: "ai" }
      : { depth_source: "imported", import_id: value.split(":")[1] },
    "Switching depth source",
    "PUT",
  )
    .then(() => {
      if (state.editor.depth_source === "imported") {
        state.ready = true;
        $("canvas-message").hidden = true;
        syncProject();
        schedulePreview(0);
      } else {
        state.ready = false;
        waitForDepth(scope.capture()).catch((e) => fail(e));
      }
    })
    .catch(() => {});
};
$("depth-file").onchange = async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  const form = new FormData();
  form.append("file", file);
  const invert = $("depth-white-far").checked,
    alignment = $("depth-stretch").checked ? "stretch" : "match";
  const importToken = scope.capture(),
    previousError = $("source-message").textContent;
  try {
    await action(async (token) => {
      const editor = await json(
        `/api/sessions/${token.id}/depth/import?white_is_far=${invert}&alignment=${alignment}&expected_revision=${state.editor.revision}`,
        { method: "POST", body: form },
      );
      if (!scope.current(token)) return;
      state.editor = editor;
      state.ready = true;
      state.readyModel = state.params.depth_model;
      $("canvas-message").hidden = true;
      syncProject();
      invalidateExport();
      schedulePreview(0);
      planExport();
      refreshLibrary();
      $("source-message").textContent =
        "High-precision depth imported. Your original file is preserved.";
      if ($("error-text").textContent === previousError) clearError();
    });
  } catch (e) {
    if (!scope.current(importToken)) return;
    // Rejected input never changed the saved project. Permit correcting the file
    // without clearing a different failed write from the serialized queue.
    if (e.status === 400 || e.status === 422) queue.clearError(e);
    $("source-message").textContent = e.message;
  } finally {
    event.target.value = "";
  }
};
function download(url, filename = "") {
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
}
for (const [id, format] of [
  ["depth-export-png", "png16"],
  ["depth-export-npy", "npy"],
])
  $(id).onclick = async () => {
    try {
      await flush();
      const source = $("depth-export-source").value,
        response = await api(
          session(`/depth/export?source=${source}&format=${format}`),
        );
      const url = URL.createObjectURL(await response.blob());
      download(url, `depth-${source}.${format === "png16" ? "png" : "npy"}`);
      setTimeout(() => URL.revokeObjectURL(url), 30000);
      $("source-message").textContent =
        `Saved ${format === "png16" ? "16-bit grayscale PNG" : "lossless float32 NPY"}. Higher values mean nearer.`;
    } catch (e) {
      $("source-message").textContent = e.message;
    }
  };
$("restore-ai").onclick = async () => {
  if (
    !(await confirm(
      "Restore the original AI workflow?",
      "Returns to unpainted AI depth and disables the subject mask and optional surface refinements. Existing imports and archived edits remain available. Size and original shaping controls stay as set.",
      "Restore AI",
    ))
  )
    return;
  mutate("/editor/restore-ai", {}, "Restored original AI")
    .then(() => {
      $("source-message").textContent =
        "Original AI restored. Undo depth can recover its previous brush work.";
    })
    .catch(() => {});
};

async function openHistory() {
  if (!state.id) return;
  $("checkpoint-layer").value = state.layer;
  try {
    const result = await json(session("/editor/checkpoints"));
    $("checkpoint-list").replaceChildren();
    for (const checkpoint of result.items.toReversed()) {
      const row = document.createElement("div");
      row.className = "checkpoint-row";
      const span = document.createElement("span");
      span.textContent = `${checkpoint.channel} · ${new Date(checkpoint.created_at).toLocaleString()}`;
      const button = document.createElement("button");
      button.className = "button";
      button.textContent = "Restore";
      button.onclick = async () => {
        if (
          await confirm(
            "Restore this editing state?",
            "Both depth and mask return to the archived state. Current work is archived first, so it can be recovered. Shaping settings and dimensions stay current.",
            "Restore checkpoint",
          )
        )
          mutate(
            "/editor/checkpoints/restore",
            { id: checkpoint.id },
            "Restored checkpoint",
          )
            .then(() => {
              openHistoryRefresh();
            })
            .catch(() => {});
      };
      row.append(span, button);
      $("checkpoint-list").append(row);
    }
    if (!result.items.length)
      $("checkpoint-list").textContent = "No checkpoints yet.";
    if (!$("history-dialog").open) modal("history-dialog");
  } catch (e) {
    fail(e);
  }
}
function openHistoryRefresh() {
  openHistory();
}
$("manage-history").onclick = openHistory;
$("create-checkpoint").onclick = async () => {
  const channel = $("checkpoint-layer").value;
  if (
    !(await confirm(
      "Start a new undo history?",
      "The current result is kept. The previous editing state is archived and can be restored below. Original photos and AI predictions are never replaced.",
      "Create checkpoint",
    ))
  )
    return;
  mutate("/editor/checkpoint", { channel }, "Created history checkpoint")
    .then(openHistoryRefresh)
    .catch(() => {});
};

async function planExport() {
  if (!state.id || !state.params) return;
  const token = scope.capture(),
    sequence = ++planSequence;
  try {
    const plan = await json(`/api/sessions/${token.id}/export-plan`, {
      method: "POST",
      json: state.params,
    });
    if (!scope.current(token) || sequence !== planSequence) return;
    state.plan = plan;
    const box = $("export-plan");
    box.replaceChildren();
    box.classList.toggle("unsafe", !plan.allowed);
    for (const [name, value] of [
      ["Triangles", plan.output_triangles_estimate.toLocaleString()],
      ["Estimated file", bytes(plan.output_bytes_estimate)],
      ["Working memory", bytes(plan.memory_bytes_estimate)],
    ]) {
      const stat = document.createElement("span");
      stat.className = "plan-stat";
      const title = document.createElement("span"),
        strong = document.createElement("strong");
      title.textContent = name;
      strong.textContent = value;
      stat.append(title, strong);
      box.append(stat);
    }
    const explanation = document.createElement("p");
    explanation.className = "plan-explanation";
    explanation.textContent = plan.message;
    box.append(explanation);
    $("lower-quality").hidden = plan.allowed || state.params.resolution === 512;
    $("export-build").disabled =
      !plan.allowed ||
      !state.ready ||
      state.compare ||
      Boolean(state.exporting);
    syncParams();
  } catch (e) {
    if (scope.current(token)) {
      $("export-plan").textContent = e.message;
      $("export-build").disabled = true;
    }
  }
}
$("lower-quality").onclick = async () => {
  state.params = changeParam(state.params, "resolution", 512);
  paramVersion++;
  syncParams();
  await saveParams().catch(() => {});
  planExport();
};
$("open-export").onclick = async () => {
  try {
    await flush();
    syncProject();
    modal("export-dialog");
    planExport();
  } catch (e) {
    fail(e, () => reloadProject());
  }
};
const stageNames = {
  "loading depth": "Preparing depth",
  "shaping heightmap": "Preparing relief",
  "building mesh": "Building a solid",
  "validating watertight": "Checking the solid",
  decimating: "Reducing triangles",
  "re-validating watertight": "Checking the simplified solid",
};
$("export-build").onclick = async () => {
  if (state.exporting || state.compare) return;
  const token = scope.capture(),
    name = state.project.name;
  try {
    await flush();
    if (!scope.current(token)) return;
    await planExport();
    if (!scope.current(token) || !state.plan?.allowed) return;
    const snapshot = JSON.parse(JSON.stringify(state.params)),
      key = JSON.stringify(snapshot) + ":" + state.editor.revision;
    if (state.lastExport?.key === key) {
      const result = await json(`/api/jobs/${state.lastExport.id}`);
      if (result.status === "ready") {
        $("download-mesh").href = result.download_url;
        $("download-mesh").hidden = false;
        $("export-result").textContent =
          "The existing export matches these saved settings.";
        return;
      }
    }
    state.exporting = { id: token.id };
    $("export-build").disabled = true;
    $("export-progress").hidden = false;
    $("export-result").textContent = "";
    $("download-mesh").hidden = true;
    $("export-progress-bar").removeAttribute("value");
    const job = await json(`/api/sessions/${token.id}/export`, {
      method: "POST",
      json: snapshot,
    });
    state.exporting.job = job.job_id;
    let result;
    do {
      result = await json(`/api/jobs/${job.job_id}`);
      if (scope.current(token)) {
        $("export-stage").textContent =
          stageNames[result.stage] || result.stage || "Starting export";
        $("export-progress-bar").value = result.progress || 0;
      }
      if (result.status === "processing")
        await new Promise((resolve) => setTimeout(resolve, 400));
    } while (result.status === "processing");
    if (result.status === "error") throw new Error(result.error);
    if (scope.current(token)) {
      state.lastExport = { key, id: job.job_id, url: result.download_url };
      $("download-mesh").href = result.download_url;
      $("download-mesh").hidden = false;
      $("export-result").textContent =
        `Export ready · ${result.triangles.toLocaleString()} triangles · ${bytes(result.file_bytes)}`;
      $("export-stage").textContent = "Complete";
    } else
      toast(
        `“${name}” export is ready.`,
        () => download(result.download_url),
        "Download",
      );
  } catch (e) {
    if (scope.current(token)) {
      $("export-result").textContent = e.message;
      fail(e, () => $("export-build").click());
    } else toast(`Export for “${name}” did not finish: ${e.message}`);
  } finally {
    state.exporting = null;
    if (scope.current(token)) {
      $("export-progress").hidden = true;
      planExport();
    }
  }
};

$("open-settings").onclick = async () => {
  modal("settings-dialog");
  try {
    const [models, storage] = await Promise.all([
      json("/api/models"),
      json("/api/storage"),
    ]);
    state.models = models.models;
    renderModels();
    $("storage-summary").textContent =
      `Projects: ${bytes(storage.protected_session_bytes)} · Shared depth cache: ${bytes(storage.cache_bytes)} · Models: ${bytes(storage.model_bytes)}`;
  } catch (e) {
    $("storage-summary").textContent = e.message;
  }
};
$("open-help").onclick = () => modal("help-dialog");
function renderModels() {
  const labels = {
    "da2-small": "Depth Anything V2 Small",
    "da2-large": "Depth Anything V2 Large",
    "da3mono-large": "Depth Anything 3 Mono Large",
  };
  $("depth_model").replaceChildren();
  $("setup-models").replaceChildren();
  for (const model of state.models) {
    const label = labels[model.model_id] || model.model_id;
    const option = new Option(
      `${label}${model.selectable ? "" : ` · ${model.setup_state.replaceAll("_", " ")}`}`,
      model.model_id,
    );
    option.disabled = !model.selectable;
    $("depth_model").append(option);
    const row = document.createElement("div");
    row.className = "setup-model";
    const strong = document.createElement("strong"),
      status = document.createElement("span"),
      reason = document.createElement("p");
    strong.textContent = label;
    status.textContent =
      model.activity || model.setup_state.replaceAll("_", " ");
    reason.textContent = model.setup_reason;
    row.append(strong, status, reason);
    $("setup-models").append(row);
  }
  syncParams();
}
async function init() {
  try {
    const models = await json("/api/models");
    state.models = models.models;
    state.defaultModel = models.default_model;
    state.defaults = models.default_params;
    renderModels();
    await refreshLibrary();
    $("setup-note").textContent = chooseModel(state.models, state.defaultModel)
      ? "No accounts. No cloud processing."
      : "Local AI setup is incomplete. You can still upload a photo and import a depth map.";
    let id = new URLSearchParams(location.search).get("session");
    try {
      id = id || localStorage.getItem("p2r_session_id");
    } catch {}
    if (id) {
      if (state.projects.some((p) => p.id === id)) await openProject(id);
      else {
        toast(
          "That saved project is no longer available. Your other projects are here.",
        );
        history.replaceState(null, "", location.pathname);
        try {
          localStorage.removeItem("p2r_session_id");
        } catch {}
      }
    }
  } catch (e) {
    fail(e, init);
  }
  syncProject();
}
init();
