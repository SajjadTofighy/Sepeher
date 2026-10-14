import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({
  plugins: [react()],
  server: {
    allowedHosts: ["terminal.local"],
    proxy: Object.fromEntries(
      ["/api", "/docs", "/openapi.json", "/swagger"].map((path) => [
        path,
        "http://192.168.10.251:8000",
      ]),
    ),
  },
});
