const token = document.querySelector('meta[name="csrf-token"]').content;
const grid = document.querySelector("#tool-grid");
const workspace = document.querySelector("#workspace");
const fields = document.querySelector("#fields");
const form = document.querySelector("#tool-form");
const applyInput = document.querySelector("#apply");
const debugInput = document.querySelector("#debug");
const confirmationRow = document.querySelector("#confirmation-row");
const resultPanel = document.querySelector("#result");
let selectedTool = null;
let connectivityScope = null;
let portSiteScope = null;

function card(tool) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "tool-card";
  button.disabled = !tool.available;
  button.dataset.toolId = tool.tool_id;
  button.setAttribute("aria-pressed", "false");
  const title = document.createElement("h3");
  title.textContent = tool.name;
  const summary = document.createElement("p");
  summary.textContent = tool.summary;
  const state = document.createElement("span");
  state.className = "tool-state";
  state.textContent = tool.available ? "Available now" : "Adapter planned";
  button.append(title, summary, state);
  if (tool.available) button.addEventListener("click", () => selectTool(tool));
  else button.title = tool.unavailable_reason;
  return button;
}

function selectTool(tool) {
  selectedTool = tool;
  document.querySelectorAll(".tool-card").forEach((item) => {
    item.setAttribute("aria-pressed", String(item.dataset.toolId === tool.tool_id));
  });
  document.querySelector("#workspace-title").textContent = tool.name;
  document.querySelector("#workspace-summary").textContent = `${tool.summary} ${tool.safety}`;
  fields.replaceChildren(...tool.fields.map(fieldElement));
  if (tool.tool_id === "connectivity-evidence") fields.append(connectivityScopeElement());
  if (tool.tool_id === "port-capacity") fields.append(portSiteScopeElement());
  applyInput.checked = false;
  debugInput.checked = false;
  updateMode();
  hideResult();
  workspace.hidden = false;
  workspace.scrollIntoView({ behavior: "smooth", block: "start" });
}

function fieldElement(field) {
  const label = document.createElement("label");
  label.className = "field";
  label.dataset.applyOnly = String(field.apply_only);
  const title = document.createElement("span");
  title.textContent = field.label;
  let input;
  if (field.kind === "textarea") {
    input = document.createElement("textarea");
  } else if (field.kind === "select") {
    input = document.createElement("select");
    field.options.forEach(([value, text]) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = text;
      input.append(option);
    });
  } else if (field.kind === "checkbox") {
    input = document.createElement("input");
    input.type = "checkbox";
  } else {
    input = document.createElement("input");
    input.type = field.kind === "number" ? "number" : "text";
  }
  input.name = field.name;
  input.required = field.required;
  if (field.kind === "checkbox") input.checked = Boolean(field.default);
  else input.value = field.default;
  input.autocomplete = "off";
  input.addEventListener("change", updateMode);
  label.append(title);
  if (field.picker) {
    const row = document.createElement("span");
    row.className = "path-row";
    const browse = document.createElement("button");
    browse.type = "button";
    browse.className = "button browse-button";
    browse.textContent = field.picker === "folder" ? "Choose folder…" : "Choose file…";
    browse.addEventListener("click", () => browsePath(field, input, browse));
    row.append(input, browse);
    label.append(row);
  } else {
    label.append(input);
  }
  if (field.help_text) {
    const help = document.createElement("small");
    help.textContent = field.help_text;
    label.append(help);
  }
  return label;
}

async function browsePath(field, input, button) {
  button.disabled = true;
  try {
    const response = await fetch("/api/browse", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": token },
      body: JSON.stringify({ tool_id: selectedTool.tool_id, field_name: field.name }),
    });
    const body = await response.json();
    if (!response.ok) throw new Error(body.error || "The path selector could not be opened.");
    if (body.path) {
      input.value = body.path;
      input.dispatchEvent(new Event("change", { bubbles: true }));
      if (selectedTool.tool_id === "connectivity-evidence" && field.name === "inventory_file") {
        await loadConnectivityScope();
      }
      if (selectedTool.tool_id === "port-capacity" && field.name === "site_inventory_file") {
        await loadPortSiteScope();
      }
    }
  } catch (error) {
    showResult({ message: error.message }, "Unable to select a path", true);
  } finally {
    button.disabled = false;
  }
}

