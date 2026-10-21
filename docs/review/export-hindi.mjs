// Regenerates hindi-review.csv from frontend/src/lib/i18n.jsx:
//   node docs/review/export-hindi.mjs
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(join(here, "../../frontend/src/lib/i18n.jsx"), "utf8");

function block(name) {
  const start = src.indexOf(`const ${name} = {`);
  const end = src.indexOf("\n};", start);
  const pairs = [...src.slice(start, end).matchAll(/^\s+"([^"]+)":\s+"((?:[^"\\]|\\.)*)",?$/gm)];
  return Object.fromEntries(pairs.map((m) => [m[1], m[2].replace(/\\"/g, '"')]));
}

const en = block("en");
const hi = block("hi");
const categories = block("categoriesHi");
const quote = (s) => `"${String(s ?? "").replace(/"/g, '""')}"`;

const rows = [["key", "english", "hindi (current)", "reviewer: correct? (Y/N)", "reviewer: better hindi", "reviewer notes"]];
for (const k of Object.keys(en)) rows.push([k, en[k], hi[k] ?? "(MISSING)", "", "", ""]);
for (const [english, hindi] of Object.entries(categories)) rows.push([`category: ${english}`, english, hindi, "", "", ""]);

// BOM so Excel opens the Devanagari correctly.
writeFileSync(join(here, "hindi-review.csv"), "﻿" + rows.map((r) => r.map(quote).join(",")).join("\n") + "\n");
const missing = Object.keys(en).filter((k) => !(k in hi));
console.log(`hindi-review.csv: ${rows.length - 1} strings, ${missing.length} missing${missing.length ? `: ${missing.join(", ")}` : ""}`);
