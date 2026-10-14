import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const venv = resolve(
  root,
  process.platform === "win32"
    ? ".venv/Scripts/python.exe"
    : ".venv/bin/python",
);
const python =
  process.env.SEPHER_PYTHON ||
  (existsSync(venv)
    ? venv
    : process.platform === "win32"
      ? "python"
      : "python3");
const children = [];
const demo = process.argv.includes("--demo");
let exiting = false;
function start(cmd, args, cwd) {
  const child = spawn(cmd, args, {
    cwd,
    stdio: "inherit",
    env: {
      ...process.env,
      ...(demo ? { SEPEHR_AUTH_MODE: "demo" } : {}),
      PYTHONPATH: [
        resolve(root, ".preview-deps"),
        process.env.PYTHONPATH || "",
      ].join(process.platform === "win32" ? ";" : ":"),
    },
  });
  children.push(child);
  child.on("error", (e) => {
    console.error(e.message);
    stop(1);
  });
  child.on("exit", (code) => {
    if (!exiting) stop(code || 0);
  });
  return child;
}
function stop(code = 0) {
  if (exiting) return;
  exiting = true;
  children.forEach((c) => c.kill("SIGTERM"));
  setTimeout(() => process.exit(code), 400);
}
start(
  python,
  [
    "-m",
    "uvicorn",
    "app.main:app",
    "--app-dir",
    resolve(root, "backend"),
    "--host",
    "0.0.0.0",
    "--port",
    "8000",
  ],
  root,
);
start(
  process.execPath,
  [
    resolve(root, "frontend/node_modules/vite/bin/vite.js"),
    ...process.argv.slice(2).filter(arg => arg !== "--demo"),
  ],
  resolve(root, "frontend"),
);
process.on("SIGINT", () => stop());
process.on("SIGTERM", () => stop());
