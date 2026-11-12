"""Self-contained status + configuration page for the gateway.

Served at ``GET /`` on loopback, this single HTML document (inline CSS/JS, no
external requests) lets a human see what the gateway sees — which CLIs are
installed, whether the upstream is reachable, active sessions, uptime — and
change the runtime config (permission mode, upstream URL, working dir), with an
option to persist the change to ``.env``.

``SECURITY_PAGE`` (``GET /security``) lists the security stops of every turn on this
machine (security_log.py) with links to the pages involved; it only talks to
``/api/security``. Both pages share ``STYLE``.

Kept out of ``gateway.py`` so the routing logic stays readable; the status page only
talks to ``/api/status`` and ``/api/config``.
"""

STYLE = """  :root {
    --bg: #f6f7f9; --panel: #ffffff; --panel-2: #f0f2f5; --border: #e2e5ea;
    --text: #1b1f27; --muted: #667085; --accent: #4f46e5; --accent-2: #0d9488;
    --ok: #15803d; --ok-bg: #dcfce7; --bad: #b91c1c; --bad-bg: #fee2e2;
    --warn: #b45309; --warn-bg: #fef3c7; --shadow: 0 1px 3px rgba(16,24,40,.08);
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #0f1115; --panel: #171a21; --panel-2: #1e222b; --border: #2a2f3a;
      --text: #e6e8ec; --muted: #9aa2b1; --accent: #818cf8; --accent-2: #2dd4bf;
      --ok: #4ade80; --ok-bg: #14321f; --bad: #f87171; --bad-bg: #3a1717;
      --warn: #fbbf24; --warn-bg: #3a2c10; --shadow: 0 1px 3px rgba(0,0,0,.35);
    }
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--text);
    font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  }
  .wrap { max-width: 940px; margin: 0 auto; padding: 28px 20px 60px; }
  header { display: flex; align-items: center; gap: 12px; margin-bottom: 4px; }
  header h1 { font-size: 22px; margin: 0; font-weight: 650; letter-spacing: -.01em; }
  header .badge-live { margin-left: auto; }
  .sub { color: var(--muted); margin: 0 0 22px; font-size: 13.5px; }
  .dot { width: 10px; height: 10px; border-radius: 50%; background: var(--muted); display: inline-block; flex: none; }
  .dot.ok { background: var(--ok); box-shadow: 0 0 0 3px var(--ok-bg); }
  .dot.bad { background: var(--bad); box-shadow: 0 0 0 3px var(--bad-bg); }
  section { margin-bottom: 26px; }
  h2 { font-size: 13px; text-transform: uppercase; letter-spacing: .06em; color: var(--muted);
       margin: 0 0 12px; font-weight: 600; }
  .grid { display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); }
  .card { background: var(--panel); border: 1px solid var(--border); border-radius: 12px;
          padding: 14px 16px; box-shadow: var(--shadow); }
  .stat .k { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }
  .stat .v { font-size: 22px; font-weight: 650; margin-top: 4px; font-variant-numeric: tabular-nums; }
  .stat .v small { font-size: 13px; font-weight: 500; color: var(--muted); }
  .badge { display: inline-flex; align-items: center; gap: 5px; font-size: 12px; font-weight: 600;
           padding: 2px 9px; border-radius: 999px; }
  .badge.ok { color: var(--ok); background: var(--ok-bg); }
  .badge.bad { color: var(--bad); background: var(--bad-bg); }
  .badge.warn { color: var(--warn); background: var(--warn-bg); }
  table { width: 100%; border-collapse: collapse; }
  .table-wrap { overflow-x: auto; border: 1px solid var(--border); border-radius: 12px; background: var(--panel);
                box-shadow: var(--shadow); }
  th, td { text-align: left; padding: 11px 14px; border-bottom: 1px solid var(--border); vertical-align: middle; }
  th { font-size: 11.5px; text-transform: uppercase; letter-spacing: .05em; color: var(--muted); font-weight: 600; }
  tr:last-child td { border-bottom: none; }
  td.name { font-weight: 600; }
  code, .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12.5px; }
  .chips { display: flex; flex-wrap: wrap; gap: 5px; }
  .chip { background: var(--panel-2); border: 1px solid var(--border); border-radius: 6px;
          padding: 1px 7px; font-size: 11.5px; }
  .hint { color: var(--muted); font-size: 12px; }
  form.card { padding: 18px 18px 20px; }
  .field { margin-bottom: 15px; }
  .field label { display: block; font-size: 13px; font-weight: 600; margin-bottom: 5px; }
  .field .desc { color: var(--muted); font-size: 12px; margin: -2px 0 6px; }
  .field input, .field select {
    width: 100%; padding: 9px 11px; border: 1px solid var(--border); border-radius: 8px;
    background: var(--panel-2); color: var(--text); font: inherit; font-size: 14px;
  }
  .field input:focus, .field select:focus { outline: 2px solid var(--accent); outline-offset: 0; border-color: transparent; }
  .actions { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-top: 4px; }
  button { font: inherit; font-weight: 600; font-size: 14px; border-radius: 8px; padding: 9px 16px;
           border: 1px solid var(--border); cursor: pointer; background: var(--panel-2); color: var(--text); }
  button.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
  button:disabled { opacity: .55; cursor: default; }
  .toast { font-size: 13px; font-weight: 600; opacity: 0; transition: opacity .2s; }
  .toast.show { opacity: 1; }
  .toast.ok { color: var(--ok); }
  .toast.bad { color: var(--bad); }
  footer { color: var(--muted); font-size: 12px; margin-top: 34px; border-top: 1px solid var(--border); padding-top: 14px; }
  a { color: var(--accent); }
  nav { display: flex; gap: 16px; margin: 0 0 22px; font-size: 13.5px; }
  nav a { text-decoration: none; font-weight: 600; }
  nav a.here { color: var(--text); }
  [hidden] { display: none !important; }
  form.authbar { margin-bottom: 22px; border-color: var(--warn); }
  form.authbar .row { display: flex; gap: 8px; }
  form.authbar input { flex: 1; }
"""

