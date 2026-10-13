import { load, save, normalize, toJson, loadRemotes, saveRemotes, DEVICE_TYPES, POWER_STYLES,
  DEFAULT_FUNCTIONS, REMOTE_LAYOUT, uniqueName, activityName, newDevice, newActivity, putDevice,
  deleteDevice, setFunctionNames, activityDevices, buildSequences, suggestButtons, validate,
  irCoverage } from './store.js';
import { RemoteConnection, webHidSupported } from './usb.js';
import { REMOTES, hex4 } from './models.js';
import { toHex } from './protocol.js';

const REPO_URL = 'https://github.com/av1452/harmonyforge';

let config = load();
let remotes = loadRemotes();
// Forms edit a copy; `editing.key` is the original name (null when adding).
const ui = { tab: 'activities', editing: null, activity: null, button: null };
const usb = { conn: null, log: [], props: null, progress: null, busy: false, error: null };

const view = document.getElementById('view');
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const persist = () => save(config);
const typeLabel = (t) => DEVICE_TYPES.find(([v]) => v === t)?.[1] ?? t;
const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;

function toast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(toast.t);
  toast.t = setTimeout(() => t.classList.remove('show'), 2400);
}

function setTab(tab) {
  ui.tab = tab;
  ui.editing = null;
  for (const b of document.querySelectorAll('.tabs button')) {
    if (b.dataset.tab === tab) b.setAttribute('aria-current', 'page'); else b.removeAttribute('aria-current');
  }
  try { localStorage.setItem('harmonyforge.tab', tab); } catch { /* ignore */ }
  render();
}

const stepText = (s) => `${esc(s.device)}: ${esc(s.function)}${s.delay_ms >= 1000 ? ` <span class="muted">(wait ${s.delay_ms / 1000}s)</span>` : ''}`;

// ---------- Activities ----------

function activitiesView() {
  if (ui.editing?.kind === 'activity') return activityForm(ui.editing);
  const cards = Object.values(config.activities).map((a) => `<div class="card stack">
      <div class="row spread"><h2>${esc(a.label || a.name)}</h2><span class="chip">${plural(activityDevices(config, a).length, 'device')}</span></div>
      ${a.start_sequence.length ? `<div><div class="muted small">Starting it</div><ol class="steps small">${a.start_sequence.map((s) => `<li>${stepText(s)}</li>`).join('')}</ol></div>`
        : '<p class="muted small">No start-up steps yet.</p>'}
      ${a.stop_sequence.length ? `<div class="muted small">Turning off: ${a.stop_sequence.map((s) => `${esc(s.device)} ${esc(s.function)}`).join(', ')}</div>` : ''}
      <div class="row">
        <button class="btn" data-act="edit-activity" data-name="${esc(a.name)}">Edit</button>
        <button class="btn" data-act="map-activity" data-name="${esc(a.name)}">Buttons</button>
        <button class="btn danger" data-act="delete-activity" data-name="${esc(a.name)}">Delete</button>
      </div></div>`).join('');
  const hasDevices = Object.keys(config.devices).length > 0;
  return `<h1>Activities</h1>
    <p class="lede">An activity is something you do, like “Watch TV”. It turns on the right devices, switches inputs, and decides what each button controls.</p>
    <div class="row" style="margin-bottom:16px"><button class="btn primary" data-act="new-activity" ${hasDevices ? '' : 'disabled'}>Add activity</button>
    ${hasDevices ? '' : '<span class="muted small">Add a device first.</span>'}</div>
    ${cards ? `<div class="grid">${cards}</div>` : '<div class="card empty">No activities yet.</div>'}`;
}

