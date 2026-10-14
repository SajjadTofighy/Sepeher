// Fast, deterministic production packaging. Vite remains the development server.
import { build } from "esbuild";
import { rm, mkdir, readFile, writeFile, cp } from "node:fs/promises";
await rm("dist", { recursive: true, force: true });
await mkdir("dist/assets", { recursive: true });
await build({
  entryPoints: { main: "src/main.tsx" },
  outdir: "dist/assets",
  bundle: true,
  minify: true,
  splitting: true,
  format: "esm",
  target: "es2022",
  jsx: "automatic",
  entryNames: "[name]",
  chunkNames: "chunks/[name]-[hash]",
  assetNames: "[name]-[hash]",
  loader: { ".woff": "file", ".woff2": "file", ".ttf": "file", ".svg": "file" },
  define: { "process.env.NODE_ENV": '"production"' },
  metafile: true,
}).then((r) => writeFile("dist/build-meta.json", JSON.stringify(r.metafile)));
await cp("public", "dist", { recursive: true });
await mkdir("dist/swagger", { recursive: true });
for (const f of ["swagger-ui-bundle.js", "swagger-ui.css"])
  await cp("node_modules/swagger-ui-dist/" + f, "dist/swagger/" + f);
const html = (await readFile("index.html", "utf8")).replace(
  '<script type="module" src="/src/main.tsx"></script>',
  '<link rel="stylesheet" href="/assets/main.css"/><script type="module" src="/assets/main.js"></script>',
);
await writeFile("dist/index.html", html);
console.log("Production bundle ready in frontend/dist");