# Both pages call the API with the owner token (gateway_auth.py), kept in this browser's
# localStorage. It arrives pasted in AUTH_FORM, or in a link ending in #token=<token>, which the
# page stores and then strips from the address bar.
AUTH_FORM = """  <form id="auth" class="card authbar" hidden>
    <div class="field">
      <label for="token-input">Owner token</label>
      <div class="desc">This page needs the gateway's owner token: paste the contents of
        <code>~/.agent-cli-bridge/gateway-owner-token</code>. It stays in this browser.</div>
      <div class="row">
        <input id="token-input" type="password" class="mono" autocomplete="off" spellcheck="false">
        <button type="submit" class="primary">Use token</button>
      </div>
    </div>
  </form>
"""

AUTH_JS = """
  var TOKEN_KEY = "acb-gateway-token";
  (function takeTokenFromLink() {
    var m = /^#token=([^&]+)/.exec(location.hash || "");
    if (!m) return;
    try { localStorage.setItem(TOKEN_KEY, decodeURIComponent(m[1])); } catch (e) {}
    history.replaceState(null, "", location.pathname + location.search);
  })();
  function storedToken() { try { return localStorage.getItem(TOKEN_KEY) || ""; } catch (e) { return ""; } }
  function api(path, opts) {
    opts = opts || {};
    opts.headers = opts.headers || {};
    opts.headers.Authorization = "Bearer " + storedToken();
    return fetch(path, opts).then(function (r) {
      if (r.status === 401) { $("auth").hidden = false; throw new Error("token refused"); }
      if (r.status === 403) {  // the client token was pasted: owner actions need the owner's
        r.clone().json().then(function (j) {
          if (j.error && j.error.code === "owner_token_required") $("auth").hidden = false;
        }).catch(function () {});
      }
      return r;
    });
  }
  $("auth").addEventListener("submit", function (ev) {
    ev.preventDefault();
    var value = $("token-input").value.trim();
    if (!value) return;
    try { localStorage.setItem(TOKEN_KEY, value); } catch (e) {}
    location.reload();
  });
"""

