// Drive the bep-builder web app in headless Chromium and screenshot it.
// Usage: node .claude/skills/run-bep-builder/web.cjs [URL] [OUT_DIR]
//   URL defaults to http://127.0.0.1:8000/ (serve app/ or _site/ there first).
// Flow: load the example plan -> check progress -> open 05 Process -> run the
// NCS name checker on 09 Standards. Exits 1 on any failed check or page error.
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

const url = process.argv[2] || "http://127.0.0.1:8000/";
const out = process.argv[3] || "/tmp/bep-shots";
fs.mkdirSync(out, { recursive: true });

(async () => {
  const exe = fs.existsSync("/opt/pw-browsers/chromium") ? "/opt/pw-browsers/chromium" : undefined;
  const browser = await chromium.launch({ executablePath: exe, args: ["--no-sandbox"] });
  const page = await (await browser.newContext({ viewport: { width: 1400, height: 900 } })).newPage();
  const errors = [];
  page.on("pageerror", e => errors.push(String(e)));
  page.on("console", m => { if (m.type() === "error") errors.push(m.text()); });
  const shot = async name => { const f = path.join(out, name); await page.screenshot({ path: f, fullPage: false }); console.log("screenshot", f); };
  const fail = msg => { console.error("FAIL", msg); process.exitCode = 1; };

  await page.goto(url);
  await page.waitForSelector("#progress-text");
  console.log("banner:", (await page.textContent("#banner")).trim().slice(0, 80));
  await shot("01-start.png");

  // Load example: a fresh browser goes straight in; a non-empty plan asks to confirm first.
  await page.click('[data-action="example"]');
  const confirm = page.locator('[data-action="example-yes"]');
  if (await confirm.count()) await confirm.click();
  await page.waitForFunction(() => document.querySelector("#progress-text").textContent.startsWith("11 of 11"), null, { timeout: 5000 })
    .catch(() => fail("progress never reached 11 of 11"));
  console.log("progress:", await page.textContent("#progress-text"));
  console.log("title block:", (await page.textContent("#tb-project")).trim());
  await shot("02-example-loaded.png");

  await page.click('#index [data-goto="process"]');
  await page.waitForSelector('#index [data-goto="process"][aria-current="step"]');
  await shot("03-process.png");

  await page.click('#index [data-goto="standards"]');
  await page.fill("#checker-input", "A-WALL-FULL a-door AD-101 A-101");
  await page.click('[data-action="check"]');
  const rows = await page.$$eval("#checker-out tr", trs => trs.map(t => [...t.cells].map(c => c.textContent.trim()).join(" | ")));
  rows.forEach(r => console.log("checker:", r));
  if (!rows.some(r => r.startsWith("AD-101") && r.includes("Fix"))) fail("checker did not flag AD-101");
  await page.locator("#checker-out").scrollIntoViewIfNeeded();
  await shot("04-name-checker.png");

  // Serving raw app/ (no <meta charset>) turns "—" into "â€”"; serve the _site build instead.
  if ((await page.textContent("body")).includes("\u00e2\u20ac")) fail("mojibake on the page: serve _site/ (tools/build_pages.py), not app/");
  if (errors.length) fail("page errors: " + errors.join("; "));
  else console.log("no console errors");
  await browser.close();
})();
