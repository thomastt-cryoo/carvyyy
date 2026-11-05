// M2 functional editor. Durable documents and stroke calculations live on the backend.
export function createStudioEditor({ api, getSession, changed }) {
  const $ = (id) => document.getElementById(id);
  const dialog = $("studio-editor");
  const canvas = $("editor-canvas");
  const ctx = canvas.getContext("2d");
  let sid = null, documentState = null, photo = null, basePixels = null;
  let rectangle = null, gesture = null, sequence = 0, busy = false;
  let queue = Promise.resolve();

  function message(text, error = false) {
    $("editor-message").textContent = text;
    $("editor-message").classList.toggle("error", error);
  }
  const channel = () => ["keep", "remove", "rectangle"].includes($("editor-tool").value) ? "mask" : "depth";
  function sync() {
    if (!documentState) return;
    for (const control of dialog.querySelectorAll('input, select, button')) {
      if (control.id !== 'editor-close') control.disabled = busy;
    }
    const select = $("editor-source");
    select.replaceChildren();
    const ai = new Option("AI prediction", "ai");
    select.append(ai);
    const imports = documentState.imports?.length ? documentState.imports : (documentState.imported ? [documentState.imported] : []);
    imports.forEach((item, index) => select.append(new Option(`${index + 1}. ${item.filename}`, `imported:${item.id}`)));
    select.value = documentState.depth_source === "imported" ? `imported:${documentState.imported.id}` : "ai";
    $("mask-enabled").checked = documentState.mask_enabled;
    $("mask-feather").value = documentState.mask_feather_mm;
    $("mask-transition").value = documentState.mask_transition_mm;
    $("sculpt-strength").value = documentState.sculpt_strength;
    $("texture-guard").value = documentState.texture_guard;
    const layer = channel();
    $("editor-undo").textContent = `Undo ${layer}`;
    $("editor-redo").textContent = `Redo ${layer}`;
    $("editor-reset").textContent = `Reset ${layer}`;
    $("editor-undo").disabled = busy || !documentState[`${layer}_undo`];
    $("editor-redo").disabled = busy || !documentState[`${layer}_redo`];
    $("editor-summary").textContent = `${documentState.depth_source === "ai" ? "AI" : "Imported"} depth · ${documentState.mask_enabled ? "subject mask on" : "mask off"} · saved revision ${documentState.revision}`;
    $("edit-btn").disabled = false;
  }
  const loadImage = (url) => new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error("The editor image is not ready. Wait for depth inference or choose another source."));
    image.src = url;
  });
  function redraw() {
    if (!basePixels) return;
    ctx.putImageData(basePixels, 0, 0);
    if (rectangle) {
      ctx.strokeStyle = "#fff"; ctx.lineWidth = 2; ctx.setLineDash([6, 4]);
      ctx.strokeRect(rectangle[0] * canvas.width, rectangle[1] * canvas.height,
        (rectangle[2] - rectangle[0]) * canvas.width, (rectangle[3] - rectangle[1]) * canvas.height);
      ctx.setLineDash([]);
    }
    if (gesture?.points.length && gesture.tool !== "rectangle") {
      ctx.strokeStyle = gesture.channel === "mask" ? (gesture.tool === "keep" ? "#75d6ab" : "#ed8e88") : "#fff";
      ctx.lineWidth = Math.max(2, gesture.radius * 2 * Math.max(canvas.width, canvas.height));
      ctx.lineCap = "round"; ctx.lineJoin = "round"; ctx.globalAlpha = 0.35;
      ctx.beginPath();
      gesture.points.forEach(([x, y], index) => index ? ctx.lineTo(x * canvas.width, y * canvas.height) : ctx.moveTo(x * canvas.width, y * canvas.height));
      if (gesture.points.length === 1) ctx.lineTo(gesture.points[0][0] * canvas.width + 0.01, gesture.points[0][1] * canvas.height);
      ctx.stroke(); ctx.globalAlpha = 1;
    }
  }
  async function render() {
    if (!sid || !documentState || !dialog.open) return;
    const current = ++sequence;
    const view = $("editor-view").value;
    const suffix = `?view=${view}&v=${documentState.revision}`;
    const [image, mask] = await Promise.all([
      view === "photo" ? Promise.resolve(photo) : loadImage(`/api/sessions/${sid}/editor/image${suffix}`),
      loadImage(`/api/sessions/${sid}/editor/image?view=mask&v=${documentState.revision}`),
    ]);
    if (current !== sequence || !dialog.open) return;
    canvas.width = photo.width; canvas.height = photo.height;
    ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
    if (view !== "processed" && view !== "ai" && documentState.mask_enabled) {
      const scratch = document.createElement("canvas");
      scratch.width = canvas.width; scratch.height = canvas.height;
      const sc = scratch.getContext("2d", { willReadFrequently: true });
      sc.drawImage(mask, 0, 0, canvas.width, canvas.height);
      const overlay = sc.getImageData(0, 0, canvas.width, canvas.height);
      for (let i = 0; i < overlay.data.length; i += 4) {
        const removed = 1 - overlay.data[i] / 255;
        overlay.data[i] = 220; overlay.data[i + 1] = 65; overlay.data[i + 2] = 65;
        overlay.data[i + 3] = Math.round(removed * 115);
      }
      sc.putImageData(overlay, 0, 0); ctx.drawImage(scratch, 0, 0);
    }
    basePixels = ctx.getImageData(0, 0, canvas.width, canvas.height);
    redraw();
  }
  function enqueue(path, body, label = "Saving correction…", options = {}) {
    const submittedSid = sid;
    const task = queue.then(async () => {
      if (submittedSid !== sid) throw new Error("The selected photo changed. Reopen the editor.");
      busy = true; dialog.classList.add("busy"); sync(); message(label);
      try {
        const request = options.form ? options.form : JSON.stringify({ ...body, expected_revision: documentState.revision });
        const url = `/api/sessions/${sid}${path}` + (options.form ? `&expected_revision=${documentState.revision}` : "");
        documentState = await (await api(url, {
          method: options.method || "POST", body: request,
          headers: options.form ? undefined : { "Content-Type": "application/json" },
        })).json();
        sync();
        await render();
        await changed(documentState);
        message(documentState.segmentation ? `${documentState.segmentation.method}. ${documentState.segmentation.note}` : "Saved. Preview and exports use this correction.");
      } catch (error) {
        message(error.message, true);
        // Refresh revision after a stale request without silently replaying its gesture.
        try { documentState = await (await api(`/api/sessions/${sid}/editor`)).json(); sync(); } catch {}
        throw error;
      } finally {
        busy = false; dialog.classList.remove("busy"); sync();
      }
    });
    queue = task.catch(() => {});
    return task;
  }
  const update = (fields) => enqueue("/editor", fields, "Saving processing settings…", { method: "PUT" });
  $("edit-btn").addEventListener("click", async () => {
    try {
      await queue;
      documentState = await (await api(`/api/sessions/${sid}/editor`)).json();
      const segmentation = await (await api(`/api/sessions/${sid}/segmentation`)).json();
      $("segmentation-status").textContent = segmentation.available ? "U2NETP installed · local CPU · approximately 500 MB temporary RAM." : "GrabCut ready. Optional U2NETP needs the segmentation extra and verified model download.";
      if (!photo) photo = await loadImage(`/api/sessions/${sid}/editor/image?view=photo`);
      dialog.showModal(); sync(); await render();
      message("Paint keep/remove to correct a mask, or select a depth brush. Automatic isolation is a starting point.");
    } catch (error) { message(error.message, true); }
  });
  $("editor-close").addEventListener("click", async () => { await queue; dialog.close(); ++sequence; });
  $("editor-source").addEventListener("change", () => {
    const value = $("editor-source").value;
    update(value === "ai" ? { depth_source: "ai" } : { depth_source: "imported", import_id: value.split(":")[1] }).catch(() => {});
  });
  $("auto-mask").addEventListener("click", () => enqueue("/editor/automatic-mask", { rectangle: null, method: $("mask-method").value }, "Separating subject locally…").catch(() => {}));
  $("isolate-selection").addEventListener("click", () => {
    if (!rectangle) return message("Select the rectangle tool and drag around the complete subject first.", true);
    enqueue("/editor/automatic-mask", { rectangle, method: $("mask-method").value }, "Separating selected subject locally…").catch(() => {});
  });
  $("editor-tool").addEventListener("change", () => {
    const tool = $("editor-tool").value;
    $("brush-strength").value = channel() === "mask" ? 100 : (tool === "smooth" || tool === "flatten" ? 60 : 6);
    if (channel() === "depth" && $("editor-view").value === "photo") $("editor-view").value = "working";
    if (channel() === "mask" && $("editor-view").value === "working") $("editor-view").value = "photo";
    sync(); render().catch((e) => message(e.message, true));
  });
  $("editor-view").addEventListener("change", () => render().catch((e) => message(e.message, true)));
  for (const action of ["undo", "redo", "reset"]) $("editor-" + action).addEventListener("click", () => {
    enqueue("/editor/history", { channel: channel(), action }).catch(() => {});
  });
  for (const [id, field] of [["mask-enabled", "mask_enabled"], ["mask-feather", "mask_feather_mm"],
    ["mask-transition", "mask_transition_mm"], ["sculpt-strength", "sculpt_strength"], ["texture-guard", "texture_guard"]]) {
    $(id).addEventListener("change", () => update({ [field]: id === "mask-enabled" ? $(id).checked : Number($(id).value) }).catch(() => {}));
  }
  $("restore-ai").addEventListener("click", () => enqueue("/editor/restore-ai", {}).catch(() => {}));
  $("depth-file").addEventListener("change", () => {
    const file = $("depth-file").files[0];
    if (!file) return;
    const form = new FormData(); form.append("file", file);
    const query = `?white_is_far=${$("depth-white-far").checked}&alignment=${$("depth-stretch").checked ? "stretch" : "match"}`;
    enqueue("/depth/import" + query, {}, "Importing high-precision depth…", { form }).catch(() => {});
    $("depth-file").value = "";
  });
  for (const [id, format] of [["depth-export-png", "png16"], ["depth-export-npy", "npy"]]) {
    $(id).addEventListener("click", async () => {
      await queue;
      try {
        const source = $("depth-export-source").value;
        const response = await api(`/api/sessions/${sid}/depth/export?source=${source}&format=${format}`);
        const url = URL.createObjectURL(await response.blob());
        const link = document.createElement("a"); link.href = url;
        link.download = `depth-${source}.${format === "png16" ? "png" : "npy"}`; link.click();
        setTimeout(() => URL.revokeObjectURL(url), 30000);
        message(`Saved ${format === "png16" ? "16-bit PNG" : "float32 NPY"}; white/higher values mean nearer.`);
      } catch (error) { message(error.message, true); }
    });
  }
  const point = (event) => {
    const bounds = canvas.getBoundingClientRect();
    return [Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width)),
      Math.max(0, Math.min(1, (event.clientY - bounds.top) / bounds.height))];
  };
  canvas.addEventListener("pointerdown", (event) => {
    if (busy || !basePixels || $("editor-view").value === "ai") return;
    event.preventDefault(); canvas.focus(); canvas.setPointerCapture(event.pointerId);
    gesture = { channel: channel(), tool: $("editor-tool").value, points: [point(event)],
      radius: Number($("brush-size").value) / 100, strength: Number($("brush-strength").value) / 100,
      level: Number($("flatten-level").value) };
    if (gesture.tool === "rectangle") rectangle = [...gesture.points[0], ...gesture.points[0]];
    redraw();
  });
  canvas.addEventListener("pointermove", (event) => {
    if (!gesture) return;
    const p = point(event), last = gesture.points[gesture.points.length - 1];
    if (gesture.tool === "rectangle") {
      const start = gesture.points[0];
      rectangle = [Math.min(start[0], p[0]), Math.min(start[1], p[1]), Math.max(start[0], p[0]), Math.max(start[1], p[1])];
    } else if (Math.hypot(p[0] - last[0], p[1] - last[1]) > gesture.radius / 5 && gesture.points.length < 1000) gesture.points.push(p);
    redraw();
  });
  function endGesture(event) {
    if (!gesture) return;
    if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
    const stroke = gesture; gesture = null; redraw();
    if (stroke.tool !== "rectangle") enqueue("/editor/stroke", stroke, "Saving brush stroke…").catch(() => {});
    else message("Selection ready. Click Isolate selection; use keep/remove brushes for corrections.");
  }
  canvas.addEventListener("pointerup", endGesture);
  canvas.addEventListener("pointercancel", () => { gesture = null; redraw(); });
  dialog.addEventListener("keydown", (event) => {
    if (event.target !== canvas || !(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== "z") return;
    event.preventDefault(); enqueue("/editor/history", { channel: channel(), action: event.shiftKey ? "redo" : "undo" }).catch(() => {});
  });
  return {
    async bindSession(sessionId) {
      await queue; sid = sessionId; photo = null; basePixels = null; rectangle = null; ++sequence;
      documentState = await (await api(`/api/sessions/${sid}/editor`)).json(); sync();
    },
    async refresh() { if (sid) { documentState = await (await api(`/api/sessions/${sid}/editor`)).json(); sync(); } },
    flush: () => queue,
    revision: () => documentState?.revision || 0,
    usingImported: () => documentState?.depth_source === "imported",
  };
}
