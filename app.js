/* global state */
let recipients = []; // Array<{name, email, event, host}>
let previewIndex = 0;

// Cached template strings
let tmplHtml = null;
let tmplCss = null;

const MAX_RECIPIENTS = 50;

// ── Validation ────────────────────────────────────────────────────────────────

// Covers the vast majority of real email addresses (RFC 5321 practical subset)
const EMAIL_RE = /^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$/;

function isValidEmail(email) {
  return EMAIL_RE.test(String(email || "").trim());
}

/** Returns an array of field names that fail validation for a given row. */
function validateRow(r) {
  const errs = [];
  if (!String(r.name || "").trim()) errs.push("name");
  if (!isValidEmail(r.email)) errs.push("email");
  return errs;
}

// ── DOM helpers ───────────────────────────────────────────────────────────────

const $ = (id) => document.getElementById(id);

function show(id) {
  $(id).classList.remove("hidden");
}
function hide(id) {
  $(id).classList.add("hidden");
}

function setStatus(id, msg, type = "") {
  const el = $(id);
  el.textContent = msg;
  el.className = "status-text" + (type ? " " + type : "");
}

function escHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// ── Send button state ─────────────────────────────────────────────────────────

function refreshSendButton() {
  const total = recipients.length;
  const invalid = recipients.filter((r) => validateRow(r).length > 0).length;
  const missingEvent = !$("global-event").value.trim();
  const missingHost = !$("global-host").value.trim();
  const tooMany = total > MAX_RECIPIENTS;
  const btn = $("btn-send-all");

  // Visual feedback on the required fields
  $("global-event").classList.toggle("input-missing", missingEvent);
  $("global-host").classList.toggle("input-missing", missingHost);

  if (total === 0) {
    btn.disabled = true;
    $("recipient-count").textContent = "";
    return;
  }

  const reasons = [];
  if (tooMany)
    reasons.push(
      `Max ${MAX_RECIPIENTS} recipients — remove ${total - MAX_RECIPIENTS} row${total - MAX_RECIPIENTS === 1 ? "" : "s"}`,
    );
  if (missingEvent) reasons.push("Event Name is required");
  if (missingHost) reasons.push("Host Name is required");
  if (invalid > 0)
    reasons.push(`${invalid} row${invalid === 1 ? "" : "s"} with errors`);

  if (reasons.length > 0) {
    btn.disabled = true;
    $("recipient-count").textContent =
      reasons.join(" · ") + " — fix to enable sending";
  } else {
    btn.disabled = false;
    $("recipient-count").textContent =
      `${total} recipient${total === 1 ? "" : "s"} · all valid`;
  }
}

// ── Parse error UI ────────────────────────────────────────────────────────────

function showParseError(message) {
  $("parse-error-title").textContent = message;
  show("parse-error-box");
}

function hideParseError() {
  hide("parse-error-box");
}

// ── Spreadsheet parser ────────────────────────────────────────────────────────

