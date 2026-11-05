// Shared, DOM-free state rules. All values map directly to the original backend schema.
export const FIELDS = [
  {
    id: "model_width_mm",
    label: "Width",
    unit: "mm",
    min: 10,
    max: 1000,
    step: 0.1,
    group: "essential",
    tip: "Image width in millimetres. Height follows the original image aspect.",
  },
  {
    id: "relief_height_mm",
    label: "Relief depth",
    unit: "mm",
    min: 0.5,
    max: 100,
    step: 0.1,
    group: "essential",
    tip: "Maximum height above the backing. More depth creates a stronger relief.",
  },
  {
    id: "smoothing",
    label: "Smoothing",
    min: 0,
    max: 10,
    step: 0.1,
    group: "essential",
    tip: "Soften small surface irregularities. Higher values reduce fine detail.",
  },
  {
    id: "detail_blend",
    label: "Surface detail",
    min: 0,
    max: 1,
    step: 0.005,
    group: "essential",
    tip: "Adds texture from photo brightness. Shadows and reflections can become false geometry.",
  },
  {
    id: "base_thickness_mm",
    label: "Backing thickness",
    unit: "mm",
    min: 0.5,
    max: 50,
    step: 0.1,
    group: "geometry",
    tip: "Solid material underneath the relief.",
  },
  {
    id: "border_frame_mm",
    label: "Border frame",
    unit: "mm",
    min: 0,
    max: 50,
    step: 0.1,
    group: "geometry",
    tip: "Adds a full-height margin outside the image on all four sides.",
  },
  {
    id: "edge_taper_mm",
    label: "Outer edge taper",
    unit: "mm",
    min: 0,
    max: 50,
    step: 0.1,
    group: "geometry",
    tip: "Blends the outer image edges down to the backing over this distance.",
  },
  {
    id: "gamma",
    label: "Depth contrast (gamma)",
    min: 0.2,
    max: 5,
    step: 0.01,
    group: "shaping",
    tip: "Redistributes heights. Above 1 compresses lower areas; below 1 lifts them.",
  },
  {
    id: "depth_floor",
    label: "Far depth limit",
    min: 0,
    max: 1,
    step: 0.001,
    group: "shaping",
    tip: "Depth values below this level are clipped. Must be below the near limit.",
  },
  {
    id: "depth_ceiling",
    label: "Near depth limit",
    min: 0,
    max: 1,
    step: 0.001,
    group: "shaping",
    tip: "Depth values above this level reach full relief. Must exceed the far limit.",
  },
  {
    id: "invert_depth",
    label: "Invert relief",
    type: "checkbox",
    group: "shaping",
    tip: "Swap raised and recessed areas for an intaglio or mould.",
  },
  {
    id: "flatten_background",
    label: "Flatten low depth",
    type: "checkbox",
    group: "shaping",
    tip: "Flatten values below a threshold. This is separate from subject isolation.",
  },
  {
    id: "background_threshold",
    label: "Flatten threshold",
    min: 0,
    max: 1,
    step: 0.001,
    group: "shaping",
    tip: "Normalized cutoff used by Flatten low depth. Full original 0–1 range retained.",
  },
  {
    id: "edge_preserve",
    label: "Preserve edges when smoothing",
    type: "checkbox",
    group: "shaping",
    tip: "Use bilateral filtering to retain boundaries. Turn off for Gaussian smoothing.",
  },
  {
    id: "depth_model",
    label: "Depth model",
    type: "model",
    group: "model",
    tip: "Only installed, supported and permitted models can be selected.",
  },
  {
    id: "resolution",
    label: "Mesh resolution",
    type: "select",
    options: [512, 1024, 2048],
    group: "export",
    tip: "Long-side sample count, including the frame. Higher settings need more memory.",
  },
  {
    id: "decimate_ratio",
    label: "Triangle reduction",
    min: 0,
    max: 0.95,
    step: 0.01,
    group: "export",
    tip: "Fraction of triangles removed. 0.5 removes about half; full grid memory is still needed.",
  },
  {
    id: "output_format",
    label: "File format",
    type: "select",
    options: ["stl", "obj"],
    group: "export",
    tip: "STL or OBJ. Import into your other software using millimetres.",
  },
];
export const QUALITY = [
  { name: "Standard", value: 512 },
  { name: "High", value: 1024 },
  { name: "Maximum", value: 2048 },
];
export function changeParam(params, id, value) {
  const field = FIELDS.find((f) => f.id === id);
  if (!field) throw new Error("Unknown parameter");
  if (field.type === "checkbox") value = Boolean(value);
  else if (field.type === "select") {
    value = id === "resolution" ? Number(value) : value;
    if (!field.options.includes(value)) throw new Error("Unsupported option");
  } else if (field.type !== "model") {
    value = Number(value);
    if (!Number.isFinite(value)) throw new Error("Enter a number");
    value = Math.max(field.min, Math.min(field.max, value));
  }
  const result = { ...params, [id]: value };
  if (result.depth_floor >= result.depth_ceiling)
    throw new Error("Far depth limit must be below the near depth limit.");
  return result;
}
export const bytes = (value) =>
  value >= 1024 ** 3
    ? `${(value / 1024 ** 3).toFixed(1)} GB`
    : `${(value / 1024 ** 2).toFixed(1)} MB`;
export function chooseModel(models, preferred) {
  return (
    models.find((m) => m.model_id === preferred && m.selectable)?.model_id ||
    models.find((m) => m.selectable)?.model_id ||
    null
  );
}

export function modelTransition(current, selected, depthSource, ready) {
  return {
    changed: current !== selected,
    ready: depthSource === "imported" ? ready : current === selected && ready,
  };
}
export function createScope() {
  let generation = 0,
    id = null;
  return {
    enter(next) {
      id = next;
      generation++;
      return this.capture();
    },
    capture() {
      return { id, generation };
    },
    current(token) {
      return token.id === id && token.generation === generation;
    },
  };
}
export function serialQueue() {
  let tail = Promise.resolve(),
    error = null;
  return {
    run(fn) {
      const task = tail.then(fn);
      tail = task.catch((e) => {
        error = e;
      });
      return task;
    },
    async flush() {
      await tail;
      if (error) {
        const e = error;
        error = null;
        throw e;
      }
    },
    settled() {
      return tail;
    },
    clearError(expected) {
      if (expected !== undefined && error !== expected) return false;
      error = null;
      return true;
    },
  };
}
export function savedPreset(project, params, editor) {
  const values = {
    Portrait: [1.1, 1.8, 0.04, 0.25, 0.85],
    Pet: [1.1, 2.2, 0.035, 0.35, 0.9],
    Object: [1, 1.8, 0.04, 0.2, 0.9],
    Ornament: [1, 1.2, 0.08, 0, 0.3],
  }[project?.preset];
  if (!values) return "Custom";
  return [
    params.gamma,
    params.smoothing,
    params.detail_blend,
    editor.sculpt_strength,
    editor.texture_guard,
  ].every((n, i) => Math.abs(n - values[i]) < 1e-6)
    ? project.preset
    : "Custom";
}
