const paths = {
  sidebar: "M8 4v16M4 4h16v16H4z",
  plus: "M12 5v14M5 12h14",
  minus: "M5 12h14",
  close: "m6 6 12 12M18 6 6 18",
  folder: "M3 7V5h6l2 2h10v12H3z",
  moon: "M20 15a8 8 0 0 1-11-11A8 8 0 1 0 20 15",
  sun: "M12 2v2m0 16v2M2 12h2m16 0h2M5 5l2 2m10 10 2 2M5 19l2-2M17 7l2-2M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0",
  settings:
    "M9 3h6l1 3 3 1 2 5-2 5-3 1-1 3H9l-1-3-3-1-2-5 2-5 3-1zM15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0",
  help: "M12 17h.01M9 9a3 3 0 0 1 6 0c0 2-3 2-3 5M22 12A10 10 0 1 1 2 12a10 10 0 0 1 20 0",
  export: "M12 15V3m-4 4 4-4 4 4M4 14v6h16v-6",
  upload: "M12 16V4m-5 5 5-5 5 5M4 16v5h16v-5",
  layers: "m3 8 9-5 9 5-9 5zM3 12l9 5 9-5M3 16l9 5 9-5",
  compare: "M12 3v18M4 5h16v14H4z",
  sliders: "M4 7h16M4 17h16M8 4v6M16 14v6",
  chevron: "m9 5 7 7-7 7",
  undo: "M8 6 3 11l5 5M3 11h11a6 6 0 0 1 6 6",
  redo: "m16 6 5 5-5 5M21 11H10a6 6 0 0 0-6 6",
  fit: "M4 9V4h5m6 0h5v5M4 15v5h5m6 0h5v-5",
  reset: "M4 10a8 8 0 1 1 1 8M4 4v6h6",
  top: "M4 4h16v16H4zM8 8h8v8H8z",
  more: "M5 12h.01M12 12h.01M19 12h.01",
  isolate:
    "M4 8V4h4m8 0h4v4M4 16v4h4m8 0h4v-4M12 7a3 3 0 0 1 3 3v2c0 3 3 3 3 5H6c0-2 3-2 3-5v-2a3 3 0 0 1 3-3",
  keep: "M12 4a8 8 0 1 0 0 16 8 8 0 0 0 0-16M8 12h8m-4-4v8",
  remove: "M12 4a8 8 0 1 0 0 16 8 8 0 0 0 0-16M8 12h8",
  rectangle: "M4 4h16v16H4z",
  raise: "m6 12 6-6 6 6M12 6v14",
  lower: "m6 12 6 6 6-6M12 18V4",
  smooth: "M3 15c4-12 6 8 10-3s6 3 8-3",
  flatten: "M4 12h16M8 5l4 4 4-4M8 19l4-4 4 4",
};
export function icon(name) {
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] ? `<path d="${paths[name]}"/>` : ""}</svg>`;
}
export function renderIcons(root = document) {
  for (const el of root.querySelectorAll("[data-icon]"))
    el.innerHTML = icon(el.dataset.icon);
}
