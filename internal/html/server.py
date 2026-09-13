from html import escape
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from itertools import groupby
import json
import os
from pathlib import Path
import sys
from urllib.parse import quote, unquote, urlsplit

ROOT = Path("/srv/html").resolve()
LEGACY_ROOT = ROOT / "01204512-Design-and-Analysis-of-Algorithms"
SYNC_STATE = Path("/runtime/syncthing.json")
MODE = os.environ.get("MODE", "content")
SITE_TITLE = os.environ.get("TITLE", "HTML Learning Materials")
# pages need their own images/styles; anything else (PDF, .md, source) stays hidden
ASSET_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico",
                  ".css", ".js", ".woff", ".woff2"}

DASHBOARD = """
<aside class="dashboard" aria-labelledby="sync-title">
  <div class="dashboard-head"><h2 id="sync-title">Syncthing</h2><span id="sync-state">Loading…</span></div>
  <progress id="sync-progress" max="100" value="0"></progress>
  <p id="sync-summary">Reading sync status…</p>
  <div class="sync-metrics">
    <p><strong id="sync-local">—</strong><span>Local data</span></p>
    <p><strong id="sync-global">—</strong><span>Global data</span></p>
    <p><strong id="sync-pending">—</strong><span>Pending</span></p>
    <p><strong id="sync-errors">—</strong><span>Errors</span></p>
  </div>
  <dl class="sync-times">
    <div><dt>State since</dt><dd id="sync-state-changed">—</dd></div>
    <div><dt>Last checked</dt><dd id="sync-updated">—</dd></div>
  </dl>
  <details class="devices"><summary>Device details</summary><div id="device-list"></div></details>
</aside>
<section class="history" aria-labelledby="history-title">
  <div class="history-head">
    <h2 id="history-title">HTML Transfers Per Day</h2>
    <nav aria-label="Transfer history range">
      <button type="button" data-days="7">7d</button>
      <button type="button" data-days="30" aria-pressed="true">30d</button>
      <button type="button" data-days="0">All</button>
    </nav>
  </div>
  <div class="history-metrics">
    <p><strong id="history-total">0</strong><span>Transfers</span></p>
    <p><strong id="history-average">0</strong><span>Average / day</span></p>
    <p><strong id="history-peak">0</strong><span>Peak / day</span></p>
  </div>
  <div id="history-chart" class="history-chart" aria-label="Daily HTML transfer frequency"></div>
  <p id="history-empty" hidden>No HTML sync events recorded in this range.</p>
  <details class="history-records"><summary>Transfer records</summary>
    <ol id="history-list" class="history-list" aria-label="HTML transfer records"></ol>
  </details>
</section>
<script>
const stateLabel = {idle: "Up to date", scanning: "Scanning", syncing: "Syncing", error: "Unavailable"};
const bytes = value => value < 1024 ? `${value} B` : value < 1048576 ? `${(value / 1024).toFixed(1)} KB` : value < 1073741824 ? `${(value / 1048576).toFixed(1)} MB` : `${(value / 1073741824).toFixed(2)} GB`;
const fileLabel = file => file.split("/").pop().replace(/\\.html$/i, "").split(/[_-]+/).filter(Boolean).map(word => word[0].toUpperCase() + word.slice(1)).join(" ");
const dateTime = value => value ? new Date(value).toLocaleString([], {dateStyle: "medium", timeStyle: "medium"}) : "—";
let historyDays = 30;
let historyItems = [];

function bangkokToday() {
  return new Intl.DateTimeFormat("en-CA", {timeZone: "Asia/Bangkok", year: "numeric", month: "2-digit", day: "2-digit"}).format(new Date());
}

function dayKeys(items) {
  const today = bangkokToday();
  const end = new Date(`${today}T00:00:00Z`);
  const start = historyDays
    ? new Date(end.getTime() - (historyDays - 1) * 86400000)
    : new Date(`${items.map(item => item.day).sort()[0] || today}T00:00:00Z`);
  const keys = [];
  for (const day = new Date(start); day <= end; day.setUTCDate(day.getUTCDate() + 1)) {
    keys.push(day.toISOString().slice(0, 10));
  }
  return keys;
}

function renderHistory() {
  const keys = dayKeys(historyItems);
  const items = historyItems.filter(item => item.day >= keys[0]);
  const counts = new Map(keys.map(day => [day, 0]));
  items.forEach(item => counts.set(item.day, (counts.get(item.day) || 0) + 1));
  const peak = Math.max(0, ...counts.values());
  document.querySelector("#history-total").textContent = items.length;
  document.querySelector("#history-average").textContent = (items.length / keys.length).toFixed(1);
  document.querySelector("#history-peak").textContent = peak;
  document.querySelectorAll("[data-days]").forEach(button => button.setAttribute("aria-pressed", Number(button.dataset.days) === historyDays));

  document.querySelector("#history-chart").replaceChildren(...keys.map((day, index) => {
    const column = document.createElement("div");
    const time = document.createElement("time");
    const track = document.createElement("span");
    const bar = document.createElement("i");
    const value = document.createElement("b");
    const count = counts.get(day);
    const label = new Date(`${day}T00:00:00Z`).toLocaleDateString([], {month: "short", day: "numeric", timeZone: "UTC"});
    time.textContent = keys.length <= 14 || index % 5 === 0 || index === keys.length - 1 ? label : "";
    bar.style.height = count ? `${Math.max(4, 100 * count / peak)}%` : "0";
    value.textContent = count || "";
    track.append(bar);
    column.append(value, track, time);
    column.title = `${label}: ${count} transfer${count === 1 ? "" : "s"}`;
    return column;
  }));

  document.querySelector("#history-list").replaceChildren(...items.slice(0, 50).map(item => {
    const row = document.createElement("li");
    const time = new Date(item.time).toLocaleString([], {dateStyle: "medium", timeStyle: "short"});
    row.textContent = `${time} · ${item.kind} · ${fileLabel(item.file)}`;
    row.title = item.file;
    return row;
  }));
  document.querySelector("#history-empty").hidden = items.length !== 0;
}

document.querySelectorAll("[data-days]").forEach(button => button.addEventListener("click", () => {
  historyDays = Number(button.dataset.days);
  renderHistory();
}));

async function refreshSync() {
  try {
    const data = await fetch("/api/sync", {cache: "no-store"}).then(response => response.json());
    const state = data.available ? data.state : "error";
    document.querySelector("#sync-state").textContent = stateLabel[state] || state;
    document.querySelector("#sync-state").dataset.state = state;
    document.querySelector("#sync-progress").value = data.completion || 0;
    document.querySelector("#sync-summary").textContent = data.available
      ? `${data.completion}% complete · ${data.needFiles} files / ${bytes(data.needBytes)} remaining · ${data.connectedDevices} of ${data.totalDevices || 0} devices connected`
      : "Syncthing status is temporarily unavailable";
    document.querySelector("#sync-local").textContent = `${(data.localFiles || 0).toLocaleString()} files · ${bytes(data.localBytes || 0)}`;
    document.querySelector("#sync-global").textContent = `${(data.globalFiles || 0).toLocaleString()} files · ${bytes(data.globalBytes || 0)}`;
    document.querySelector("#sync-pending").textContent = `${(data.needFiles || 0) + (data.needDirectories || 0) + (data.needDeletes || 0)} items`;
    document.querySelector("#sync-errors").textContent = data.error || `${data.errors || 0}`;
    document.querySelector("#sync-state-changed").textContent = dateTime(data.stateChanged);
    document.querySelector("#sync-updated").textContent = dateTime(data.updatedAt);
    document.querySelector("#device-list").replaceChildren(...(data.devices || []).map(device => {
      const row = document.createElement("p");
      const status = device.paused ? "Paused" : device.connected ? "Connected" : "Disconnected";
      row.innerHTML = `<strong></strong><span></span><small></small>`;
      row.querySelector("strong").textContent = device.name;
      row.querySelector("span").textContent = `${status}${device.clientVersion ? ` · ${device.clientVersion}` : ""}`;
      row.querySelector("small").textContent = `Received ${bytes(device.inBytes || 0)} · Sent ${bytes(device.outBytes || 0)} · Last contact ${dateTime(device.lastSeen)}`;
      row.dataset.connected = device.connected;
      return row;
    }));
    historyItems = data.activities || [];
    renderHistory();
  } catch {
    document.querySelector("#sync-state").textContent = "Unavailable";
  }
}
refreshSync();
setInterval(refreshSync, 3000);
</script>
"""


