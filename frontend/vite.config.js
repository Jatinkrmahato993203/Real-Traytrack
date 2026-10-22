import { randomBytes } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import { contentSecurityPolicy } from "./csp.js";

// `vite preview` behaves like production nginx: every HTML response gets a
// fresh random CSP nonce, in both the header and <meta name="csp-nonce">.
function cspNoncePreview(api) {
  return {
    name: "csp-nonce-preview",
    configurePreviewServer(server) {
      server.middlewares.use((req, res, next) => {
        const path = (req.url || "/").split("?")[0];
        const wantsPage = req.headers.accept?.includes("text/html") && !path.startsWith("/assets/") && !/\.\w+$/.test(path);
        if (!wantsPage) return next();
        const nonce = randomBytes(16).toString("hex");
        const html = readFileSync(resolve(server.config.root, server.config.build.outDir, "index.html"), "utf8");
        res.setHeader("Content-Type", "text/html; charset=utf-8");
        res.setHeader("Cache-Control", "no-cache");
        res.setHeader("Content-Security-Policy", contentSecurityPolicy(api, nonce));
        res.end(html.replaceAll("__CSP_NONCE__", nonce));
      });
    },
  };
}

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const api = env.VITE_API_BASE?.startsWith("http") ? new URL(env.VITE_API_BASE).origin : "";
  return {
    plugins: [react(), cspNoncePreview(api)],
    // Unit tests only; browser tests live in e2e/ and run with Playwright.
    test: { include: ["src/**/*.test.{js,jsx}"] },
    // The dev server needs inline scripts for hot reload, so the CSP is only
    // applied to `vite preview` (the built app), like production.
    preview: {
      headers: {
        "Content-Security-Policy": contentSecurityPolicy(api),
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "strict-origin-when-cross-origin",
      },
    },
  };
});
