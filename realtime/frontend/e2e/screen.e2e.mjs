// End to end check of the interpreter screen in headless Chrome.
//
// Starts the backend with the public-domain KJV sample on a free port, opens
// /ui/screen/, and plays synthetic speech segments into the server from a
// second WebSocket, the way a speech source would. Needs uv and Chrome.
//
//   cd realtime/frontend && npm install && npm run e2e
//   CHROME_PATH=/path/to/chrome npm run e2e
//   SCREENSHOT_DIR=/tmp/shots npm run e2e     (save screenshots)

import { spawn } from "node:child_process";
import { existsSync, mkdtempSync } from "node:fs";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import puppeteer from "puppeteer-core";

const HERE = dirname(fileURLToPath(import.meta.url));
const BACKEND = resolve(HERE, "../../backend");
const SAMPLE = resolve(HERE, "../../../data/sample/kjv.js");
const CHROMES = [
  process.env.CHROME_PATH,
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/usr/bin/google-chrome",
  "/usr/bin/google-chrome-stable",
  "/usr/bin/chromium",
  "/usr/bin/chromium-browser",
].filter(Boolean);

function freePort() {
  return new Promise((ok) => {
    const s = createServer();
    s.listen(0, "127.0.0.1", () => {
      const { port } = s.address();
      s.close(() => ok(port));
    });
  });
}

