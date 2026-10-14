import { spawnSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const action = process.argv[2];
function productionSettings() {
  const settings = {};
  for (const line of readFileSync(resolve(root, ".env"), "utf8").split(/\r?\n/)) {
    const match = line.match(/^([A-Z0-9_]+)=(.*)$/);
    if (match) settings[match[1]] = match[2];
  }
  Object.assign(settings, process.env);
  const registry = settings.SEPEHR_INTERNAL_REGISTRY;
  if (!registry || !/^[a-z0-9.-]+(?::[0-9]+)?$/.test(registry)) throw new Error("مخزن داخلی مصوب را مشخص کنید");
  for (const key of ["SEPEHR_KEYCLOAK_PRODUCTION_IMAGE", "SEPEHR_POSTGRES_PRODUCTION_IMAGE"]) {
    const image = settings[key] || "";
    if (!image.startsWith(registry + "/") || !/@sha256:[a-f0-9]{64}$/.test(image)) throw new Error(`${key}: ایمیج مخزن داخلی با digest مصوب لازم است`);
  }
  for (const key of ["SEPEHR_APP_HOSTNAME", "SEPEHR_IDENTITY_HOSTNAME", "SEPEHR_ADMIN_HOSTNAME"]) {
    if (!/^[a-zA-Z0-9.-]+$/.test(settings[key] || "")) throw new Error(`${key}: hostname دقیق لازم است`);
  }
  if (new Set([settings.SEPEHR_APP_HOSTNAME, settings.SEPEHR_IDENTITY_HOSTNAME, settings.SEPEHR_ADMIN_HOSTNAME]).size !== 3) throw new Error("hostnameهای برنامه، هویت و مدیریت باید مستقل باشند");
  const privateAddress = value => {
    const parts = value.split(".").map(Number);
    if (parts.length !== 4 || parts.some(n => !Number.isInteger(n) || n < 0 || n > 255)) return false;
    return parts[0] === 10 || parts[0] === 127 || (parts[0] === 192 && parts[1] === 168) || (parts[0] === 172 && parts[1] >= 16 && parts[1] <= 31);
  };
  if (!privateAddress(settings.SEPEHR_MANAGEMENT_BIND_IP || "")) throw new Error("آدرس اتصال مدیریت باید خصوصی باشد");
  const [address, mask] = (settings.SEPEHR_MANAGEMENT_CIDR || "").split("/");
  const minimum = address?.startsWith("192.168.") ? 16 : address?.startsWith("172.") ? 12 : 8;
  if (!privateAddress(address || "") || !/^\d+$/.test(mask || "") || Number(mask) < minimum || Number(mask) > 32) throw new Error("CIDR شبکه مدیریت باید خصوصی و محدود باشد");
}
const commands = {
  build: ["build", "backend", "frontend"],
  up: ["up", "--build", "--detach", "--wait", "--wait-timeout", "300"],
  down: ["down"],
  logs: ["logs", "--follow", "--tail", "100"],
  config: ["config", "--quiet"],
};
if (action === "init") {
  const template = readFileSync(resolve(root, ".env.example"), "utf8");
  const content = template.replace(/^(KEYCLOAK_(?:ADMIN|DB)_PASSWORD)=$/gm,
    (_, key) => `${key}=${randomBytes(32).toString("hex")}`);
  try {
    writeFileSync(resolve(root, ".env"), content, { flag: "wx", mode: 0o600 });
    console.log("فایل .env با رمزهای تصادفی ساخته شد؛ رمزها را در مخزن ثبت نکنید.");
  } catch (error) {
    if (error.code !== "EEXIST") throw error;
    console.log("فایل .env موجود است و تغییر نکرد.");
  }
} else if (commands[action]) {
  const result = spawnSync("docker", ["compose", "--project-directory", root,
    "--file", resolve(root, "compose.yaml"), ...commands[action]], {
    cwd: root, stdio: "inherit",
  });
  if (result.error) console.error(result.error.message);
  process.exit(result.status ?? 1);
} else if (["production-check", "production-pull"].includes(action)) {
  try { productionSettings(); }
  catch (error) { console.error(error.message); process.exit(2); }
  const result = spawnSync("docker", ["compose", "--project-directory", root,
    "--file", resolve(root, "compose.yaml"), "--file", resolve(root, "deploy/compose.production.yaml"),
    ...(action === "production-check" ? ["config", "--quiet"] : ["pull", "postgres", "keycloak"])], { cwd: root, stdio: "inherit" });
  if (result.error) console.error(result.error.message);
  process.exit(result.status ?? 1);
} else {
  console.error("Usage: node scripts/compose.mjs init|build|up|down|logs|config|production-check|production-pull");
  process.exit(2);
}
