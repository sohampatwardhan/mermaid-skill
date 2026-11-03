#!/usr/bin/env node
// Parse-only Mermaid validator. Loads the pinned Mermaid 12.0.0 once and calls
// mermaid.parse() on every diagram of a batch in this one process — no browser, no
// render. A diagram is valid when mermaid.parse() resolves; a parse error rejects it
// with the parser's own line number and message.
//
// Protocol (keeps the whole batch in one Node start, so the cost is one import). The output is
// line-based so check.sh can read it with plain shell — no second Node process:
//   stdin : JSON { "diagrams": [ { "id": <int>, "source": "<mermaid text>" }, ... ] }
//   stdout: one line per diagram, in input order:
//             OK <id>
//             FAIL <id> <line|-> <message>        (line is the parser's line, or - when none)
//           plus, on a batch-level problem, a single line:
//             BATCHERROR <message>
//   exit  : 0 when every diagram parsed, 1 when any failed, 2 on a bad batch or a missing
//           dependency (mermaid / jsdom). ids are integers and messages are single-line, so a
//           result line splits cleanly on spaces into id, line, and the rest as the message.
//
// Mermaid 12 is ESM and expects a browser environment even for parsing: the sequence parser
// reaches for `Option` (window.Option), external diagrams reach for `location`,
// `localStorage`, and so on. A minimal jsdom window is installed on globalThis before mermaid
// is imported, and every window-owned global jsdom provides is mirrored onto globalThis so the
// parsers find them. `@mermaid-js/mermaid-zenuml` is registered when present so the one
// external diagram the catalog documents also parses. mermaid, jsdom, and the zenuml plugin
// are resolved from MERMAID_PARSE_NODE_MODULES when set (check.sh points this at the pinned
// install), else from this script's own resolution paths.

import { existsSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

function oneLine(text) {
  return String(text == null ? "" : text).replace(/[\r\n]+/g, " ").trim();
}

function fail(message) {
  process.stdout.write("BATCHERROR " + oneLine(message) + "\n");
  process.exit(2);
}

// Resolve dependencies from a caller-provided node_modules first, then from here.
function resolver() {
  const base = process.env.MERMAID_PARSE_NODE_MODULES;
  if (base) {
    return createRequire(pathToFileURL(base.replace(/\/?$/, "/") + "package.json"));
  }
  return createRequire(import.meta.url);
}

// The ESM entry file URL for a package, as an import() specifier. These packages ship
// `exports` with only an `import` condition (no CJS `require`), so require.resolve() fails on
// them; the entry is read from package.json instead. `nodeModules` is the directory holding
// the package; when null the require()-visible resolution is used (dev install next to this
// script). Returns null when the package is not installed.
function esmEntry(name, nodeModules) {
  const dir = nodeModules ? join(nodeModules, ...name.split("/")) : null;
  const pkgPath = dir ? join(dir, "package.json") : null;
  if (pkgPath && existsSync(pkgPath)) {
    const pkg = JSON.parse(readFileSync(pkgPath, "utf8"));
    const dot = pkg.exports && pkg.exports["."];
    const rel =
      (dot && (dot.import || dot.default)) ||
      (typeof pkg.exports === "string" ? pkg.exports : null) ||
      pkg.module ||
      pkg.main;
    if (!rel) return null;
    return pathToFileURL(join(dir, rel)).href;
  }
  return null;
}

// Install a jsdom window and mirror its globals onto globalThis. Mermaid's parsers assume a
// browser: without `window.Option` the sequence `box` parser throws "Option is not defined",
// and external diagrams need `location` and `localStorage`. The url and storage quota make
// those real objects rather than stubs that throw on use.
function installDom(require) {
  let JSDOM;
  try {
    ({ JSDOM } = require("jsdom"));
  } catch (e) {
    fail("cannot load jsdom: " + (e && e.message ? e.message : e));
  }
  const dom = new JSDOM("<!DOCTYPE html><html><body></body></html>", {
    pretendToBeVisual: true,
    url: "http://localhost/",
    storageQuota: 10_000_000,
  });
  const w = dom.window;
  globalThis.window = w;
  globalThis.document = w.document;
  for (const key of Object.getOwnPropertyNames(w)) {
    if (key === "window" || key === "document") continue;
    if (globalThis[key] !== undefined) continue;
    try {
      const descriptor = Object.getOwnPropertyDescriptor(w, key);
      if (!descriptor) continue;
      Object.defineProperty(globalThis, key, { value: w[key], writable: true, configurable: true });
    } catch {
      // A property jsdom refuses to re-bind (rare) is left alone; the parsers do not need it.
    }
  }
}

function readBatch() {
  let raw;
  try {
    raw = readFileSync(0, "utf8");
  } catch (e) {
    fail("could not read the batch from stdin: " + (e && e.message ? e.message : e));
  }
  let batch;
  try {
    batch = JSON.parse(raw);
  } catch (e) {
    fail("batch is not valid JSON: " + (e && e.message ? e.message : e));
  }
  if (!batch || !Array.isArray(batch.diagrams)) {
    fail('batch must be a JSON object with a "diagrams" array');
  }
  return batch.diagrams;
}

// The first source line number a parse error points at, or null when it has none.
function errorLine(err) {
  const loc = err && err.hash && err.hash.loc;
  if (loc && Number.isInteger(loc.first_line)) {
    return loc.first_line;
  }
  const m = err && err.message && err.message.match(/\bline (\d+)\b/i);
  return m ? Number(m[1]) : null;
}

function errorMessage(err) {
  if (!err) return "unknown parse error";
  const first = String(err.message || err).split("\n")[0].trim();
  return first || "unknown parse error";
}

async function main() {
  const diagrams = readBatch();
  const require = resolver();
  const nodeModules = process.env.MERMAID_PARSE_NODE_MODULES || null;
  installDom(require);

  let mermaid;
  try {
    const mermaidEntry = esmEntry("mermaid", nodeModules);
    mermaid = (await import(mermaidEntry || "mermaid")).default;
  } catch (e) {
    fail("cannot load mermaid: " + (e && e.message ? e.message : e));
  }

  // Register zenuml, the one external diagram the catalog documents, when its plugin is
  // installed. Core Mermaid does not know `zenuml` on its own. A missing or broken plugin is
  // not fatal: a zenuml diagram then reports "No diagram type detected", which is an honest
  // parse failure rather than a crash of the whole batch.
  try {
    const zenumlEntry = esmEntry("@mermaid-js/mermaid-zenuml", nodeModules);
    if (zenumlEntry) {
      const { default: zenuml } = await import(zenumlEntry);
      await mermaid.registerExternalDiagrams([zenuml]);
    }
  } catch {
    // zenuml plugin unavailable; leave it unregistered.
  }

  mermaid.initialize({ startOnLoad: false, suppressErrorRendering: true });

  const lines = [];
  let anyFailed = false;
  for (const diagram of diagrams) {
    const id = diagram && Number.isInteger(diagram.id) ? diagram.id : 0;
    const source = diagram && typeof diagram.source === "string" ? diagram.source : "";
    try {
      await mermaid.parse(source);
      lines.push("OK " + id);
    } catch (err) {
      anyFailed = true;
      const line = errorLine(err);
      lines.push(`FAIL ${id} ${line == null ? "-" : line} ${oneLine(errorMessage(err))}`);
    }
  }

  process.stdout.write(lines.join("\n") + (lines.length ? "\n" : ""));
  process.exit(anyFailed ? 1 : 0);
}

main().catch((e) => {
  fail("unexpected failure: " + (e && e.stack ? e.stack.split("\n")[0] : e));
});