function parseSpreadsheet(raw) {
  const lines = raw
    .trim()
    .split(/\r?\n/)
    .filter((l) => l.trim().length > 0);
  if (lines.length < 2) {
    throw new Error("Need at least one header row and one data row.");
  }

  const delim = lines[0].includes("\t") ? "\t" : ",";

  const headers = lines[0].split(delim).map((h) =>
    h
      .trim()
      .toLowerCase()
      .replace(/[\s_\-'"]+/g, ""),
  );

  const aliases = {
    name: ["name", "fullname", "recipient", "studentname", "attendeename"],
    email: ["email", "emailaddress", "mail", "e-mail"],
    event: ["event", "eventname", "workshop", "session", "program"],
    host: ["host", "hostname", "presenter", "ambassador", "speaker"],
  };

  const col = {};
  for (const [field, list] of Object.entries(aliases)) {
    const idx = headers.findIndex((h) => list.includes(h));
    if (idx !== -1) col[field] = idx;
  }

  if (col.name === undefined)
    throw new Error('Could not find a "Name" column in your data.');
  if (col.email === undefined)
    throw new Error('Could not find an "Email" column in your data.');

  const rows = [];
  for (let i = 1; i < lines.length; i++) {
    const cells = splitRow(lines[i], delim);
    const name = (cells[col.name] || "").trim();
    const email = (cells[col.email] || "").trim();
    if (!name && !email) continue;

    rows.push({
      name,
      email,
      event: col.event !== undefined ? (cells[col.event] || "").trim() : "",
      host: col.host !== undefined ? (cells[col.host] || "").trim() : "",
    });
  }

  if (rows.length === 0)
    throw new Error("No data rows were found after parsing.");
  return rows;
}

function splitRow(line, delim) {
  const cells = [];
  let cur = "";
  let inQ = false;

  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (ch === '"') {
      if (inQ && line[i + 1] === '"') {
        cur += '"';
        i++;
      } else inQ = !inQ;
    } else if (ch === delim && !inQ) {
      cells.push(cur);
      cur = "";
    } else {
      cur += ch;
    }
  }
  cells.push(cur);
  return cells;
}

// ── Recipient table (editable) ────────────────────────────────────────────────

function renderTable(data) {
  const tbody = $("data-tbody");
  tbody.innerHTML = "";

  data.forEach((r, i) => {
    const errs = validateRow(r);
    const tr = document.createElement("tr");
    if (errs.length) tr.classList.add("row-invalid");

    function editTd(field, value, extraClass = "") {
      const td = document.createElement("td");
      td.className = [
        "cell-editable",
        extraClass,
        errs.includes(field) ? "cell-invalid" : "",
      ]
        .filter(Boolean)
        .join(" ");
      td.contentEditable = "true";
      td.dataset.i = i;
      td.dataset.field = field;
      td.spellcheck = false;
      if ((field === "event" || field === "host") && !value) {
        td.dataset.placeholder = "uses global";
      }
      td.textContent = value;
      return td;
    }

    const numTd = document.createElement("td");
    numTd.className = "cell-num";
    numTd.textContent = i + 1;
    tr.appendChild(numTd);

    tr.appendChild(editTd("name", r.name, "cell-name"));
    tr.appendChild(editTd("email", r.email, "cell-email-mono"));
    tr.appendChild(editTd("event", r.event, "cell-dim"));
    tr.appendChild(editTd("host", r.host, "cell-dim"));

    const actTd = document.createElement("td");
    const btn = document.createElement("button");
    btn.className = "btn btn-ghost btn-sm js-preview";
    btn.dataset.i = i;
    btn.textContent = "Preview";
    actTd.appendChild(btn);
    tr.appendChild(actTd);

    tbody.appendChild(tr);
  });

  // ── Wire up contenteditable cells ──────────────────────────────────────────
  tbody.querySelectorAll("[contenteditable]").forEach((td) => {
    td.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        td.blur();
      }
    });

    td.addEventListener("input", () => {
      const idx = +td.dataset.i;
      const field = td.dataset.field;
      const val = td.textContent.trim();

      recipients[idx][field] = val;

      if (field === "event" || field === "host") {
        if (val) delete td.dataset.placeholder;
        else td.dataset.placeholder = "uses global";
      }

      const rowErrs = validateRow(recipients[idx]);
      const trEl = td.closest("tr");
      trEl.classList.toggle("row-invalid", rowErrs.length > 0);
      trEl.querySelectorAll("[data-field]").forEach((cell) => {
        const f = cell.dataset.field;
        cell.classList.toggle(
          "cell-invalid",
          (f === "name" || f === "email") && rowErrs.includes(f),
        );
      });

      _updateTableMeta();
      refreshSendButton();

      if (
        !$("step-preview").classList.contains("hidden") &&
        previewIndex === idx
      ) {
        renderPreview();
      }
    });
  });

  // ── Wire up Preview buttons ────────────────────────────────────────────────
  tbody
    .querySelectorAll(".js-preview")
    .forEach((btn) =>
      btn.addEventListener("click", () => openPreview(+btn.dataset.i)),
    );

  _updateTableMeta();
  show("table-wrapper");
}