async function startServer(port) {
  const env = {
    ...process.env,
    BIBLE_TEXT_PATH: process.env.E2E_BIBLE_TEXT ?? SAMPLE,
    LIVEVERSE_LOG_DIR: mkdtempSync(join(tmpdir(), "lv-e2e-")),
  };
  const proc = spawn(
    "uv",
    ["run", "--frozen", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", String(port)],
    { cwd: BACKEND, env, stdio: ["ignore", "ignore", "pipe"] },
  );
  let log = "";
  proc.stderr.on("data", (d) => (log += d));
  for (let i = 0; i < 120; i++) {
    try {
      const res = await fetch(`http://127.0.0.1:${port}/api/health`);
      if (res.ok) return proc;
    } catch {
      /* not up yet */
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  proc.kill();
  throw new Error(`server did not start:\n${log}`);
}

const checks = [];
function check(name, ok, detail = "") {
  checks.push({ name, ok });
  console.log(`${ok ? "ok  " : "FAIL"} ${name}${ok || !detail ? "" : `: ${detail}`}`);
}

async function main() {
  const chrome = CHROMES.find((p) => existsSync(p));
  if (!chrome) throw new Error("Chrome not found; set CHROME_PATH");
  const port = await freePort();
  const server = await startServer(port);
  const base = `http://127.0.0.1:${port}`;
  const browser = await puppeteer.launch({ executablePath: chrome, headless: true, args: ["--no-sandbox"] });
  const shots = process.env.SCREENSHOT_DIR;
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on("pageerror", (e) => errors.push(String(e)));
    page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
    await page.setViewport({ width: 1280, height: 800 });
    await page.goto(`${base}/ui/screen/`, { waitUntil: "networkidle0" });
    await page.waitForFunction(() => document.getElementById("conn").textContent === "connected");
    check("connects to the server", true);
    check("starts empty", await page.$eval("#empty", (e) => !e.hidden));

    // A synthetic speech source in the page: a second WebSocket.
    await page.evaluate(
      (url) =>
        new Promise((ok) => {
          window.src = new WebSocket(url);
          window.src.onopen = ok;
          window.say = (seq, text, final) =>
            window.src.send(JSON.stringify({ type: "transcript", seq, text, is_final: final, t_client: Date.now() / 1000 }));
        }),
      `ws://127.0.0.1:${port}/ws`,
    );
    const title = () => page.$eval("#title-en", (e) => e.textContent);
    const waitTitle = (t) => page.waitForFunction((t) => document.getElementById("title-en").textContent === t, { timeout: 5000 }, t);

    await page.evaluate(() => window.say(1, "요한복음 3장 16절 말씀입니다", true));
    await waitTitle("John 3:16");
    check("a final shows the passage", (await title()) === "John 3:16");
    const verse = await page.$eval('#verses .row[data-verse="16"] .en', (e) => e.textContent);
    check("the verse text is shown", verse.includes("God so loved"), verse);
    check("source is marked", (await page.$eval("#marks .source", (e) => e.textContent)) === "said");
    if (shots) await page.screenshot({ path: join(shots, "screen-light.png") });

    // Interim display: a stable verse in interim results, marked, then confirmed.
    await page.evaluate(() => {
      window.say(2, "로마서 8장 28절", false);
      window.say(2, "로마서 8장 28절 말씀", false);
    });
    await waitTitle("Romans 8:28");
    check("a stable interim shows the verse", true);
    check("it is marked interim", await page.$eval("#passage", (e) => e.classList.contains("interim")));
    check("with an interim pill", Boolean(await page.$("#marks .pill.interim")));
    if (shots) await page.screenshot({ path: join(shots, "screen-interim.png") });
    await page.evaluate(() => window.say(2, "로마서 8장 28절 말씀입니다", true));
    await page.waitForFunction(() => !document.getElementById("passage").classList.contains("interim"));
    check("the final removes the mark", true);

    // Out of range: the screen stays, a guess appears among the alternatives.
    await page.evaluate(() => window.say(3, "로마서 17장 1절", true));
    await page.waitForFunction(() => document.getElementById("alternatives").textContent.includes("guess"));
    check("out of range keeps the screen", (await title()) === "Romans 8:28");
    check("and lists a guess", true);

    // Keyboard: 1 shows the first alternative, Esc clears, / searches.
    await page.keyboard.press("1");
    await page.waitForFunction(() => document.getElementById("title-en").textContent !== "Romans 8:28");
    check("key 1 switches to the first alternative", (await title()) !== "Romans 8:28", await title());
    check("a switch is marked manual", (await page.$eval("#marks .source", (e) => e.textContent)) === "manual");
    await page.keyboard.press("Escape");
    await page.waitForFunction(() => !document.getElementById("empty").hidden);
    check("Esc clears the screen", true);
    await page.keyboard.press("/");
    check("/ focuses search", await page.evaluate(() => document.activeElement.id === "search"));
    await page.keyboard.type("요 3:16");
    await page.keyboard.press("Enter");
    await waitTitle("John 3:16");
    check("search shows the passage", true);

    // Text size, theme, help.
    const size = () => page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue("--verse-size").trim());
    const before = await size();
    await page.keyboard.press("+");
    check("+ makes the text larger", (await size()) !== before, `${before} -> ${await size()}`);
    await page.keyboard.press("t");
    const theme = await page.evaluate(() => document.documentElement.dataset.theme);
    check("T switches the theme", theme === "dark" || theme === "light", theme);
    await page.evaluate(() => {
      document.documentElement.dataset.theme = "dark";
    });
    const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
    check("dark theme has a dark background", bg === "rgb(20, 20, 19)", bg);
    if (shots) await page.screenshot({ path: join(shots, "screen-dark.png") });
    await page.keyboard.press("?");
    check("? opens the shortcut list", await page.$eval("#help", (e) => e.classList.contains("open")));
    await page.keyboard.press("Escape");

    // Speech status from /api/stt.
    await page.waitForFunction(
      () => {
        const t = document.getElementById("stt").textContent;
        return t === "hearing speech" || t.startsWith("quiet");
      },
      { timeout: 6000 },
    );
    const stt = await page.$eval("#stt", (e) => e.textContent);
    check("speech status follows the segments", stt === "hearing speech" || stt.startsWith("quiet"), stt);

    // Phone width: no sideways scrolling.
    await page.setViewport({ width: 375, height: 740 });
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    check("no horizontal scroll at 375 px", overflow <= 0, `${overflow}px`);
    if (shots) await page.screenshot({ path: join(shots, "screen-phone.png"), fullPage: true });

    check("no page errors", errors.length === 0, errors.join(" | "));
  } finally {
    await browser.close();
    server.kill();
  }
  const failed = checks.filter((c) => !c.ok).length;
  console.log(`${checks.length - failed} passed, ${failed} failed`);
  process.exit(failed ? 1 : 0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