# Both pages insert API text into HTML, including inside attributes, with this one function.
ESC_JS = """
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
"""

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AgentCliBridge · Status &amp; Config</title>
<style>
""" + STYLE + """</style>
</head>
<body>
<div class="wrap">
  <header>
    <span id="health-dot" class="dot"></span>
    <h1>AgentCliBridge</h1>
    <span class="badge-live"><span id="live" class="badge warn">connecting…</span></span>
  </header>
  <p class="sub">OpenAI-compatible gateway over your local AI coding CLIs · loopback only, single user.</p>
  <nav><a class="here" href="/">Status &amp; config</a><a href="/security">Security log</a></nav>
""" + AUTH_FORM + """
  <section>
    <h2>Status</h2>
    <div class="grid" id="stats">
      <div class="card stat"><div class="k">Port</div><div class="v" id="s-port">—</div></div>
      <div class="card stat"><div class="k">Uptime</div><div class="v" id="s-uptime">—</div></div>
      <div class="card stat"><div class="k">Active sessions</div><div class="v" id="s-sessions">—</div></div>
      <div class="card stat"><div class="k">Version</div><div class="v" id="s-version">—</div></div>
    </div>
  </section>

  <section>
    <h2>Upstream (local-model passthrough)</h2>
    <div class="card" style="display:flex;align-items:center;gap:14px;flex-wrap:wrap">
      <span id="up-badge" class="badge warn">—</span>
      <code id="up-url" class="mono">—</code>
      <span class="hint" id="up-models"></span>
    </div>
  </section>

  <section>
    <h2>CLI agents</h2>
    <div class="table-wrap">
      <table>
        <thead><tr><th>Agent</th><th>Command</th><th>Status</th><th>Models</th></tr></thead>
        <tbody id="agents"><tr><td colspan="4" class="hint">Loading…</td></tr></tbody>
      </table>
    </div>
  </section>

  <section>
    <h2>Configuration</h2>
    <form class="card" id="cfg-form">
      <div class="field">
        <label for="permission_mode">Permission mode</label>
        <div class="desc">How CLIs are allowed to act. <code>plan</code> is read-only; <code>acceptEdits</code> and beyond let agents write files.</div>
        <select id="permission_mode" name="permission_mode"></select>
      </div>
      <div class="field">
        <label for="upstream">Upstream OpenAI base URL</label>
        <div class="desc">Non-CLI model ids are proxied here verbatim (default: http://127.0.0.1:8899/v1, e.g. a local MLX or Ollama server).</div>
        <input id="upstream" name="upstream" class="mono" spellcheck="false" placeholder="http://127.0.0.1:8899/v1">
      </div>
      <div class="field">
        <label for="workdir">Working directory</label>
        <div class="desc">The directory the CLIs run in.</div>
        <input id="workdir" name="workdir" class="mono" spellcheck="false">
      </div>
      <div class="actions">
        <button type="button" class="primary" id="apply">Apply</button>
        <button type="button" id="save">Apply &amp; save to .env</button>
        <span id="toast" class="toast"></span>
      </div>
    </form>
  </section>

  <section>
    <h2>Use from Brave Leo</h2>
    <div class="card" id="brave-leo">
      <div class="field">
        <label>Brave · Settings · Leo · Bring your own model · Add new model</label>
        <div class="desc">Leo sends the open page's text, and any page can hide instructions in it, so
          this route runs Claude with every tool, MCP server and web search off: it can read and
          answer, not act.</div>
      </div>
      <table>
        <tbody>
          <tr><td class="name">Server endpoint</td><td><code id="leo-endpoint">http://127.0.0.1:4747/browser/v1/chat/completions</code></td></tr>
          <tr><td class="name">Model request name</td><td><code>claude:sonnet</code>, <code>claude:haiku</code>, <code>claude:opus</code></td></tr>
          <tr><td class="name">API key</td><td>the contents of <code>~/.agent-cli-bridge/gateway-token</code> (the app token, not the owner token)</td></tr>
          <tr><td class="name">Context size</td><td><code>100000</code>: Leo cuts a longer page to fit it</td></tr>
          <tr><td class="name">Vision · Tool support</td><td>off</td></tr>
        </tbody>
      </table>
    </div>
  </section>

  <footer>
    Runtime changes take effect immediately; <em>Apply</em> alone resets on restart, <em>Apply &amp; save</em>
    writes them to <code>.env</code>. This page is served on 127.0.0.1 for a single user only —
    do not expose the gateway beyond loopback.
  </footer>
</div>

<script>
(function () {
  var $ = function (id) { return document.getElementById(id); };
""" + AUTH_JS + """  var formReady = false;

  function fmtUptime(s) {
    s = Math.max(0, s | 0);
    var d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600),
        m = Math.floor((s % 3600) / 60), sec = s % 60;
    if (d) return d + "d " + h + "h";
    if (h) return h + "h " + m + "m";
    if (m) return m + "m " + sec + "s";
    return sec + "s";
  }

  function badge(el, kind, text) {
    el.className = "badge " + kind;
    el.textContent = text;
  }

  function renderAgents(agents) {
    var tb = $("agents");
    if (!agents || !agents.length) { tb.innerHTML = '<tr><td colspan="4" class="hint">No agents known.</td></tr>'; return; }
    tb.innerHTML = agents.map(function (a) {
      var status = a.installed
        ? '<span class="badge ok">✓ installed</span>'
        : '<span class="badge bad">not installed</span>'
          + (a.install_hint ? ' <div class="hint">' + esc(a.install_hint) + '</div>' : '');
      var models = (a.models || []).map(function (m) { return '<span class="chip">' + esc(m) + '</span>'; }).join(' ');
      return '<tr><td class="name">' + esc(a.name) + '</td>'
        + '<td><code>' + esc(a.command) + '</code></td>'
        + '<td>' + status + '</td>'
        + '<td><div class="chips">' + models + '</div></td></tr>';
    }).join('');
  }

""" + ESC_JS + """
  function initForm(cfg) {
    var sel = $("permission_mode");
    sel.innerHTML = (cfg.permission_modes || []).map(function (m) {
      return '<option value="' + esc(m) + '"' + (m === cfg.permission_mode ? ' selected' : '') + '>' + esc(m) + '</option>';
    }).join('');
    $("upstream").value = cfg.upstream || '';
    $("workdir").value = cfg.workdir || '';
    formReady = true;
  }

  function applyStatus(d) {
    $("health-dot").className = "dot " + (d.ok ? "ok" : "bad");
    badge($("live"), "ok", "live");
    $("s-port").textContent = d.port;
    $("s-uptime").textContent = fmtUptime(d.uptime_seconds);
    $("s-sessions").textContent = d.sessions;
    $("s-version").innerHTML = 'v' + esc(d.version);
    var up = d.upstream || {};
    $("up-url").textContent = up.url || '—';
    if (up.reachable) { badge($("up-badge"), "ok", "reachable"); $("up-models").textContent = up.models + " models"; }
    else { badge($("up-badge"), "bad", "unreachable"); $("up-models").textContent = "passthrough disabled until it responds"; }
    renderAgents(d.agents);
    if (!formReady && d.config) initForm(d.config);
  }

  function poll() {
    api("/api/status").then(function (r) { return r.json(); }).then(applyStatus)
      .catch(function (err) {
        // A 401 means the gateway answered: it is up, the page just has no token yet.
        var isTokenMissing = err && err.message === "token refused";
        badge($("live"), isTokenMissing ? "warn" : "bad", isTokenMissing ? "token needed" : "offline");
        $("health-dot").className = "dot " + (isTokenMissing ? "" : "bad");
      });
  }

  function showToast(kind, text) {
    var t = $("toast");
    t.className = "toast show " + kind;
    t.textContent = text;
    setTimeout(function () { t.className = "toast " + kind; }, 2600);
  }

  function submit(persist) {
    var body = {
      permission_mode: $("permission_mode").value,
      upstream: $("upstream").value.trim(),
      workdir: $("workdir").value.trim(),
      persist: !!persist
    };
    $("apply").disabled = $("save").disabled = true;
    api("/api/config", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body)
    }).then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (res) {
        if (res.ok) showToast("ok", persist ? "Saved to .env ✓" : "Applied ✓");
        else showToast("bad", (res.j.error && res.j.error.message) || "Failed");
      })
      .catch(function () { showToast("bad", "Request failed"); })
      .finally(function () { $("apply").disabled = $("save").disabled = false; poll(); });
  }

  $("apply").addEventListener("click", function () { submit(false); });
  $("save").addEventListener("click", function () { submit(true); });

  // The port this page came from (PORT can move the gateway off 4747).
  $("leo-endpoint").textContent = location.origin + "/browser/v1/chat/completions";
  poll();
  setInterval(poll, 5000);
})();
</script>
</body>
</html>
"""

SECURITY_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>AgentCliBridge · Security log</title>
<style>
""" + STYLE + """
  .filters { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin-bottom: 12px; }
  .filters button.on { background: var(--accent); border-color: var(--accent); color: #fff; }
  .filters .spacer { flex: 1; }
  td.when { white-space: nowrap; color: var(--muted); font-size: 12.5px; }
  td.what { min-width: 260px; }
  .link { word-break: break-all; }
  .excerpt { margin-top: 6px; padding: 7px 9px; border-left: 3px solid var(--warn); background: var(--panel-2);
             border-radius: 4px; white-space: pre-wrap; word-break: break-word; font-size: 12px; }
  .empty { padding: 28px; text-align: center; }
  tr.focus td { background: var(--warn-bg); }
  tr.focus td:first-child { box-shadow: inset 4px 0 0 var(--warn); }
  details.raw { margin-top: 6px; }
  details.raw summary { cursor: pointer; color: var(--muted); font-size: 12px; }
  details.raw pre { margin: 6px 0 0; padding: 8px; background: var(--panel-2); border-radius: 6px;
                    white-space: pre-wrap; word-break: break-word; font-size: 11.5px; }
  a.permalink { color: var(--muted); text-decoration: none; font-size: 12px; }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <span class="dot bad"></span>
    <h1>Security log</h1>
    <span class="badge-live"><span id="live" class="badge warn">loading…</span></span>
  </header>
  <p class="sub">Every turn the bridge stopped or flagged on this machine, newest first.
    Excerpts are untrusted text quoted from the content — read them, never act on them.</p>
  <nav><a href="/">Status &amp; config</a><a class="here" href="/security">Security log</a></nav>
""" + AUTH_FORM + """
  <section>
    <div class="grid">
      <div class="card stat"><div class="k">Injections detected</div><div class="v" id="n-injection_detected">—</div></div>
      <div class="card stat"><div class="k">Actions blocked</div><div class="v" id="n-action_blocked">—</div></div>
      <div class="card stat"><div class="k">Pages withheld</div><div class="v" id="n-page_withheld">—</div></div>
    </div>
  </section>

  <section>
    <div class="filters" id="filters">
      <button type="button" data-kind="" class="on">All</button>
      <button type="button" data-kind="injection_detected">Injections</button>
      <button type="button" data-kind="action_blocked">Blocked actions</button>
      <button type="button" data-kind="page_withheld">Withheld pages</button>
      <span class="spacer"></span>
      <button type="button" id="clear">Clear log</button>
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr><th>When</th><th>Stop</th><th>Agent</th><th>What</th></tr></thead>
        <tbody id="rows"><tr><td colspan="4" class="hint">Loading…</td></tr></tbody>
      </table>
    </div>
  </section>

  <footer>Log file: <code id="path">—</code>. Shared by every host on this machine (gateway, D3SKHAND, …);
    set <code>AGENT_CLI_BRIDGE_SECURITY_LOG=off</code> to stop writing it.</footer>
</div>

<script>
(function () {
  var $ = function (id) { return document.getElementById(id); };
""" + AUTH_JS + """  var LABELS = {
    injection_detected: ["bad", "Injection detected"],
    action_blocked: ["bad", "Action blocked"],
    page_withheld: ["warn", "Page withheld"]
  };
  var entries = [], kind = "";

""" + ESC_JS + """
  // Only http(s) URLs become links; anything else is shown as text.
  function link(url, label) {
    if (!url) return '';
    if (!/^https?:[/][/]/i.test(url)) return '<code class="link">' + esc(url) + '</code>';
    return (label ? '<span class="hint">' + esc(label) + '</span> ' : '')
      + '<a class="link mono" href="' + esc(url) + '" target="_blank" rel="noopener noreferrer">' + esc(url) + '</a>';
  }

  function when(ts) {
    var d = new Date((ts || 0) * 1000);
    return d.toLocaleDateString() + '<br>' + d.toLocaleTimeString();
  }

  function focusId() { return (location.hash || "").replace(/^#e-/, ""); }

  function row(e) {
    var label = LABELS[e.kind] || ["warn", e.kind];
    var isFocus = e.id && e.id === focusId();
    var what = '<div><code>' + esc(e.tool) + '</code></div>';
    if (e.url) what += '<div>' + link(e.url) + '</div>';
    else if (e.target) what += '<div class="hint mono">' + esc(e.target) + '</div>';
    if (e.tainted_by) what += '<div>' + link(e.tainted_by, 'after reading') + '</div>';
    if (e.rules && e.rules.length) what += '<div class="chips" style="margin-top:5px">'
      + e.rules.map(function (r) { return '<span class="chip">' + esc(r) + '</span>'; }).join('') + '</div>';
    if (e.excerpt) what += '<div class="excerpt mono">' + esc(e.excerpt) + '</div>';
    if (e.reason) what += '<div class="hint" style="margin-top:5px">' + esc(e.reason) + '</div>';
    what += '<details class="raw"' + (isFocus ? ' open' : '') + '><summary>Details</summary><pre class="mono">'
      + esc(JSON.stringify(e, null, 2)) + '</pre></details>';
    var agent = '<code>' + esc(e.command) + (e.model ? ':' + esc(e.model) : '') + '</code>'
      + '<div class="hint">' + esc(e.source) + '</div>'
      + (e.cwd ? '<div class="hint mono">' + esc(e.cwd) + '</div>' : '');
    return '<tr' + (e.id ? ' id="e-' + esc(e.id) + '"' : '') + (isFocus ? ' class="focus"' : '') + '>'
      + '<td class="when">' + when(e.ts)
      + (e.id ? '<br><a class="permalink" href="#e-' + esc(e.id) + '" title="Link to this entry">#</a>' : '') + '</td>'
      + '<td><span class="badge ' + label[0] + '">' + esc(label[1]) + '</span></td>'
      + '<td>' + agent + '</td><td class="what">' + what + '</td></tr>';
  }

  function render() {
    ["injection_detected", "action_blocked", "page_withheld"].forEach(function (k) {
      $("n-" + k).textContent = entries.filter(function (e) { return e.kind === k; }).length;
    });
    var shown = entries.filter(function (e) { return !kind || e.kind === kind || (e.id && e.id === focusId()); });
    $("rows").innerHTML = shown.length ? shown.map(row).join('')
      : '<tr><td colspan="4" class="hint empty">No security stops recorded.</td></tr>';
  }

  var scrolledTo = null;

  // A link to one entry (#e-<id>, e.g. from a host's injection warning) shows it whatever the
  // filter, highlighted and scrolled into view once.
  function reveal() {
    var id = focusId();
    if (!id || id === scrolledTo) return;
    var target = $("e-" + id);
    if (!target) return;
    target.scrollIntoView({ block: "center" });
    scrolledTo = id;
  }

  function load() {
    api("/api/security").then(function (r) { return r.json(); }).then(function (d) {
      entries = d.entries || [];
      $("path").textContent = d.path || "disabled";
      $("live").className = "badge ok"; $("live").textContent = "live";
      render();
      reveal();
    }).catch(function () { $("live").className = "badge bad"; $("live").textContent = "offline"; });
  }

  $("filters").addEventListener("click", function (ev) {
    var b = ev.target.closest("button[data-kind]");
    if (!b) return;
    kind = b.getAttribute("data-kind");
    Array.prototype.forEach.call(document.querySelectorAll("#filters button[data-kind]"), function (x) {
      x.className = x === b ? "on" : "";
    });
    render();
  });

  $("clear").addEventListener("click", function () {
    if (!confirm("Delete every entry of the security log?")) return;
    api("/api/security", { method: "DELETE" }).then(function (r) {
      if (!r.ok) return r.json().then(function (j) { alert((j.error && j.error.message) || "Failed"); });
    }).catch(function () {}).then(load);
  });

  window.addEventListener("hashchange", function () { scrolledTo = null; render(); reveal(); });

  load();
  setInterval(load, 10000);
})();
</script>
</body>
</html>
"""