function _updateTableMeta() {
  const total = recipients.length;
  const invalid = recipients.filter((r) => validateRow(r).length > 0).length;
  const tooMany = total > MAX_RECIPIENTS;

  let meta = `${total} recipient${total === 1 ? "" : "s"}`;

  if (tooMany) {
    meta += ` · <span class="count-error">max ${MAX_RECIPIENTS} allowed — remove ${total - MAX_RECIPIENTS} row${total - MAX_RECIPIENTS === 1 ? "" : "s"}</span>`;
  } else if (invalid > 0) {
    meta += ` · <span class="count-error">${invalid} with errors — click any cell to edit</span>`;
  } else {
    meta += ` · <span class="count-ok">all valid ✓</span>`;
  }

  $("table-meta").innerHTML = meta;
}

// ── Certificate template ──────────────────────────────────────────────────────

async function loadTemplate() {
  if (tmplHtml !== null) return;

  const [hRes, cRes] = await Promise.all([
    fetch("/Templates/Certificate/index.html"),
    fetch("/Templates/Certificate/certificate.css"),
  ]);

  if (!hRes.ok || !cRes.ok) {
    throw new Error("Could not load certificate template files.");
  }

  tmplHtml = await hRes.text();
  tmplCss = await cRes.text();
}

function buildCertHtml(recipient) {
  // Always read global fields live from the DOM — typing into the inputs
  // after parsing is immediately reflected in the preview.
  const event =
    String(recipient.event || "").trim() || $("global-event").value.trim();
  const host =
    String(recipient.host || "").trim() || $("global-host").value.trim();

  let html = tmplHtml.replace(
    /<link[^>]+certificate\.css[^>]*\/?>/i,
    `<style>${tmplCss}</style>`,
  );

  const base = `${window.location.origin}/Templates/Certificate/`;
  html = html.replace("<head>", `<head>\n  <base href="${base}">`);

  html = html.replace(/\{NAME\}/g, escHtml(recipient.name));
  html = html.replace(/\{EVENT\}/g, escHtml(event));
  html = html.replace(/\{HOST\}/g, escHtml(host));

  return html;
}

// ── Preview ───────────────────────────────────────────────────────────────────

async function openPreview(index) {
  previewIndex = index;

  try {
    await loadTemplate();
  } catch (err) {
    alert(`Failed to load template: ${err.message}`);
    return;
  }

  show("step-preview");
  $("step-preview").scrollIntoView({ behavior: "smooth", block: "start" });
  renderPreview();
}

function renderPreview() {
  const r = recipients[previewIndex];
  $("preview-label").textContent = `${r.name} · ${r.email}`;
  $("preview-counter").textContent =
    `${previewIndex + 1} / ${recipients.length}`;

  $("btn-prev").disabled = previewIndex === 0;
  $("btn-next").disabled = previewIndex === recipients.length - 1;

  $("cert-iframe").srcdoc = buildCertHtml(r);
  scaleIframe();
}

function scaleIframe() {
  const wrapper = $("iframe-wrapper");
  const iframe = $("cert-iframe");
  const CERT_W = 1053;
  const CERT_H = 757;
  const PAD = 48;

  const available = wrapper.clientWidth - PAD;
  const scale = Math.min(1, available / CERT_W);

  iframe.style.transform = `scale(${scale})`;
  wrapper.style.height = `${Math.ceil(CERT_H * scale + PAD)}px`;
}

window.addEventListener("resize", () => {
  if (!$("step-preview").classList.contains("hidden")) scaleIframe();
});

// ── Global event/host → live preview refresh ──────────────────────────────────

let _globalDebounce = null;
["global-event", "global-host"].forEach((id) => {
  $(id).addEventListener("input", () => {
    refreshSendButton();
    clearTimeout(_globalDebounce);
    _globalDebounce = setTimeout(() => {
      if (!$("step-preview").classList.contains("hidden")) renderPreview();
    }, 150);
  });
});