function values() {
  const data = Object.fromEntries(new FormData(form).entries());
  fields.querySelectorAll('input[type="checkbox"]').forEach((input) => {
    data[input.name] = input.checked;
  });
  data.debug = debugInput.checked;
  data.confirmation = document.querySelector("#confirmation").value;
  if (selectedTool?.tool_id === "connectivity-evidence" && connectivityScope) {
    data.scope_mode = document.querySelector('input[name="scope_mode"]:checked')?.value || "all";
    data.selected_sites = JSON.stringify(scopeSelections("site-choice"));
    data.selected_devices = JSON.stringify(scopeSelections("device-choice"));
  }
  if (selectedTool?.tool_id === "port-capacity" && portSiteScope) {
    data.configured_site = document.querySelector("#configured-site")?.value || "";
    data.selected_site_targets = JSON.stringify(scopeSelections("port-site-choice"));
  }
  return data;
}

function portSiteScopeElement() {
  portSiteScope = null;
  const section = document.createElement("section");
  section.className = "scope-panel field-span";
  section.innerHTML = `
    <div class="scope-heading">
      <div><strong>Configured site selector</strong><small>Load the configured-sites JSON to choose a site and its switches.</small></div>
      <button type="button" class="button" id="load-port-sites">Load configured sites</button>
    </div>
    <div id="port-site-content" class="scope-content" hidden></div>`;
  section.querySelector("#load-port-sites").addEventListener("click", loadPortSiteScope);
  return section;
}

async function loadPortSiteScope() {
  const button = document.querySelector("#load-port-sites");
  const content = document.querySelector("#port-site-content");
  if (!button || !content) return;
  button.disabled = true;
  try {
    const response = await fetch("/api/inventory-scope", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": token },
      body: JSON.stringify({ tool_id: selectedTool.tool_id, values: values() }),
    });
    const body = await response.json();
    if (!response.ok) throw new Error(body.error || "Configured sites could not be loaded.");
    portSiteScope = body;
    renderPortSiteScope(content, body);
  } catch (error) {
    portSiteScope = null;
    content.hidden = true;
    showResult({ message: error.message }, "Unable to load configured sites", true);
  } finally {
    button.disabled = false;
  }
}

function renderPortSiteScope(content, scope) {
  content.innerHTML = `
    <p class="scope-summary">Found <strong>${scope.device_count}</strong> switch(es) across <strong>${scope.site_count}</strong> configured site(s).</p>
    <label class="search-label">Configured site<select id="configured-site"></select></label>
    <div class="device-actions"><button type="button" class="text-button" id="select-port-switches">Select all</button><button type="button" class="text-button" id="clear-port-switches">Clear selection</button></div>
    <div id="port-switch-list" class="device-list"></div>
    <div id="port-site-plan" class="scope-plan"></div>`;
  const selector = content.querySelector("#configured-site");
  scope.sites.forEach((site) => {
    const option = document.createElement("option");
    option.value = site.name;
    option.textContent = site.name;
    selector.append(option);
  });
  selector.addEventListener("change", renderPortSwitchChoices);
  content.querySelector("#select-port-switches").addEventListener("click", () => setPortSwitches(true));
  content.querySelector("#clear-port-switches").addEventListener("click", () => setPortSwitches(false));
  content.hidden = false;
  renderPortSwitchChoices();
}

function renderPortSwitchChoices() {
  const siteName = document.querySelector("#configured-site")?.value;
  const site = portSiteScope?.sites.find((item) => item.name === siteName);
  const list = document.querySelector("#port-switch-list");
  if (!site || !list) return;
  list.replaceChildren(...site.switches.map((item) => {
    const choice = scopeCheckbox("port-site-choice", item.ip_address, `${item.hostname} — ${item.ip_address}`, true);
    choice.querySelector("input").addEventListener("change", updatePortSitePlan);
    return choice;
  }));
  updatePortSitePlan();
}

function setPortSwitches(checked) {
  document.querySelectorAll(".port-site-choice").forEach((item) => { item.checked = checked; });
  updatePortSitePlan();
}

function updatePortSitePlan() {
  const count = scopeSelections("port-site-choice").length;
  const site = document.querySelector("#configured-site")?.value || "";
  const plan = document.querySelector("#port-site-plan");
  if (plan) plan.textContent = `${site} · ${count} selected switch(es)`;
}

function scopeSelections(className) {
  return [...document.querySelectorAll(`.${className}:checked`)].map((item) => item.value);
}

function connectivityScopeElement() {
  connectivityScope = null;
  const section = document.createElement("section");
  section.id = "connectivity-scope";
  section.className = "scope-panel field-span";
  section.innerHTML = `
    <div class="scope-heading">
      <div><strong>Inventory run scope</strong><small>Load an inventory to select all devices, multiple sites, or individual devices.</small></div>
      <button type="button" class="button" id="load-scope">Load inventory</button>
    </div>
    <div id="scope-content" class="scope-content" hidden></div>`;
  section.querySelector("#load-scope").addEventListener("click", loadConnectivityScope);
  return section;
}

