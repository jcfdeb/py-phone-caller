# Interactive Multi-Service OpenAPI 3.0 Explorer

Explore every HTTP endpoint across all **8 `py-phone-caller` services** and **`openalertd` (`OpenAlert`)** in one place. Specifications and request/response payload examples are extracted directly from the `v1.1.0` source tree at build time, work **100% offline / air-gapped** with zero external CDNs, and include parameter tables, JSON/form payload previews, **`curl` command generation**, and downloadable **OpenAPI 3.0.3 JSON** schemas.

<style>
  .oas-shell {
    margin-top: 1.25rem;
    border: 1px solid var(--md-default-fg-color--lightest);
    border-radius: 14px;
    padding: 1.15rem;
    background: var(--md-code-bg-color);
  }
  .oas-stats {
    display: flex;
    flex-wrap: wrap;
    gap: 0.65rem;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 0.9rem;
    font-size: 0.82rem;
    color: var(--md-default-fg-color--light);
  }
  .oas-pills {
    display: flex;
    flex-wrap: wrap;
    gap: 0.45rem;
    margin-bottom: 0.95rem;
  }
  .oas-pill {
    cursor: pointer;
    border: 1px solid var(--md-default-fg-color--lighter);
    background: var(--md-default-bg-color);
    color: var(--md-default-fg-color);
    border-radius: 999px;
    padding: 0.35rem 0.78rem;
    font-size: 0.76rem;
    font-weight: 600;
    transition: all 0.15s ease;
  }
  .oas-pill:hover {
    border-color: var(--md-accent-fg-color);
  }
  .oas-pill.active {
    background: var(--md-primary-fg-color);
    color: var(--md-primary-bg-color);
    border-color: var(--md-primary-fg-color);
  }
  .oas-controls {
    display: flex;
    flex-wrap: wrap;
    gap: 0.6rem;
    margin-bottom: 1rem;
  }
  .oas-search {
    flex: 1 1 240px;
    padding: 0.52rem 0.8rem;
    border-radius: 8px;
    border: 1px solid var(--md-default-fg-color--lighter);
    background: var(--md-default-bg-color);
    color: var(--md-default-fg-color);
    font-size: 0.85rem;
  }
  .oas-method-select {
    padding: 0.52rem 0.75rem;
    border-radius: 8px;
    border: 1px solid var(--md-default-fg-color--lighter);
    background: var(--md-default-bg-color);
    color: var(--md-default-fg-color);
    font-size: 0.82rem;
    font-weight: 600;
  }
  .oas-download {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    padding: 0.5rem 0.85rem;
    border-radius: 8px;
    border: 1px solid var(--md-default-fg-color--lighter);
    background: var(--md-default-bg-color);
    color: var(--md-typeset-a-color) !important;
    font-size: 0.8rem;
    font-weight: 600;
    text-decoration: none !important;
  }
  .oas-list {
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
  }
  details.oas-op {
    border: 1px solid var(--md-default-fg-color--lightest);
    border-radius: 10px;
    background: var(--md-default-bg-color);
    overflow: hidden;
  }
  details.oas-op > summary {
    list-style: none;
    cursor: pointer;
    padding: 0.68rem 0.9rem;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.6rem;
    font-size: 0.84rem;
  }
  details.oas-op > summary::-webkit-details-marker { display: none; }
  .oas-badge {
    display: inline-block;
    min-width: 56px;
    text-align: center;
    padding: 0.18rem 0.45rem;
    border-radius: 6px;
    font-size: 0.7rem;
    font-weight: 700;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    color: #fff;
  }
  .oas-get { background: #0284c7; }
  .oas-post { background: #059669; }
  .oas-put { background: #d97706; }
  .oas-delete { background: #e11d48; }
  .oas-patch { background: #7c3aed; }
  .oas-path {
    font-family: var(--md-code-font-family);
    font-weight: 600;
    font-size: 0.83rem;
  }
  .oas-svc-tag {
    font-size: 0.7rem;
    padding: 0.12rem 0.48rem;
    border-radius: 5px;
    background: var(--md-code-bg-color);
    color: var(--md-default-fg-color--light);
    font-family: var(--md-code-font-family);
  }
  .oas-has-payload {
    font-size: 0.66rem;
    padding: 0.1rem 0.42rem;
    border-radius: 4px;
    border: 1px solid var(--md-default-fg-color--lightest);
    color: var(--md-default-fg-color--light);
  }
  .oas-summary {
    color: var(--md-default-fg-color--light);
    margin-left: auto;
    font-size: 0.8rem;
  }
  .oas-body {
    padding: 0.85rem 1rem 1rem;
    border-top: 1px solid var(--md-default-fg-color--lightest);
    font-size: 0.82rem;
  }
  .oas-param-table {
    width: 100%;
    border-collapse: collapse;
    margin: 0.45rem 0 0.85rem;
    font-size: 0.78rem;
  }
  .oas-param-table th,
  .oas-param-table td {
    text-align: left;
    padding: 0.42rem 0.55rem;
    border-bottom: 1px solid var(--md-default-fg-color--lightest);
    vertical-align: top;
  }
  .oas-param-table th {
    font-weight: 700;
    background: var(--md-code-bg-color);
  }
  .oas-req-pill {
    display: inline-block;
    padding: 0.06rem 0.36rem;
    border-radius: 4px;
    font-size: 0.68rem;
    font-weight: 700;
    background: rgba(225, 29, 72, 0.14);
    color: #e11d48;
  }
  .oas-section-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin: 0.65rem 0 0.3rem;
    font-weight: 600;
  }
  .oas-copy-btn {
    cursor: pointer;
    padding: 0.24rem 0.65rem;
    border-radius: 6px;
    border: 1px solid var(--md-default-fg-color--lighter);
    background: var(--md-code-bg-color);
    color: var(--md-default-fg-color);
    font-size: 0.74rem;
    font-weight: 600;
  }
  .oas-pre {
    margin: 0.3rem 0 0.75rem;
    padding: 0.7rem 0.85rem;
    border-radius: 8px;
    background: var(--md-code-bg-color);
    overflow-x: auto;
    font-family: var(--md-code-font-family);
    font-size: 0.76rem;
    line-height: 1.45;
  }
</style>

<div class="oas-shell" id="oas-explorer-root">
  <div class="oas-stats">
    <span id="oas-status-text">Loading OpenAPI 3.0.3 catalog…</span>
    <a class="oas-download" id="oas-download-link" href="../assets/openapi/catalog.json" download>⬇ Download JSON Spec</a>
  </div>
  <div class="oas-pills" id="oas-service-pills"></div>
  <div class="oas-controls">
    <input class="oas-search" id="oas-search-input" type="search" placeholder="Filter by path, parameter, keyword, or service (e.g. /sos, call_only, on_call, dtmf, sms, audio)…">
    <select class="oas-method-select" id="oas-method-filter" aria-label="Filter by HTTP method">
      <option value="ALL">All Methods</option>
      <option value="GET">GET</option>
      <option value="POST">POST</option>
      <option value="PUT">PUT</option>
      <option value="DELETE">DELETE</option>
    </select>
  </div>
  <div class="oas-list" id="oas-operations-list"></div>
</div>

<script>
(function () {
  function initExplorer() {
    var root = document.getElementById("oas-explorer-root");
    if (!root || root.dataset.bound === "1") return;
    root.dataset.bound = "1";

    var statusEl = document.getElementById("oas-status-text");
    var pillsEl = document.getElementById("oas-service-pills");
    var listEl = document.getElementById("oas-operations-list");
    var searchEl = document.getElementById("oas-search-input");
    var methodEl = document.getElementById("oas-method-filter");
    var downloadEl = document.getElementById("oas-download-link");

    var basePath = "../assets/openapi/";
    var allOps = [];
    var catalog = null;
    var activeService = "ALL";

    function esc(s) {
      return String(s == null ? "" : s)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
    }

    function resolveUrlWithExamples(op, includeOptionalQuery) {
      var p = op.path;
      var qParts = [];
      (op.parameters || []).forEach(function (param) {
        var exVal = param.example != null ? param.example : (param.schema && param.schema.default != null ? param.schema.default : "example");
        if (param.in === "path") {
          p = p.replace("{" + param.name + "}", encodeURIComponent(String(exVal)));
        } else if (param.in === "query" && (param.required || includeOptionalQuery)) {
          qParts.push(encodeURIComponent(param.name) + "=" + encodeURIComponent(String(exVal)));
        }
      });
      return op.server + p + (qParts.length ? "?" + qParts.join("&") : "");
    }

    function buildCurl(op) {
      var m = op.method.toUpperCase();
      var hasReqParams = (op.parameters || []).some(function (p) { return p.required; });
      var url = resolveUrlWithExamples(op, !hasReqParams);
      var parts = ["curl -fsS"];
      if (m !== "GET") parts.push("-X " + m);
      parts.push('"' + url + '"');

      if (op.bodyType === "application/json" && op.bodyExample != null) {
        parts.push('-H "Content-Type: application/json"');
        parts.push("-d '" + JSON.stringify(op.bodyExample, null, 2) + "'");
      } else if (op.bodyType === "application/x-www-form-urlencoded" && op.bodyExample && typeof op.bodyExample === "object") {
        Object.keys(op.bodyExample).forEach(function (k) {
          parts.push('--data-urlencode "' + k + "=" + String(op.bodyExample[k]) + '"');
        });
      } else if (op.bodyType === "multipart/form-data" && op.bodyExample && typeof op.bodyExample === "object") {
        Object.keys(op.bodyExample).forEach(function (k) {
          parts.push('-F "' + k + "=" + String(op.bodyExample[k]) + '"');
        });
      }
      return parts.join(" \\\n  ");
    }

    function renderPills() {
      if (!catalog) return;
      var html = '<button type="button" class="oas-pill' + (activeService === "ALL" ? " active" : "") + '" data-svc="ALL">All Services (' + catalog.total_operations + ")</button>";
      catalog.services.forEach(function (svc) {
        var cls = activeService === svc.id ? "oas-pill active" : "oas-pill";
        html += '<button type="button" class="' + cls + '" data-svc="' + esc(svc.id) + '">' + esc(svc.label) + " :" + svc.port + " (" + svc.operations + ")</button>";
      });
      pillsEl.innerHTML = html;
      Array.prototype.forEach.call(pillsEl.querySelectorAll(".oas-pill"), function (btn) {
        btn.addEventListener("click", function () {
          activeService = btn.getAttribute("data-svc");
          if (activeService === "ALL") {
            downloadEl.setAttribute("href", basePath + "catalog.json");
            downloadEl.textContent = "⬇ Download Catalog JSON";
          } else {
            downloadEl.setAttribute("href", basePath + activeService + ".json");
            downloadEl.textContent = "⬇ Download " + activeService + ".json";
          }
          renderPills();
          renderList();
        });
      });
    }

    function renderList() {
      var q = (searchEl.value || "").trim().toLowerCase();
      var mf = methodEl.value;
      var filtered = allOps.filter(function (op) {
        if (activeService !== "ALL" && op.serviceId !== activeService) return false;
        if (mf !== "ALL" && op.method !== mf) return false;
        if (!q) return true;
        return op.searchBlob.indexOf(q) !== -1;
      });

      statusEl.textContent = "Showing " + filtered.length + " of " + allOps.length + " HTTP operations across 9 services (OpenAPI 3.0.3 · v" + (catalog ? catalog.version : "1.1.0") + ")";

      if (!filtered.length) {
        listEl.innerHTML = '<div style="padding:1rem;color:var(--md-default-fg-color--light);">No endpoints match your current filter.</div>';
        return;
      }

      listEl.innerHTML = filtered.map(function (op, idx) {
        var mLower = op.method.toLowerCase();
        var hintChip = "";
        if (op.bodyExample != null) {
          hintChip = '<span class="oas-has-payload">' + (op.bodyType === "application/json" ? "JSON Body" : "Form Body") + "</span>";
        } else if (op.parameters && op.parameters.length) {
          hintChip = '<span class="oas-has-payload">' + op.parameters.length + (op.parameters.length === 1 ? " Param" : " Params") + "</span>";
        }

        var paramsHtml = "";
        if (op.parameters && op.parameters.length) {
          var sampleUrl = resolveUrlWithExamples(op, true);
          paramsHtml =
            '<div class="oas-section-bar"><span>Request Parameters (Path &amp; Query)</span></div>' +
            '<table class="oas-param-table">' +
              "<thead><tr><th>Parameter</th><th>In</th><th>Type</th><th>Status</th><th>Example &amp; Notes</th></tr></thead>" +
              "<tbody>" +
              op.parameters.map(function (p) {
                var typ = (p.schema && p.schema.type) ? p.schema.type : "string";
                var reqBadge = p.required ? '<span class="oas-req-pill">required</span>' : "optional";
                var exStr = p.example != null ? "<code>" + esc(JSON.stringify(p.example)) + "</code>" : "";
                var descStr = p.description ? (exStr ? " — " : "") + esc(p.description) : "";
                return (
                  "<tr>" +
                    "<td><code>" + esc(p.name) + "</code></td>" +
                    "<td><code>" + esc(p.in) + "</code></td>" +
                    "<td><code>" + esc(typ) + "</code></td>" +
                    "<td>" + reqBadge + "</td>" +
                    "<td>" + exStr + descStr + "</td>" +
                  "</tr>"
                );
              }).join("") +
              "</tbody>" +
            "</table>" +
            '<div style="margin-bottom:0.65rem;font-size:0.77rem;"><strong>Example Request URL:</strong> <code>' + esc(sampleUrl) + "</code></div>";
        }

        var bodyHtml = "";
        if (op.bodyExample != null) {
          var bodyLabel = "Example Request Payload (<code>" + esc(op.bodyType) + "</code>)";
          bodyHtml =
            '<div class="oas-section-bar"><span>' + bodyLabel + '</span><button type="button" class="oas-copy-btn" data-copy-target="oas-body-' + idx + '">Copy Payload</button></div>' +
            '<pre class="oas-pre" id="oas-body-' + idx + '">' + esc(JSON.stringify(op.bodyExample, null, 2)) + "</pre>";
        }

        var respExampleHtml = "";
        if (op.responseExample != null) {
          respExampleHtml =
            '<div class="oas-section-bar"><span>Example Response Payload (<code>HTTP ' + esc(op.responseExampleCode) + "</code>)</span></div>" +
            '<pre class="oas-pre">' + esc(JSON.stringify(op.responseExample, null, 2)) + "</pre>";
        }

        var respCodes = Object.keys(op.responses || {}).map(function (code) {
          var d = (op.responses[code] && op.responses[code].description) || "";
          return "<li><code>HTTP " + esc(code) + "</code> — " + esc(d) + "</li>";
        }).join("");
        var curlStr = buildCurl(op);

        return (
          '<details class="oas-op">' +
            "<summary>" +
              '<span class="oas-badge oas-' + esc(mLower) + '">' + esc(op.method) + "</span>" +
              '<span class="oas-path">' + esc(op.path) + "</span>" +
              '<span class="oas-svc-tag">' + esc(op.serviceLabel) + " :" + op.port + "</span>" +
              hintChip +
              '<span class="oas-summary">' + esc(op.summary) + "</span>" +
            "</summary>" +
            '<div class="oas-body">' +
              (op.description ? "<p>" + esc(op.description) + "</p>" : "") +
              "<p><strong>Direct Base URL:</strong> <code>" + esc(op.server) + "</code> · <strong>Gateway Prefix:</strong> <code>" + esc(op.gatewayPrefix) + "</code></p>" +
              paramsHtml +
              bodyHtml +
              (respCodes ? "<div><strong>Status Codes:</strong><ul>" + respCodes + "</ul></div>" : "") +
              respExampleHtml +
              '<div class="oas-section-bar"><span>Ready-to-Run <code>curl</code> Example</span><button type="button" class="oas-copy-btn" data-copy-target="oas-curl-' + idx + '">Copy curl</button></div>' +
              '<pre class="oas-pre" id="oas-curl-' + idx + '">' + esc(curlStr) + "</pre>" +
            "</div>" +
          "</details>"
        );
      }).join("");

      Array.prototype.forEach.call(listEl.querySelectorAll(".oas-copy-btn"), function (btn) {
        btn.addEventListener("click", function () {
          var pre = document.getElementById(btn.getAttribute("data-copy-target"));
          if (pre && navigator.clipboard) {
            navigator.clipboard.writeText(pre.textContent || "");
            var prev = btn.textContent;
            btn.textContent = "Copied!";
            setTimeout(function () { btn.textContent = prev; }, 1300);
          }
        });
      });
    }

    searchEl.addEventListener("input", renderList);
    methodEl.addEventListener("change", renderList);

    fetch(basePath + "catalog.json")
      .then(function (r) { return r.json(); })
      .then(function (cat) {
        catalog = cat;
        return Promise.all(cat.services.map(function (svc) {
          return fetch(basePath + svc.spec_file)
            .then(function (r) { return r.json(); })
            .then(function (spec) { return { svc: svc, spec: spec }; });
        }));
      })
      .then(function (loaded) {
        allOps = [];
        loaded.forEach(function (entry) {
          var svc = entry.svc;
          var spec = entry.spec;
          var server = (spec.servers && spec.servers[0] && spec.servers[0].url) || ("http://127.0.0.1:" + svc.port);
          var paths = spec.paths || {};
          Object.keys(paths).forEach(function (pathKey) {
            var item = paths[pathKey] || {};
            ["get", "post", "put", "delete", "patch"].forEach(function (m) {
              if (!item[m]) return;
              var op = item[m];
              var bodyEx = null;
              var bodyType = "";
              if (op.requestBody && op.requestBody.content) {
                var c = op.requestBody.content;
                var preferred = ["application/json", "application/x-www-form-urlencoded", "multipart/form-data"];
                for (var i = 0; i < preferred.length; i++) {
                  var mt = preferred[i];
                  if (c[mt] && c[mt].example != null) {
                    bodyType = mt;
                    bodyEx = c[mt].example;
                    break;
                  }
                }
              }
              var respEx = null;
              var respCode = "200";
              var resps = op.responses || {};
              ["200", "201"].forEach(function (rc) {
                if (!respEx && resps[rc] && resps[rc].content && resps[rc].content["application/json"] && resps[rc].content["application/json"].example != null) {
                  respEx = resps[rc].content["application/json"].example;
                  respCode = rc;
                }
              });

              var paramNames = (op.parameters || []).map(function (p) { return p.name || ""; }).join(" ");
              allOps.push({
                serviceId: svc.id,
                serviceLabel: svc.label,
                port: svc.port,
                gatewayPrefix: svc.gateway_prefix,
                server: server,
                path: pathKey,
                method: m.toUpperCase(),
                summary: op.summary || "",
                description: op.description || "",
                parameters: op.parameters || [],
                bodyType: bodyType,
                bodyExample: bodyEx,
                responseExample: respEx,
                responseExampleCode: respCode,
                responses: resps,
                searchBlob: [svc.id, svc.label, pathKey, m, op.summary || "", op.description || "", paramNames, (op.tags || []).join(" ")].join(" ").toLowerCase()
              });
            });
          });
        });
        renderPills();
        renderList();
      })
      .catch(function (err) {
        statusEl.textContent = "Unable to load OpenAPI specs: " + err;
      });
  }

  if (typeof document$ !== "undefined" && document$.subscribe) {
    document$.subscribe(initExplorer);
  } else if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initExplorer);
  } else {
    initExplorer();
  }
})();
</script>

---

## Direct Raw OpenAPI 3.0.3 JSON Specifications

When running a live stack, every Python microservice also serves interactive `/docs` and `/docs/swagger.json` on its own port (and static same-origin links when `PPC_OFFLINE=1`). You can also download each extracted specification directly here:

| Service | Default Port | APISIX Gateway Prefix | OpenAPI 3.0.3 Spec |
| :--- | :---: | :--- | :--- |
| **Web UI & NOC Center (`py_phone_caller_ui`)** | `5000` | `/` | [`py_phone_caller_ui.json`](assets/openapi/py_phone_caller_ui.json) |
| **OpenAlert Mesh Daemon (`openalertd`)** | `8090` | `/openalert` | [`openalertd.json`](assets/openapi/openalertd.json) |
| **`asterisk_caller`** | `8081` | `/api/v1/telephony` | [`asterisk_caller.json`](assets/openapi/asterisk_caller.json) |
| **`generate_audio` (TTS)** | `8082` | `/api/v1/audio` | [`generate_audio.json`](assets/openapi/generate_audio.json) |
| **`caller_register`** | `8083` | `/api/v1/registry` | [`caller_register.json`](assets/openapi/caller_register.json) |
| **`caller_prometheus_webhook`** | `8084` | `/api/v1/alerts` | [`caller_prometheus_webhook.json`](assets/openapi/caller_prometheus_webhook.json) |
| **`caller_sms`** | `8085` | `/api/v1/sms` | [`caller_sms.json`](assets/openapi/caller_sms.json) |
| **`caller_scheduler`** | `8086` | `/api/v1/schedules` | [`caller_scheduler.json`](assets/openapi/caller_scheduler.json) |
| **`caller_address_book`** | `8087` | `/api/v1/contacts` | [`caller_address_book.json`](assets/openapi/caller_address_book.json) |