function activityForm({ item: a, key }) {
  const used = activityDevices(config, a);
  const rows = Object.values(config.devices).map((d) => {
    const entry = used.find((x) => x.device === d.name);
    const inputs = d.inputs.length ? d.inputs : Object.keys(d.functions).filter((f) => /^input/i.test(f));
    return `<tr>
      <td><label class="row check"><input type="checkbox" name="use" value="${esc(d.name)}" ${entry ? 'checked' : ''}> ${esc(d.name)}</label></td>
      <td><select name="input:${esc(d.name)}" aria-label="Input for ${esc(d.name)}"><option value="">No input change</option>
        ${inputs.map((c) => `<option ${entry?.input === c ? 'selected' : ''}>${esc(c)}</option>`).join('')}</select></td></tr>`;
  }).join('');
  const roleSelect = (role, label) => `<div><label for="${role}">${label}</label><select id="${role}" name="${role}">
    <option value="">None</option>${Object.values(config.devices).map((d) => `<option ${a[role] === d.name ? 'selected' : ''}>${esc(d.name)}</option>`).join('')}</select></div>`;
  return `<h1>${key ? 'Edit activity' : 'New activity'}</h1>
    <form class="card stack" id="activity-form">
      <div><label for="a-label">Name</label><input id="a-label" name="label" required value="${esc(a.label || a.name)}" placeholder="Watch TV"></div>
      <div><h2>Devices and inputs</h2><table><thead><tr><th>Device</th><th>Input</th></tr></thead><tbody>${rows}</tbody></table>
        <p class="muted small">Start-up steps are worked out from this: each device is powered on (waiting for it to warm up), then inputs are set. Turning off reverses it.</p></div>
      <div class="grid">${roleSelect('volume_device', 'Volume controlled by')}${roleSelect('channel_device', 'Channels controlled by')}${roleSelect('primary_device', 'Menus and playback controlled by')}</div>
      <div class="row"><button class="btn primary" type="submit">Save</button><button class="btn" type="button" data-act="cancel">Cancel</button></div>
    </form>`;
}

function saveActivity(form) {
  const f = new FormData(form);
  const { item: a, key } = ui.editing;
  const label = f.get('label').trim();
  a.label = label;
  a.name = activityName(config.activities, label, key ?? undefined);
  for (const role of ['volume_device', 'channel_device', 'primary_device']) a[role] = f.get(role) || '';
  const chosen = f.getAll('use').map((device) => ({ device, input: f.get(`input:${device}`) || '' }));
  // Only rebuild the sequences when the device/input choice changed, so hand-tuned
  // sequences made with the Python tool survive an edit of the name or roles.
  if (JSON.stringify(chosen) !== JSON.stringify(activityDevices(config, a))) Object.assign(a, buildSequences(config, chosen));
  a.buttons = suggestButtons(config, a);
  if (key && key !== a.name) {
    config.activities = Object.fromEntries(Object.entries(config.activities)
      .map(([k, v]) => (k === key ? [a.name, a] : [k, v])));
  } else {
    config.activities[a.name] = a;
  }
  ui.editing = null;
  persist();
  toast('Activity saved');
  render();
}

// ---------- Devices ----------

function devicesView() {
  if (ui.editing?.kind === 'device') return deviceForm(ui.editing);
  const cards = Object.values(config.devices).map((d) => {
    const fns = Object.values(d.functions);
    const coded = fns.filter((f) => f.durations?.length).length;
    return `<div class="card stack">
    <div class="row spread"><h2>${esc(d.name)}</h2><span class="chip">${esc(typeLabel(d.type))}</span></div>
    <p class="muted small" style="margin:0">${esc([d.manufacturer, d.model].filter(Boolean).join(' · ') || 'No model set')}</p>
    <p class="small" style="margin:0">${plural(fns.length, 'command')} · <span class="${coded === fns.length && fns.length ? '' : 'muted'}">${coded} with IR codes</span></p>
    <div class="row"><button class="btn" data-act="edit-device" data-name="${esc(d.name)}">Edit</button>
    <button class="btn danger" data-act="delete-device" data-name="${esc(d.name)}">Delete</button></div></div>`;
  }).join('');
  return `<h1>Devices</h1>
    <p class="lede">The things your remote controls. Each device has a list of commands. Commands start as names only; the IR codes come from the harmonyforge command-line tool (learning from your old remote or importing a code database).</p>
    <div class="row" style="margin-bottom:16px"><button class="btn primary" data-act="new-device">Add device</button></div>
    ${cards ? `<div class="grid">${cards}</div>` : '<div class="card empty">No devices yet.</div>'}`;
}