async function loadConnectivityScope() {
  const button = document.querySelector("#load-scope");
  const content = document.querySelector("#scope-content");
  if (!button || !content) return;
  button.disabled = true;
  try {
    const response = await fetch("/api/inventory-scope", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": token },
      body: JSON.stringify({ tool_id: selectedTool.tool_id, values: values() }),
    });
    const body = await response.json();
    if (!response.ok) throw new Error(body.error || "The inventory could not be loaded.");
    connectivityScope = body;
    renderConnectivityScope(content, body);
  } catch (error) {
    connectivityScope = null;
    content.hidden = true;
    showResult({ message: error.message }, "Unable to load inventory", true);
  } finally {
    button.disabled = false;
  }
}

function renderConnectivityScope(content, scope) {
  content.innerHTML = `
    <p class="scope-summary">Found <strong>${scope.device_count}</strong> device(s) across <strong>${scope.site_count}</strong> site(s).</p>
    <div class="scope-modes">
      <label><input type="radio" name="scope_mode" value="all" checked> All inventory devices</label>
      <label><input type="radio" name="scope_mode" value="sites"> Selected sites</label>
      <label><input type="radio" name="scope_mode" value="devices"> Selected devices</label>
    </div>
    <div id="site-selector" class="scope-selector" hidden><strong>Choose sites</strong><div class="choice-grid"></div></div>
    <div id="device-selector" class="scope-selector" hidden>
      <label class="search-label">Search devices <input id="device-search" type="search" placeholder="Name, site, host, transport…"></label>
      <div class="device-actions"><button type="button" class="text-button" id="select-visible">Select visible</button><button type="button" class="text-button" id="clear-devices">Clear selection</button></div>
      <div class="device-list"></div>
    </div>
    <div id="scope-plan" class="scope-plan"></div>`;
  const siteGrid = content.querySelector("#site-selector .choice-grid");
  scope.sites.forEach((site) => siteGrid.append(scopeCheckbox("site-choice", site, site, true)));
  const deviceList = content.querySelector(".device-list");
  scope.devices.forEach((device) => {
    const label = `${device.name} — ${device.site} — ${device.host}`;
    const row = scopeCheckbox("device-choice", device.id, label, true);
    row.dataset.search = `${label} ${device.transport} ${device.site_type} ${device.edge_role}`.toLowerCase();
    deviceList.append(row);
  });
  content.querySelectorAll('input[name="scope_mode"]').forEach((radio) => radio.addEventListener("change", updateScopeView));
  content.querySelectorAll(".site-choice,.device-choice").forEach((box) => box.addEventListener("change", updateScopePlan));
  content.querySelector("#device-search").addEventListener("input", filterDevices);
  content.querySelector("#select-visible").addEventListener("click", () => setVisibleDevices(true));
  content.querySelector("#clear-devices").addEventListener("click", () => setVisibleDevices(false));
  content.hidden = false;
  updateScopeView();
}

function scopeCheckbox(className, value, text, checked) {
  const label = document.createElement("label");
  label.className = "scope-choice";
  const input = document.createElement("input");
  input.type = "checkbox";
  input.className = className;
  input.value = value;
  input.checked = checked;
  label.append(input, document.createTextNode(text));
  return label;
}

function updateScopeView() {
  const mode = document.querySelector('input[name="scope_mode"]:checked')?.value || "all";
  document.querySelector("#site-selector").hidden = mode !== "sites";
  document.querySelector("#device-selector").hidden = mode !== "devices";
  updateScopePlan();
}

function selectedScopeDevices() {
  const mode = document.querySelector('input[name="scope_mode"]:checked')?.value || "all";
  if (mode === "sites") {
    const sites = new Set(scopeSelections("site-choice"));
    return connectivityScope.devices.filter((device) => sites.has(device.site));
  }
  if (mode === "devices") {
    const devices = new Set(scopeSelections("device-choice"));
    return connectivityScope.devices.filter((device) => devices.has(device.id));
  }
  return connectivityScope.devices;
}

function updateScopePlan() {
  if (!connectivityScope) return;
  const selected = selectedScopeDevices();
  const sites = new Set(selected.map((device) => device.site));
  const workers = Math.max(1, Number(form.elements.concurrent_workers?.value) || 3);
  document.querySelector("#scope-plan").textContent = `${sites.size} selected site(s) · ${selected.length} selected device(s) · ${workers} concurrent worker(s) · ${Math.ceil(selected.length / workers)} estimated batch(es)`;
}

function filterDevices(event) {
  const query = event.target.value.trim().toLowerCase();
  document.querySelectorAll(".device-list .scope-choice").forEach((row) => {
    row.hidden = !row.dataset.search.includes(query);
  });
}

