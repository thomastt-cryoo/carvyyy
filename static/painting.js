// Aligned 2D tools only: no brush event listeners are attached to the 3D viewport.
export function createPainting({
  canvas,
  cursor,
  getState,
  submit,
  selectionReady,
}) {
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  let imageData = null,
    photo = null,
    project = null,
    gesture = null,
    rectangle = null,
    serial = 0;
  const load = (url) =>
    new Promise((resolve, reject) => {
      const im = new Image();
      im.onload = () => resolve(im);
      im.onerror = () =>
        reject(
          new Error(
            "This preview is not ready. Wait for depth or import a depth map.",
          ),
        );
      im.src = url;
    });
  function redraw() {
    if (!imageData) return;
    ctx.putImageData(imageData, 0, 0);
    if (rectangle) {
      ctx.strokeStyle = "#222";
      ctx.lineWidth = 3;
      ctx.strokeRect(
        rectangle[0] * canvas.width,
        rectangle[1] * canvas.height,
        (rectangle[2] - rectangle[0]) * canvas.width,
        (rectangle[3] - rectangle[1]) * canvas.height,
      );
      ctx.strokeStyle = "#fff";
      ctx.lineWidth = 1;
      ctx.setLineDash([5, 4]);
      ctx.strokeRect(
        rectangle[0] * canvas.width,
        rectangle[1] * canvas.height,
        (rectangle[2] - rectangle[0]) * canvas.width,
        (rectangle[3] - rectangle[1]) * canvas.height,
      );
      ctx.setLineDash([]);
    }
    if (gesture && gesture.tool !== "rectangle") {
      ctx.strokeStyle =
        gesture.channel === "mask"
          ? gesture.tool === "keep"
            ? "#d3ead8"
            : "#e2aaaa"
          : "#eee";
      ctx.globalAlpha = 0.4;
      ctx.lineWidth =
        gesture.radius * 2 * Math.max(canvas.width, canvas.height);
      ctx.lineCap = "round";
      ctx.lineJoin = "round";
      ctx.beginPath();
      gesture.points.forEach(([x, y], i) =>
        i
          ? ctx.lineTo(x * canvas.width, y * canvas.height)
          : ctx.moveTo(x * canvas.width, y * canvas.height),
      );
      if (gesture.points.length === 1)
        ctx.lineTo(
          gesture.points[0][0] * canvas.width + 0.01,
          gesture.points[0][1] * canvas.height,
        );
      ctx.stroke();
      ctx.globalAlpha = 1;
    }
  }
  async function render() {
    const state = getState();
    if (!state.id || !state.ready || state.view !== "edit") return;
    const version = ++serial,
      id = state.id;
    if (project !== id) {
      photo = null;
      project = id;
      rectangle = null;
      imageData = null;
    }
    if (!photo) {
      const loaded = await load(`/api/sessions/${id}/editor/image?view=photo`);
      if (version !== serial || getState().id !== id) return;
      photo = loaded;
    }
    const view = state.layer === "mask" ? "photo" : "working";
    const [image, mask] = await Promise.all([
      view === "photo"
        ? Promise.resolve(photo)
        : load(
            `/api/sessions/${id}/editor/image?view=${view}&v=${state.editor.revision}`,
          ),
      load(
        `/api/sessions/${id}/editor/image?view=mask&v=${state.editor.revision}`,
      ),
    ]);
    if (
      version !== serial ||
      getState().id !== id ||
      getState().view !== "edit"
    )
      return;
    canvas.width = photo.width;
    canvas.height = photo.height;
    ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
    if (state.editor.mask_enabled) {
      const scratch = document.createElement("canvas");
      scratch.width = canvas.width;
      scratch.height = canvas.height;
      const sc = scratch.getContext("2d", { willReadFrequently: true });
      sc.drawImage(mask, 0, 0, canvas.width, canvas.height);
      const overlay = sc.getImageData(0, 0, canvas.width, canvas.height);
      for (let i = 0; i < overlay.data.length; i += 4) {
        const opacity = (1 - overlay.data[i] / 255) * 100;
        overlay.data[i] = 190;
        overlay.data[i + 1] = 70;
        overlay.data[i + 2] = 70;
        overlay.data[i + 3] = opacity;
      }
      sc.putImageData(overlay, 0, 0);
      ctx.drawImage(scratch, 0, 0);
    }
    imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
    redraw();
  }
  function point(event) {
    const r = canvas.getBoundingClientRect();
    return [
      Math.max(0, Math.min(1, (event.clientX - r.left) / r.width)),
      Math.max(0, Math.min(1, (event.clientY - r.top) / r.height)),
    ];
  }
  function cancel() {
    gesture = null;
    cursor.hidden = true;
    redraw();
  }
  canvas.addEventListener("pointerdown", (event) => {
    const state = getState();
    if (
      !imageData ||
      !state.ready ||
      state.saving ||
      state.compare ||
      state.view !== "edit" ||
      event.button !== 0
    )
      return;
    event.preventDefault();
    canvas.focus();
    canvas.setPointerCapture(event.pointerId);
    gesture = {
      channel: state.layer,
      tool: state.tool,
      points: [point(event)],
      radius: state.brushRadius / 100,
      strength: state.brushStrength / 100,
      level: state.flattenLevel,
    };
    if (state.tool === "rectangle")
      rectangle = [...gesture.points[0], ...gesture.points[0]];
    redraw();
  });
  canvas.addEventListener("pointermove", (event) => {
    const state = getState(),
      p = point(event),
      r = canvas.getBoundingClientRect();
    cursor.hidden =
      state.tool === "rectangle" ||
      !state.ready ||
      state.compare ||
      state.saving;
    cursor.style.left = `${p[0] * r.width}px`;
    cursor.style.top = `${p[1] * r.height}px`;
    cursor.style.width =
      cursor.style.height = `${(state.brushRadius / 100) * 2 * Math.max(r.width, r.height)}px`;
    if (!gesture) return;
    if (gesture.tool === "rectangle") {
      const start = gesture.points[0];
      rectangle = [
        Math.min(start[0], p[0]),
        Math.min(start[1], p[1]),
        Math.max(start[0], p[0]),
        Math.max(start[1], p[1]),
      ];
    } else {
      const last = gesture.points.at(-1);
      if (
        Math.hypot(p[0] - last[0], p[1] - last[1]) > gesture.radius / 5 &&
        gesture.points.length < 1000
      )
        gesture.points.push(p);
    }
    redraw();
  });
  canvas.addEventListener("pointerleave", () => {
    cursor.hidden = true;
  });
  canvas.addEventListener("pointercancel", cancel);
  canvas.addEventListener("pointerup", (event) => {
    if (!gesture) return;
    const stroke = gesture;
    gesture = null;
    if (canvas.hasPointerCapture(event.pointerId))
      canvas.releasePointerCapture(event.pointerId);
    redraw();
    if (stroke.tool === "rectangle") selectionReady(rectangle);
    else submit(stroke);
  });
  return {
    render,
    cancel,
    rectangle: () => rectangle,
    clear() {
      serial++;
      imageData = null;
      photo = null;
      project = null;
      rectangle = null;
      cancel();
    },
  };
}