// ── Wire up buttons ───────────────────────────────────────────────────────────

$("btn-parse").addEventListener("click", () => {
  const text = $("paste-area").value;
  if (!text.trim()) {
    setStatus("parse-status", "Paste some data first.", "error");
    return;
  }

  try {
    recipients = parseSpreadsheet(text);
    hideParseError();
    renderTable(recipients);
    refreshSendButton();

    const invalid = recipients.filter((r) => validateRow(r).length > 0).length;
    const n = recipients.length;

    if (invalid > 0) {
      setStatus(
        "parse-status",
        `${n} row${n === 1 ? "" : "s"} parsed · ${invalid} with errors`,
        "error",
      );
    } else {
      setStatus(
        "parse-status",
        `✓ ${n} recipient${n === 1 ? "" : "s"} parsed`,
        "success",
      );
    }
  } catch (err) {
    showParseError(err.message);
    setStatus("parse-status", err.message, "error");
    hide("table-wrapper");
    hide("step-preview");
    recipients = [];
    refreshSendButton();
  }
});

$("btn-clear").addEventListener("click", () => {
  $("paste-area").value = "";
  recipients = [];
  hide("table-wrapper");
  hide("step-preview");
  hideParseError();
  setStatus("parse-status", "");
  refreshSendButton();
});

$("btn-close-preview").addEventListener("click", () => hide("step-preview"));

$("btn-prev").addEventListener("click", () => {
  if (previewIndex > 0) {
    previewIndex--;
    renderPreview();
  }
});

$("btn-next").addEventListener("click", () => {
  if (previewIndex < recipients.length - 1) {
    previewIndex++;
    renderPreview();
  }
});

// ── Send all ──────────────────────────────────────────────────────────────────

$("btn-send-all").addEventListener("click", async () => {
  if (recipients.length === 0) return;

  const globalEvent = $("global-event").value.trim();
  const globalHost = $("global-host").value.trim();

  $("btn-send-all").disabled = true;
  $("btn-parse").disabled = true;

  const resultsList = $("results-list");
  resultsList.innerHTML = "";
  resultsList.classList.add("hidden");
  $("progress-fill").style.width = "0%";
  $("progress-label").textContent = `Sending 1 of ${recipients.length}…`;
  show("progress-area");

  let sent = 0;
  let errors = 0;

  for (let i = 0; i < recipients.length; i++) {
    const r = recipients[i];
    $("progress-label").textContent =
      `Sending ${i + 1} of ${recipients.length}: ${r.name}…`;

    let resultStatus = "error";
    let resultMsg = "";

    try {
      const res = await fetch("/api/send", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          recipients: [r],
          event: globalEvent,
          host: globalHost,
        }),
      });

      const data = await res.json();
      const item = data.results?.[0];

      if (item?.status === "sent") {
        resultStatus = "sent";
        sent++;
      } else {
        resultMsg = item?.message || `HTTP ${res.status}`;
        errors++;
      }
    } catch (err) {
      resultMsg = err.message || "Network error";
      errors++;
    }

    const li = document.createElement("li");
    li.className = `result-item ${resultStatus}`;
    li.innerHTML = `
      <span class="result-icon">${resultStatus === "sent" ? "✓" : "✕"}</span>
      <span>
        <span class="result-name">${escHtml(r.name)}</span>
        <span class="result-addr"> &lt;${escHtml(r.email)}&gt;</span>
      </span>
      ${resultMsg ? `<span class="result-msg">${escHtml(resultMsg)}</span>` : ""}
    `;
    resultsList.appendChild(li);
    show("results-list");

    const pct = Math.round(((i + 1) / recipients.length) * 100);
    $("progress-fill").style.width = pct + "%";
  }

  $("progress-label").textContent =
    `Done — ${sent} sent, ${errors} error${errors === 1 ? "" : "s"}`;

  $("btn-parse").disabled = false;
  refreshSendButton();
});
