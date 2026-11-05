// Applied before the first paint to avoid a light flash. No network or telemetry.
try {
  document.documentElement.dataset.theme =
    localStorage.getItem("relief-theme") === "light" ? "light" : "dark";
} catch {
  document.documentElement.dataset.theme = "dark";
}
