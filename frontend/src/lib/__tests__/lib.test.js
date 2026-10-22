// @vitest-environment jsdom
import { readFileSync } from "node:fs";
import { describe, expect, it, beforeEach } from "vitest";
import { formatDate, formatDateTime, parseUtc, timeAgo } from "../time";
import { currentMeal } from "../meal";
import { contentSecurityPolicy } from "../../../csp.js";

describe("time", () => {
  beforeEach(() => { document.documentElement.lang = "en"; });

  it("treats server timestamps without a zone as UTC", () => {
    expect(parseUtc("2026-10-21 13:53:32").toISOString()).toBe("2026-10-21T13:53:32.000Z");
    expect(parseUtc("2026-10-21T13:53:32").toISOString()).toBe("2026-10-21T13:53:32.000Z");
    expect(parseUtc("2026-10-21T13:53:32+05:30").toISOString()).toBe("2026-10-21T08:23:32.000Z");
  });

  it("formats calendar dates without shifting the day across time zones", () => {
    expect(formatDate("2026-11-03")).toMatch(/3 Nov 2026/);
  });

  it("never throws on missing or odd values", () => {
    expect(formatDateTime(null)).toBe("—");
    expect(formatDate("")).toBe("—");
    expect(formatDateTime("not a date")).toBe("not a date");
    expect(timeAgo(undefined)).toBe("");
  });

  it("follows the chosen language", () => {
    const iso = new Date(Date.now() - 2 * 3600e3).toISOString();
    expect(timeAgo(iso)).toBe("2 hours ago");
    document.documentElement.lang = "hi";
    expect(timeAgo(iso)).not.toBe("2 hours ago");
  });
});

describe("meal of the day", () => {
  it("picks the meal being served", () => {
    const at = (h) => currentMeal(new Date(2026, 0, 1, h));
    expect([at(8), at(13), at(17), at(21)]).toEqual(["breakfast", "lunch", "snacks", "dinner"]);
  });
});

describe("translations", () => {
  const src = readFileSync("src/lib/i18n.jsx", "utf8");   // tests run from frontend/
  const keys = (name) => {
    const start = src.indexOf(`const ${name} = {`);
    return [...src.slice(start, src.indexOf("\n};", start)).matchAll(/^\s+"([^"]+)":/gm)].map((m) => m[1]);
  };

  it("has a Hindi string for every English one (and no extras)", () => {
    const en = keys("en");
    const hi = keys("hi");
    expect(en.length).toBeGreaterThan(100);
    expect(en.filter((k) => !hi.includes(k))).toEqual([]);
    expect(hi.filter((k) => !en.includes(k))).toEqual([]);
  });

  it("keeps placeholders identical across languages", () => {
    const pairs = (name) => Object.fromEntries([...src.slice(src.indexOf(`const ${name} = {`)).split("\n};")[0]
      .matchAll(/^\s+"([^"]+)":\s+"((?:[^"\\]|\\.)*)"/gm)].map((m) => [m[1], m[2]]));
    const en = pairs("en");
    const hi = pairs("hi");
    for (const k of Object.keys(en)) {
      const ph = (s) => (s.match(/\{\w+\}/g) || []).sort().join();
      expect(ph(hi[k]), `placeholders in ${k}`).toBe(ph(en[k]));
    }
  });
});

describe("content security policy", () => {
  const csp = contentSecurityPolicy("http://localhost:8002");
  it("blocks inline scripts and plugins, allows only what the app uses", () => {
    expect(csp).toMatch(/script-src 'self' https:\/\/accounts\.google\.com\/gsi\/client;/);
    expect(csp).not.toMatch(/script-src[^;]*'unsafe-inline'/);
    expect(csp).toMatch(/object-src 'none'/);
    expect(csp).toMatch(/frame-ancestors 'none'/);
    expect(csp).toMatch(/connect-src[^;]*http:\/\/localhost:8002/);
  });
  it("lets only the nonce'd <style> block through", () => {
    const withNonce = contentSecurityPolicy("", "abc123");
    expect(withNonce).toMatch(/style-src-elem [^;]*'nonce-abc123'/);
    expect(contentSecurityPolicy()).not.toMatch(/nonce-/);
  });
  it("only allows inline style attributes, not inline <style> blocks", () => {
    expect(csp).toMatch(/style-src-attr 'unsafe-inline'/);
    expect(csp).not.toMatch(/style-src-elem[^;]*'unsafe-inline'/);
  });
});