def display_name(path):
    words = path.stem.replace("_", " ").replace("-", " ").split()
    return " ".join(word[:1].upper() + word[1:] for word in words)


def render_index(files, mode=MODE):
    files = sorted(files, key=lambda path: (path.relative_to(ROOT).parent, path.name))
    sections = []
    for folder, paths in groupby(files, key=lambda path: path.relative_to(ROOT).parent):
        links = "\n".join(
            f'<li><a href="{quote("/" + path.relative_to(ROOT).as_posix(), safe="/")}">'
            f'{escape(display_name(path))}</a></li>'
            for path in paths
        )
        title = "BASE" if folder.as_posix() == "." else escape(folder.as_posix())
        sections.append(f"<section><h2>{title}</h2><ul>{links}</ul></section>")
    sections = "\n".join(sections)
    title = "Syncthing Monitor" if mode == "monitor" else SITE_TITLE
    body = DASHBOARD if mode == "monitor" else sections
    return f"""<!doctype html>
<html lang="th"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
    <style>body{{max-width:70rem;margin:3rem auto;padding:0 1rem;font:1rem/1.6 system-ui,sans-serif}}section{{margin:1.5rem 0}}h2{{margin-bottom:.35rem;font-size:1.05rem;overflow-wrap:anywhere}}ul,ol{{margin:.25rem 0;padding-left:1.4rem}}li{{margin:.2rem 0}}a{{color:#0645ad;text-decoration:none}}a:hover{{text-decoration:underline}}.dashboard,.history{{margin:1.5rem 0;padding:1rem;border:1px solid #ddd;border-radius:.6rem}}.dashboard-head,.history-head{{display:flex;align-items:center;justify-content:space-between;gap:1rem}}.dashboard-head h2,.history-head h2{{margin:0}}#sync-state{{font-weight:600}}#sync-state[data-state="idle"]{{color:#16743a}}#sync-state[data-state="syncing"],#sync-state[data-state="scanning"]{{color:#9a6700}}#sync-state[data-state="error"]{{color:#b42318}}progress{{width:100%;height:.65rem}}#sync-summary{{margin:.5rem 0}}button{{padding:.35rem .6rem;border:1px solid #ccc;border-radius:.4rem;background:white;cursor:pointer}}button[aria-pressed="true"]{{border-color:#0645ad;background:#eef4ff;color:#0645ad}}.sync-metrics,.history-metrics{{display:grid;grid-template-columns:repeat(4,1fr);gap:.75rem;margin:1rem 0}}.sync-metrics p,.history-metrics p{{margin:0;padding:.65rem;background:#f7f7f7;border-radius:.4rem}}.sync-metrics strong,.sync-metrics span,.history-metrics strong,.history-metrics span{{display:block}}.sync-metrics strong{{font-size:.95rem}}.sync-metrics span,.history-metrics span{{font-size:.8rem;color:#666}}.history-metrics{{grid-template-columns:repeat(3,1fr)}}.history-metrics strong{{font-size:1.4rem}}.sync-times{{display:grid;grid-template-columns:repeat(2,1fr);gap:.25rem 1rem;font-size:.85rem}}.sync-times div{{display:flex;gap:.5rem}}.sync-times dt{{color:#666}}.sync-times dd{{margin:0}}.devices summary{{cursor:pointer;font-weight:600}}#device-list p{{display:grid;grid-template-columns:1fr auto;margin:.6rem 0;padding:.65rem;background:#f7f7f7;border-left:.25rem solid #b42318}}#device-list p[data-connected="true"]{{border-color:#16743a}}#device-list span{{font-size:.85rem}}#device-list small{{grid-column:1/-1;color:#666}}.history-chart{{display:flex;align-items:stretch;gap:.25rem;height:13rem;overflow-x:auto;padding:.5rem 0;border-bottom:1px solid #ddd}}.history-chart>div{{display:grid;grid-template-rows:1.2rem 1fr 1.6rem;flex:1 0 1.5rem;min-width:1.5rem;text-align:center}}.history-chart b{{font-size:.75rem}}.history-chart span{{display:flex;align-items:flex-end;overflow:hidden;background:#f2f2f2;border-radius:.25rem .25rem 0 0}}.history-chart i{{display:block;width:100%;background:#1677ff;border-radius:.25rem .25rem 0 0}}.history-chart time{{font-size:.65rem;color:#666;white-space:nowrap}}.history-records{{margin-top:1rem}}.history-records summary{{cursor:pointer;font-weight:600}}.history-list{{max-height:18rem;overflow:auto;margin-top:1rem;padding-left:1.4rem;font-size:.9rem}}#history-empty{{color:#666}}@media(max-width:40rem){{.dashboard-head,.history-head{{align-items:flex-start;flex-direction:column}}.sync-metrics{{grid-template-columns:repeat(2,1fr)}}.sync-times{{grid-template-columns:1fr}}}}</style>
</head><body><h1>{title}</h1>{body}</body></html>""".encode()


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        super().end_headers()

    def guess_type(self, path):
        # without a charset, pages lacking <meta charset> render Thai as mojibake
        kind = super().guess_type(path)
        return f"{kind}; charset=utf-8" if kind.startswith("text/") else kind

    def translate_path(self, path):
        relative = unquote(urlsplit(path).path).lstrip("/")
        candidate = (ROOT / relative).resolve()
        if not candidate.is_relative_to(ROOT):
            return str(ROOT / "__not_found__")
        if "/" not in relative and not candidate.exists():
            candidate = (LEGACY_ROOT / relative).resolve()
        return str(candidate)

    def servable(self, path):
        suffix = Path(path).suffix.lower()
        return ((suffix == ".html" or suffix in ASSET_SUFFIXES)
                and Path(self.translate_path(self.path)).is_file())

    def do_GET(self):
        path = unquote(urlsplit(self.path).path)
        if path in ("/", "/index.html"):
            self.send_index(head_only=False)
        elif path == "/api/sync" and MODE == "monitor":
            self.send_sync(head_only=False)
        elif MODE == "content" and self.servable(path):
            super().do_GET()
        elif path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
        else:
            self.send_error(404)

    def do_HEAD(self):
        path = unquote(urlsplit(self.path).path)
        if path in ("/", "/index.html"):
            self.send_index(head_only=True)
        elif path == "/api/sync" and MODE == "monitor":
            self.send_sync(head_only=True)
        elif MODE == "content" and self.servable(path):
            super().do_HEAD()
        else:
            self.send_error(404)

    def send_index(self, head_only):
        files = [] if MODE == "monitor" else sorted(
            path for path in ROOT.rglob("*")
            if path.is_file() and path.suffix.lower() == ".html"
        )
        body = render_index(files)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    def send_sync(self, head_only):
        try:
            state = json.loads(SYNC_STATE.read_text())
            body = json.dumps({key: value for key, value in state.items() if not key.startswith("_")}).encode()
        except (OSError, ValueError):
            body = b'{"available":false,"state":"error","completion":0,"needFiles":0,"needBytes":0,"connectedDevices":0,"totalDevices":0,"devices":[],"activities":[]}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if not head_only:
            self.wfile.write(body)


if __name__ == "__main__":
    if sys.argv[1:] == ["--check"]:
        page = render_index([ROOT / "space_&-name.html"], mode="content")
        assert b"space_%26-name.html" in page
        assert b"Space &amp; Name" in page
        grouped = render_index([ROOT / "folder/a.html", ROOT / "folder/sub/a.html", ROOT / "folder/b.html"])
        assert grouped.count(b"<h2>folder</h2>") == 1
        assert b"Syncthing Monitor" not in page
        monitor = render_index([], mode="monitor")
        assert b"Syncthing Monitor" in monitor and b'/api/sync' in monitor
        assert all(label in monitor for label in (b"Local data", b"Global data", b"Device details", b"Last checked"))
        handler = object.__new__(Handler)
        assert handler.guess_type("a.html") == "text/html; charset=utf-8"
        assert handler.guess_type("a.png") == "image/png"
    else:
        ThreadingHTTPServer(("0.0.0.0", 80), Handler).serve_forever()
