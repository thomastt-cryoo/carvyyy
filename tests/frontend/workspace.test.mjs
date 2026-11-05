import test from "node:test";
import assert from "node:assert/strict";
import {
  FIELDS,
  changeParam,
  chooseModel,
  createScope,
  serialQueue,
  savedPreset,
  QUALITY,
  modelTransition,
} from "../../static/core.js";

const defaults = {
  model_width_mm: 150,
  relief_height_mm: 8,
  base_thickness_mm: 3,
  border_frame_mm: 0,
  depth_model: "da2-small",
  invert_depth: false,
  gamma: 1.2,
  depth_floor: 0,
  depth_ceiling: 1,
  flatten_background: false,
  background_threshold: 0.15,
  smoothing: 2.5,
  edge_preserve: true,
  detail_blend: 0.12,
  edge_taper_mm: 0,
  resolution: 1024,
  decimate_ratio: 0,
  output_format: "stl",
};
test("all original fields retain exact ranges, including full flatten threshold", () => {
  assert.equal(FIELDS.length, 18);
  assert.deepEqual(
    FIELDS.map((f) => f.id).sort(),
    Object.keys(defaults).sort(),
  );
  assert.equal(
    changeParam(defaults, "background_threshold", 0.95).background_threshold,
    0.95,
  );
  assert.equal(
    changeParam(defaults, "model_width_mm", 187.125).model_width_mm,
    187.125,
  );
  assert.throws(() => changeParam(defaults, "depth_floor", 1), /below/);
  assert.throws(() => changeParam(defaults, "gamma", NaN), /number/);
  assert.equal(changeParam(defaults, "gamma", 9).gamma, 5);
});
test("export quality names map only to the three supported resolutions", () =>
  assert.deepEqual(
    QUALITY.map((v) => v.value),
    [512, 1024, 2048],
  ));
test("default and fallback models must already be installed and permitted", () => {
  const models = [
    { model_id: "restricted", selectable: false },
    { model_id: "missing", selectable: false },
    { model_id: "small", selectable: true },
  ];
  assert.equal(chooseModel(models, "missing"), "small");
  assert.equal(chooseModel(models, "restricted"), "small");
  assert.equal(chooseModel(models, "small"), "small");
  assert.equal(chooseModel(models.slice(0, 2), "missing"), null);
});
test("project and generation tokens invalidate old previews even after returning to the same project", () => {
  const scope = createScope(),
    first = scope.enter("tiger");
  scope.enter("face");
  const returned = scope.enter("tiger");
  assert.equal(scope.current(first), false);
  assert.equal(scope.current(returned), true);
});
test("queued writes finish in order and a failed write prevents silent project-switch flush", async () => {
  const queue = serialQueue(),
    order = [];
  let release;
  const gate = new Promise((r) => (release = r));
  const one = queue.run(async () => {
    await gate;
    order.push("first");
  });
  const two = queue.run(async () => order.push("second"));
  release();
  await Promise.all([one, two]);
  await queue.flush();
  assert.deepEqual(order, ["first", "second"]);
  await assert.rejects(
    queue.run(async () => {
      throw new Error("stale revision");
    }),
  );
  await assert.rejects(queue.flush(), /stale/);
  queue.clearError();
  await queue.flush();
});
test("reselecting an active model keeps previews ready; imported sources survive model changes", () => {
  assert.deepEqual(modelTransition("small", "small", "ai", true), {
    changed: false,
    ready: true,
  });
  assert.deepEqual(modelTransition("small", "large", "ai", true), {
    changed: true,
    ready: false,
  });
  assert.deepEqual(modelTransition("small", "large", "imported", true), {
    changed: true,
    ready: true,
  });
});
test("a preset label reflects real backend settings and becomes Custom after a manual adjustment", () => {
  const editor = { sculpt_strength: 0.25, texture_guard: 0.85 };
  const params = {
    ...defaults,
    gamma: 1.1,
    smoothing: 1.8,
    detail_blend: 0.04,
  };
  assert.equal(savedPreset({ preset: "Portrait" }, params, editor), "Portrait");
  assert.equal(
    savedPreset({ preset: "Portrait" }, { ...params, gamma: 1.3 }, editor),
    "Custom",
  );
});