function setVisibleDevices(checked) {
  document.querySelectorAll(".device-list .scope-choice:not([hidden]) .device-choice").forEach((box) => {
    box.checked = checked;
  });
  updateScopePlan();
}

async function request(path, apply = false) {
  setBusy(true);
  hideResult();
  try {
    const response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": token },
      body: JSON.stringify({ tool_id: selectedTool.tool_id, values: values(), apply }),
    });
    const body = await response.json();
    if (!response.ok) throw new Error(body.error || "The request failed.");
    showResult(body, path === "/api/validate" ? "Plan validated" : "Run complete");
  } catch (error) {
    showResult({ message: error.message }, "Unable to continue", true);
  } finally {
    setBusy(false);
  }
}

function showResult(body, title, error = false) {
  resultPanel.classList.toggle("error", error);
  document.querySelector("#result-title").textContent = title;
  document.querySelector("#result-message").textContent = body.summary || body.message || "";
  const details = document.querySelector("#result-details");
  details.replaceChildren();
  const values = body.details || (body.output_directory ? { "Output folder": body.output_directory } : {});
  Object.entries(values).forEach(([key, value]) => {
    const term = document.createElement("dt");
    term.textContent = key.replaceAll("_", " ");
    const description = document.createElement("dd");
    description.textContent = formatValue(value);
    details.append(term, description);
  });
  const logs = document.querySelector("#result-logs");
  logs.textContent = (body.logs || []).join("\n");
  logs.hidden = !body.logs?.length;
  resultPanel.hidden = false;
}

function formatValue(value) {
  if (Array.isArray(value)) return value.join(", ");
  if (value && typeof value === "object") {
    return Object.entries(value).map(([key, item]) => `${key}: ${item}`).join(", ");
  }
  return String(value);
}

function hideResult() { resultPanel.hidden = true; }
function setBusy(busy) {
  document.querySelector("#validate-button").disabled = busy;
  document.querySelector("#run-button").disabled = busy;
}
function updateMode() {
  const maintenanceOperation = selectedTool?.tool_id === "maintenance-validator"
    ? form.elements.operation?.value
    : null;
  const offlineMaintenance = maintenanceOperation === "mock";
  if (offlineMaintenance) applyInput.checked = false;
  applyInput.disabled = offlineMaintenance;
  const live = applyInput.checked;
  const offlinePortCollection = selectedTool?.tool_id === "port-capacity"
    && form.elements.source_mode?.value === "mock";
  document.querySelector("#apply-label").textContent = offlineMaintenance
    ? "Offline comparison"
    : offlinePortCollection
    ? "Collect interface details"
    : "Enable live collection";
  document.querySelector("#apply-help").textContent = offlineMaintenance
    ? "Uses preserved fictional captures and makes no device connection."
    : offlinePortCollection
    ? "Uses only the selected local mock fixture; no network request is made."
    : "Off by default. Validation and report planning make no device connections.";
  document.querySelector("#mode-badge").textContent = live
    ? (offlinePortCollection ? "Offline collection" : "Live collection")
    : "Dry-run";
  document.querySelector("#mode-badge").classList.toggle("live", live);
  document.querySelector("#run-button").textContent = offlineMaintenance
    ? "Create offline sample report"
    : live
    ? (offlinePortCollection ? "Collect mock interface details" : "Run live collection")
    : "Create dry-run report";
  confirmationRow.hidden = !live;
  document.querySelectorAll('[data-apply-only="true"]').forEach((item) => { item.hidden = !live; });
  updateMaintenanceFields(maintenanceOperation);
  updateScopePlan();
}

function updateMaintenanceFields(operation) {
  if (!operation) return;
  const targetFields = ["inventory_file", "hostname", "device_type", "commands_file", "max_workers", "max_devices"];
  targetFields.forEach((name) => {
    const field = form.elements[name]?.closest(".field");
    if (field) field.hidden = operation === "mock";
  });
  ["baseline_file", "delay_minutes"].forEach((name) => {
    const field = form.elements[name]?.closest(".field");
    if (field) field.hidden = operation !== "postcheck";
  });
}

document.querySelector("#validate-button").addEventListener("click", () => request("/api/validate"));
applyInput.addEventListener("change", updateMode);
form.addEventListener("submit", (event) => {
  event.preventDefault();
  request("/api/run", applyInput.checked);
});

fetch("/api/tools")
  .then((response) => response.json())
  .then((body) => grid.replaceChildren(...body.tools.map(card)))
  .catch(() => { grid.textContent = "Unable to load the local tool registry."; });