function deviceForm({ item: d, key }) {
  const names = Object.keys(d.functions);
  return `<h1>${key ? 'Edit device' : 'New device'}</h1>
    <form class="card stack" id="device-form">
      <div class="grid">
        <div><label for="d-name">Name</label><input id="d-name" name="name" required value="${esc(d.name)}" placeholder="Living room TV"></div>
        <div><label for="d-type">Type</label><select id="d-type" name="type">${DEVICE_TYPES.map(([v, l]) => `<option value="${v}" ${d.type === v ? 'selected' : ''}>${esc(l)}</option>`).join('')}</select></div>
        <div><label for="d-man">Manufacturer</label><input id="d-man" name="manufacturer" value="${esc(d.manufacturer)}"></div>
        <div><label for="d-model">Model number</label><input id="d-model" name="model" value="${esc(d.model)}"></div>
        <div><label for="d-power">Power</label><select id="d-power" name="power_style">${POWER_STYLES.map(([v, l]) => `<option value="${v}" ${d.power_style === v ? 'selected' : ''}>${esc(l)}</option>`).join('')}</select></div>
        <div><label for="d-delay">Warm-up time after power on (seconds)</label><input id="d-delay" name="delay" type="number" min="0" max="60" step="0.5" value="${d.power_on_delay_ms / 1000}"></div>
      </div>
      <div><label for="d-cmds">Commands (one per line)</label><textarea id="d-cmds" name="functions" rows="8" class="mono">${esc(names.join('\n'))}</textarea>
      <p class="muted small">Leave empty to start with common commands for this device type. Renaming a command drops any IR code it had.</p></div>
      <div class="row"><button class="btn primary" type="submit">Save</button><button class="btn" type="button" data-act="cancel">Cancel</button></div>
    </form>`;
}

