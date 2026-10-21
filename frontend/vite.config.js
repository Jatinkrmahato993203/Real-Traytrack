import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import { contentSecurityPolicy } from "./csp.js";

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const api = env.VITE_API_BASE?.startsWith("http") ? new URL(env.VITE_API_BASE).origin : "";
  return {
    plugins: [react()],
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