function saveDevice(form) {
  const f = new FormData(form);
  const { item: d, key } = ui.editing;
  d.name = uniqueName(config.devices, f.get('name').replace(/\//g, '-'), key ?? undefined);
  d.type = f.get('type');
  d.manufacturer = f.get('manufacturer').trim();
  d.model = f.get('model').trim();
  d.power_style = f.get('power_style');
  d.power_on_delay_ms = Math.round(Number(f.get('delay') || 0) * 1000);
  const names = [...new Set(f.get('functions').split('\n').map((s) => s.trim()).filter(Boolean))];
  setFunctionNames(d, names.length ? names : [...(DEFAULT_FUNCTIONS[d.type] ?? ['PowerToggle'])]);
  putDevice(config, key, d);
  ui.editing = null;
  persist();
  toast('Device saved');
  render();
}

// ---------- Buttons ----------

function buttonsView() {
  const all = Object.values(config.activities);
  if (!all.length) return `<h1>Buttons</h1><div class="card empty">Create an activity first, then choose what each button does in it.</div>`;
  const a = config.activities[ui.activity] ?? all[0];
  ui.activity = a.name;
  const keys = REMOTE_LAYOUT.map(([k, label]) => (k
    ? `<button data-act="pick-button" data-key="${k}" class="${a.buttons[k] ? 'mapped' : ''} ${ui.button === k ? 'selected' : ''}" title="${esc(a.buttons[k] ?? 'Not mapped')}">${esc(label)}</button>`
    : '<button class="gap" tabindex="-1" aria-hidden="true"></button>')).join('');
  let editor = '<p class="muted">Pick a button on the remote to choose what it does.</p>';
  if (ui.button) {
    const devices = [...new Set([...activityDevices(config, a).map((x) => x.device),
      a.volume_device, a.channel_device, a.primary_device].filter((n) => config.devices[n]))];
    const options = devices.map((n) => `<optgroup label="${esc(n)}">${Object.keys(config.devices[n].functions).map((fn) => {
      const v = `${n}/${fn}`;
      return `<option value="${esc(v)}" ${a.buttons[ui.button] === v ? 'selected' : ''}>${esc(fn)}</option>`;
    }).join('')}</optgroup>`).join('');
    const label = REMOTE_LAYOUT.find(([k]) => k === ui.button)?.[1];
    editor = `<h2>${esc(label)} <span class="muted small mono">${esc(ui.button)}</span></h2>
      <label for="b-cmd">Sends</label>
      <select id="b-cmd" data-act="set-button"><option value="">Nothing</option>${options}</select>`;
  }
  const mapped = Object.entries(a.buttons).map(([b, target]) => `<tr><td class="mono">${esc(b)}</td><td class="mono">${esc(target)}</td></tr>`).join('');
  return `<h1>Buttons</h1>
    <p class="lede">Choose what each button sends during an activity.</p>
    <div class="row" style="margin-bottom:16px"><label for="b-act" style="margin:0">Activity</label>
      <select id="b-act" data-act="pick-activity" style="width:auto">${all.map((x) => `<option value="${esc(x.name)}" ${x.name === a.name ? 'selected' : ''}>${esc(x.label || x.name)}</option>`).join('')}</select>
      <button class="btn" data-act="auto-buttons">Fill in suggestions</button></div>
    <div class="layout"><div class="remote" aria-label="Remote buttons">${keys}</div>
      <div class="stack"><div class="card">${editor}</div>
      <div class="card"><h2>Mapped buttons</h2>${mapped ? `<table><thead><tr><th>Button</th><th>Sends</th></tr></thead><tbody>${mapped}</tbody></table>` : '<p class="muted">None yet.</p>'}</div></div></div>`;
}

// ---------- USB remote ----------

function remoteView() {
  if (!webHidSupported()) {
    return `<h1>USB remote</h1><div class="card"><p>This browser can't talk to USB devices. Use a recent Chrome or Edge on a computer (WebHID), opened at the https:// link or localhost.</p></div>`;
  }
  const c = usb.conn;
  const info = c?.info;
  const props = usb.props ? Object.entries(usb.props).map(([k, v]) => `<tr><td class="mono">${esc(k)}</td><td class="mono">${esc(v)}</td></tr>`).join('') : '';
  const supported = REMOTES.map((r) => `<tr><td class="mono">${hex4(r.vid)}:${hex4(r.pid)}</td><td>${esc(r.name)}</td><td><span class="chip ${r.protocol === 'legacy' ? 'warn' : 'ok'}">${r.protocol === 'legacy' ? 'use Python tool' : r.protocol === 'mixed' ? 'some models' : 'supported'}</span></td></tr>`).join('');
  return `<h1>USB remote</h1>
    <p class="lede">Plug your remote or hub into this computer with a USB cable, then connect to read its model, firmware and serial number.</p>
    <div class="card stack">
      <div class="row">
        ${c ? `<span class="chip ok">Connected</span><strong>${esc(c.device.productName || info?.name || 'Remote')}</strong>
          <span class="muted small mono">${hex4(c.device.vendorId)}:${hex4(c.device.productId)} · ${c.width}-byte reports</span>`
          : '<span class="chip">Not connected</span>'}
      </div>
      <div class="row">
        ${c ? `<button class="btn primary" data-act="usb-identify" ${usb.busy || info?.protocol === 'legacy' ? 'disabled' : ''}>Read remote info</button>
               <button class="btn" data-act="usb-disconnect" ${usb.busy ? 'disabled' : ''}>Disconnect</button>`
            : '<button class="btn primary" data-act="usb-connect">Connect remote</button>'}
      </div>
      ${info?.protocol === 'legacy' ? `<p class="small">This model uses the older USB protocol, which the browser app can’t read yet. Use the harmonyforge command-line tool instead: <code>harmonyforge identify</code>. See <a href="${REPO_URL}#installing">installing harmonyforge</a>.</p>` : ''}
      ${info?.protocol === 'mixed' ? `<p class="small">This USB ID is shared by newer and older models. If reading fails, it's probably a Harmony 665 or similar older remote: use <code>harmonyforge identify</code> from the <a href="${REPO_URL}#installing">command-line tool</a> instead.</p>` : ''}
      ${usb.progress ? `<progress value="${usb.progress[0]}" max="${usb.progress[1]}"></progress>` : ''}
      ${usb.error ? `<p class="small" style="color:var(--danger)">${esc(usb.error)}</p>` : ''}
    </div>
    ${props ? `<div class="card"><h2>Remote info</h2><table><tbody>${props}</tbody></table>
      <div class="row" style="margin-top:12px"><button class="btn" data-act="usb-save">Use this remote for my setup</button></div></div>` : ''}
    ${usb.log.length ? `<div class="card"><div class="row spread"><h2>Packet log</h2><div class="row"><button class="btn" data-act="usb-copy">Copy</button><button class="btn" data-act="usb-clear">Clear</button></div></div>
      <div class="log">${esc(usb.log.slice(-200).join('\n'))}</div></div>` : ''}
    ${remotes.length ? `<div class="card"><h2>My remotes</h2><table><thead><tr><th>Model</th><th>Firmware</th><th>Serial</th></tr></thead><tbody>
      ${remotes.map((r) => `<tr><td>${esc(r.name)}</td><td class="mono">${esc(r.props?.fw_ver ?? '')}</td><td class="mono">${esc(r.props?.serial_number ?? '')}</td></tr>`).join('')}</tbody></table></div>` : ''}
    <details class="card"><summary>Remotes this app recognises</summary><table style="margin-top:10px"><tbody>${supported}</tbody></table></details>`;
}

const usbLog = (dir, bytes) => {
  usb.log.push(`${dir === 'out' ? '→' : '←'} ${toHex(bytes.subarray(0, 24))}${bytes.length > 24 ? ' …' : ''}`);
  if (ui.tab === 'remote') render();
};

async function usbAction(act) {
  usb.error = null;
  try {
    if (act === 'usb-connect') {
      usb.conn = await RemoteConnection.request(usbLog);
      usb.props = null;
    } else if (act === 'usb-disconnect') {
      await usb.conn?.close();
      usb.conn = null;
    } else if (act === 'usb-identify') {
      usb.busy = true; render();
      usb.props = await usb.conn.identify((n, total) => { usb.progress = [n, total]; render(); });
    } else if (act === 'usb-save') {
      const name = usb.conn.device.productName || usb.conn.info?.name || 'Remote';
      const serial = usb.props.serial_number;
      remotes = remotes.filter((r) => !serial || r.props?.serial_number !== serial);
      remotes.push({ name, props: usb.props });
      saveRemotes(remotes);
      config.remote_model = name;
      const skin = Number.parseInt(usb.props.skin, 10);
      if (Number.isFinite(skin)) config.remote_skin = skin;
      persist(); toast('Remote saved and set as this setup’s remote');
    } else if (act === 'usb-copy') {
      await navigator.clipboard.writeText(usb.log.join('\n'));
      toast('Packet log copied');
    } else if (act === 'usb-clear') {
      usb.log = [];
    }
  } catch (e) {
    if (e?.name !== 'NotFoundError') usb.error = e?.message ?? String(e);
  } finally {
    usb.busy = false; usb.progress = null;
    render();
  }
}

// ---------- Setup file ----------

function setupView() {
  const warnings = validate(config);
  const { withCode, total } = irCoverage(config);
  return `<h1>Setup file</h1>
    <p class="lede">Your setup is saved in this browser and uses the same file format as the harmonyforge command-line tool, so you can move it between the two.</p>
    <div class="card stack">
      <div class="grid">
        <div><label for="s-name">Setup name</label><input id="s-name" data-act="rename-setup" value="${esc(config.name)}"></div>
        <div><label>Remote</label><div class="mono small" style="padding-top:8px">${esc(config.remote_model || 'Not set')}${config.remote_skin != null ? ` (skin ${esc(config.remote_skin)})` : ''}</div></div>
      </div>
      <p class="muted small" style="margin:0">${plural(Object.keys(config.devices).length, 'device')} · ${plural(Object.keys(config.activities).length, 'activity').replace('activitys', 'activities')} · ${withCode} of ${plural(total, 'command')} have IR codes</p>
      <div class="row"><button class="btn primary" data-act="export">Download setup file</button>
      <label class="btn" style="margin:0;color:inherit">Open setup file<input type="file" accept="application/json,.json" data-act="import" hidden></label></div>
    </div>
    <div class="card stack"><h2>Checks</h2>
      ${warnings.length ? `<ul class="small">${warnings.map((w) => `<li>${esc(w)}</li>`).join('')}</ul>` : '<p class="small">No problems found.</p>'}
      <p class="muted small">The same checks as <code>harmonyforge config validate</code>.</p></div>
    <div class="card stack"><h2>Using it with the command-line tool</h2>
      <ol class="small">
        <li>Download the setup file (for example <code>${esc(fileName())}</code>).</li>
        <li>Check it: <code>harmonyforge config validate ${esc(fileName())}</code></li>
        <li>Add IR codes, by learning from your old remote: <code>harmonyforge learn --device "TV" PowerOn PowerOff</code>, or importing a code database (see the <a href="${REPO_URL}#2-get-ir-codes">README</a>).</li>
        <li>Open the updated file here again with <strong>Open setup file</strong>.</li>
      </ol></div>
    <div class="card stack"><h2>Start over</h2><p class="muted small">Removes every device and activity from this browser. Download the setup file first if you want to keep it.</p>
      <div><button class="btn danger" data-act="reset">Delete everything</button></div></div>`;
}

const fileName = () => `${(config.name || 'setup').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'setup'}.json`;

function exportConfig() {
  const blob = new Blob([toJson(config)], { type: 'application/json' });
  const a = Object.assign(document.createElement('a'), { href: URL.createObjectURL(blob), download: fileName() });
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

async function importConfig(file) {
  try {
    config = normalize(JSON.parse(await file.text()));
    ui.activity = null; ui.button = null;
    persist(); toast(`Opened “${config.name}”`); render();
  } catch (e) {
    toast(`Couldn’t open that file: ${e.message}`);
  }
}

// ---------- Wiring ----------

const views = { activities: activitiesView, devices: devicesView, buttons: buttonsView, remote: remoteView, setup: setupView };

function render() {
  view.innerHTML = views[ui.tab]();
}

document.querySelector('.tabs').addEventListener('click', (e) => {
  const b = e.target.closest('button[data-tab]');
  if (b) setTab(b.dataset.tab);
});

view.addEventListener('submit', (e) => {
  e.preventDefault();
  if (e.target.id === 'device-form') saveDevice(e.target);
  if (e.target.id === 'activity-form') saveActivity(e.target);
});

view.addEventListener('change', (e) => {
  const act = e.target.dataset.act;
  if (act === 'pick-activity') { ui.activity = e.target.value; ui.button = null; render(); }
  if (act === 'set-button') {
    const a = config.activities[ui.activity];
    if (!e.target.value) delete a.buttons[ui.button]; else a.buttons[ui.button] = e.target.value;
    persist(); render();
  }
  if (act === 'rename-setup') { config.name = e.target.value.trim() || 'My Remote'; persist(); render(); }
  if (act === 'import' && e.target.files[0]) importConfig(e.target.files[0]);
});

view.addEventListener('click', (e) => {
  const el = e.target.closest('[data-act]');
  if (!el || el.tagName === 'SELECT' || el.tagName === 'INPUT') return;
  const { act, name } = el.dataset;
  const copy = (x) => structuredClone(x);
  switch (act) {
    case 'new-device': ui.editing = { kind: 'device', key: null, item: newDevice('', DEVICE_TYPES[0][0]) }; break;
    case 'edit-device': ui.editing = { kind: 'device', key: name, item: copy(config.devices[name]) }; break;
    case 'delete-device':
      if (!confirm(`Delete “${name}”? It will be removed from every activity.`)) return;
      deleteDevice(config, name); persist(); break;
    case 'new-activity': ui.editing = { kind: 'activity', key: null, item: newActivity('', '') }; break;
    case 'edit-activity': ui.editing = { kind: 'activity', key: name, item: copy(config.activities[name]) }; break;
    case 'map-activity': ui.activity = name; ui.button = null; setTab('buttons'); return;
    case 'delete-activity':
      if (!confirm('Delete this activity?')) return;
      delete config.activities[name]; persist(); break;
    case 'cancel': ui.editing = null; break;
    case 'pick-button': ui.button = el.dataset.key; break;
    case 'auto-buttons': {
      const a = config.activities[ui.activity];
      a.buttons = suggestButtons(config, a); persist(); toast('Suggestions added'); break;
    }
    case 'export': exportConfig(); return;
    case 'reset':
      if (!confirm('Delete your whole setup from this browser?')) return;
      config = normalize({}); persist(); break;
    default:
      if (act?.startsWith('usb-')) { usbAction(act); return; }
      return;
  }
  render();
});

if (webHidSupported()) {
  navigator.hid.addEventListener('disconnect', (e) => {
    if (usb.conn?.device === e.device) { usb.conn = null; usb.error = 'Remote was unplugged.'; render(); }
  });
}

if ('serviceWorker' in navigator && location.protocol !== 'file:') {
  navigator.serviceWorker.register('sw.js').catch(() => {});
}

try {
  const saved = localStorage.getItem('harmonyforge.tab') ?? localStorage.getItem('chorus.tab');
  ui.tab = saved === 'backup' ? 'setup' : (views[saved] ? saved : ui.tab);
} catch { /* ignore */ }
setTab(ui.tab);
