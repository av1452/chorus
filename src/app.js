import { load, save, normalize, uid, DEVICE_TYPES, DEFAULT_COMMANDS, BUTTONS,
  suggestButtons, startSequence } from './store.js';
import { RemoteConnection, webHidSupported } from './usb.js';
import { REMOTES, hex4 } from './models.js';
import { toHex } from './protocol.js';

let config = load();
const ui = { tab: 'activities', editingDevice: null, editingActivity: null, activityId: null, button: null };
const usb = { conn: null, log: [], props: null, progress: null, busy: false, error: null };

const view = document.getElementById('view');
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const persist = () => save(config);
const deviceById = (id) => config.devices.find((d) => d.id === id);

/** Forms edit a copy; saving puts it back (or adds it when new). */
function upsert(list, item) {
  if (!item.id) { item.id = uid(); list.push(item); return; }
  const i = list.findIndex((x) => x.id === item.id);
  if (i >= 0) list[i] = item; else list.push(item);
}

function toast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(toast.t);
  toast.t = setTimeout(() => t.classList.remove('show'), 2200);
}

function setTab(tab) {
  ui.tab = tab;
  for (const b of document.querySelectorAll('.tabs button')) {
    if (b.dataset.tab === tab) b.setAttribute('aria-current', 'page'); else b.removeAttribute('aria-current');
  }
  try { localStorage.setItem('chorus.tab', tab); } catch { /* ignore */ }
  render();
}

// ---------- Activities ----------

function activitiesView() {
  if (ui.editingActivity) return activityForm(ui.editingActivity);
  const list = config.activities.map((a) => {
    const steps = startSequence(a, config.devices);
    return `<div class="card stack">
      <div class="row spread"><h2>${esc(a.name)}</h2><span class="chip">${a.devices.length} device${a.devices.length === 1 ? '' : 's'}</span></div>
      ${steps.length ? `<ol class="steps small">${steps.map((s) => `<li>${esc(s.device)}: ${esc(s.command)}</li>`).join('')}</ol>`
        : '<p class="muted small">No start-up steps yet.</p>'}
      <div class="row">
        <button class="btn" data-act="edit-activity" data-id="${a.id}">Edit</button>
        <button class="btn" data-act="map-activity" data-id="${a.id}">Buttons</button>
        <button class="btn danger" data-act="delete-activity" data-id="${a.id}">Delete</button>
      </div></div>`;
  }).join('');
  return `<h1>Activities</h1>
    <p class="lede">An activity is something you do, like “Watch TV”. It turns on the right devices, switches inputs, and decides what each button controls.</p>
    <div class="row" style="margin-bottom:16px"><button class="btn primary" data-act="new-activity" ${config.devices.length ? '' : 'disabled'}>Add activity</button>
    ${config.devices.length ? '' : '<span class="muted small">Add a device first.</span>'}</div>
    ${list ? `<div class="grid">${list}</div>` : '<div class="card empty">No activities yet.</div>'}`;
}

function activityForm(a) {
  const rows = config.devices.map((d) => {
    const entry = a.devices.find((x) => x.deviceId === d.id);
    const inputs = d.commands.filter((c) => /^input/i.test(c));
    return `<tr>
      <td><label class="row" style="color:inherit;margin:0"><input type="checkbox" style="width:auto;min-height:0" name="use" value="${d.id}" ${entry ? 'checked' : ''}> ${esc(d.name)}</label></td>
      <td><select name="input-${d.id}" aria-label="Input for ${esc(d.name)}"><option value="">No input change</option>
        ${inputs.map((c) => `<option ${entry?.input === c ? 'selected' : ''}>${esc(c)}</option>`).join('')}</select></td></tr>`;
  }).join('');
  const roleSelect = (role, label) => `<div><label for="role-${role}">${label}</label><select id="role-${role}" name="role-${role}">
    <option value="">None</option>${config.devices.map((d) => `<option value="${d.id}" ${a.roles[role] === d.id ? 'selected' : ''}>${esc(d.name)}</option>`).join('')}</select></div>`;
  return `<h1>${a.id ? 'Edit activity' : 'New activity'}</h1>
    <form class="card stack" id="activity-form">
      <div><label for="a-name">Name</label><input id="a-name" name="name" required value="${esc(a.name)}" placeholder="Watch TV"></div>
      <div><h2>Devices and inputs</h2><table><thead><tr><th>Device</th><th>Input</th></tr></thead><tbody>${rows}</tbody></table></div>
      <div class="grid">${roleSelect('volume', 'Volume controlled by')}${roleSelect('playback', 'Channels and playback controlled by')}</div>
      <div class="row"><button class="btn primary" type="submit">Save</button><button class="btn" type="button" data-act="cancel-activity">Cancel</button></div>
    </form>`;
}

function saveActivity(form) {
  const f = new FormData(form);
  const a = ui.editingActivity;
  a.name = f.get('name').trim();
  a.devices = f.getAll('use').map((deviceId) => ({ deviceId, input: f.get(`input-${deviceId}`) || '' }));
  a.roles = { volume: f.get('role-volume') || '', playback: f.get('role-playback') || '' };
  a.buttons = suggestButtons(a, config.devices);
  upsert(config.activities, a);
  ui.editingActivity = null;
  persist();
  toast('Activity saved');
  render();
}

// ---------- Devices ----------

function devicesView() {
  if (ui.editingDevice) return deviceForm(ui.editingDevice);
  const list = config.devices.map((d) => `<div class="card stack">
    <div class="row spread"><h2>${esc(d.name)}</h2><span class="chip">${esc(d.type)}</span></div>
    <p class="muted small" style="margin:0">${esc([d.manufacturer, d.model].filter(Boolean).join(' · ') || 'No model set')}</p>
    <p class="small" style="margin:0">${d.commands.length} command${d.commands.length === 1 ? '' : 's'}</p>
    <div class="row"><button class="btn" data-act="edit-device" data-id="${d.id}">Edit</button>
    <button class="btn danger" data-act="delete-device" data-id="${d.id}">Delete</button></div></div>`).join('');
  return `<h1>Devices</h1>
    <p class="lede">The things your remote controls. Each device has a list of command names; activities and buttons use those commands.</p>
    <div class="row" style="margin-bottom:16px"><button class="btn primary" data-act="new-device">Add device</button></div>
    ${list ? `<div class="grid">${list}</div>` : '<div class="card empty">No devices yet.</div>'}`;
}

function deviceForm(d) {
  return `<h1>${d.id ? 'Edit device' : 'New device'}</h1>
    <form class="card stack" id="device-form">
      <div class="grid">
        <div><label for="d-name">Name</label><input id="d-name" name="name" required value="${esc(d.name)}" placeholder="Living room TV"></div>
        <div><label for="d-type">Type</label><select id="d-type" name="type">${DEVICE_TYPES.map((t) => `<option ${d.type === t ? 'selected' : ''}>${esc(t)}</option>`).join('')}</select></div>
        <div><label for="d-man">Manufacturer</label><input id="d-man" name="manufacturer" value="${esc(d.manufacturer)}"></div>
        <div><label for="d-model">Model number</label><input id="d-model" name="model" value="${esc(d.model)}"></div>
      </div>
      <div><label for="d-cmds">Commands (one per line)</label><textarea id="d-cmds" name="commands" rows="8" class="mono">${esc(d.commands.join('\n'))}</textarea>
      <p class="muted small">Leave empty to start with common commands for this device type.</p></div>
      <div class="row"><button class="btn primary" type="submit">Save</button><button class="btn" type="button" data-act="cancel-device">Cancel</button></div>
    </form>`;
}

function saveDevice(form) {
  const f = new FormData(form);
  const d = ui.editingDevice;
  Object.assign(d, { name: f.get('name').trim(), type: f.get('type'), manufacturer: f.get('manufacturer').trim(), model: f.get('model').trim() });
  const cmds = f.get('commands').split('\n').map((s) => s.trim()).filter(Boolean);
  d.commands = cmds.length ? [...new Set(cmds)] : [...(DEFAULT_COMMANDS[d.type] ?? ['PowerToggle'])];
  upsert(config.devices, d);
  ui.editingDevice = null;
  persist();
  toast('Device saved');
  render();
}

// ---------- Buttons ----------

function buttonsView() {
  if (!config.activities.length) {
    return `<h1>Buttons</h1><div class="card empty">Create an activity first, then choose what each button does in it.</div>`;
  }
  const a = config.activities.find((x) => x.id === ui.activityId) ?? config.activities[0];
  ui.activityId = a.id;
  const pad = ['power', 'menu', 'guide', null, 'up', 'back', 'left', 'ok', 'right', null, 'down', null,
    'volUp', 'mute', 'chUp', 'volDown', null, 'chDown', 'rew', 'play', 'ff', 'stop', 'pause', 'rec'];
  const labels = Object.fromEntries(BUTTONS);
  const keys = pad.map((k) => k
    ? `<button data-act="pick-button" data-key="${k}" class="${a.buttons[k] ? 'mapped' : ''} ${ui.button === k ? 'selected' : ''}" title="${esc(a.buttons[k] ? `${deviceById(a.buttons[k].deviceId)?.name}: ${a.buttons[k].command}` : 'Not mapped')}">${esc(labels[k])}</button>`
    : '<button class="gap" tabindex="-1" aria-hidden="true"></button>').join('');
  let editor = '<p class="muted">Pick a button on the remote to choose what it does.</p>';
  if (ui.button) {
    const cur = a.buttons[ui.button];
    const options = a.devices.map(({ deviceId }) => deviceById(deviceId)).filter(Boolean)
      .map((d) => `<optgroup label="${esc(d.name)}">${d.commands.map((c) => {
        const v = `${d.id}|${c}`;
        return `<option value="${esc(v)}" ${cur && `${cur.deviceId}|${cur.command}` === v ? 'selected' : ''}>${esc(c)}</option>`;
      }).join('')}</optgroup>`).join('');
    editor = `<h2>${esc(labels[ui.button])}</h2>
      <label for="b-cmd">Sends</label>
      <select id="b-cmd" data-act="set-button"><option value="">Nothing</option>${options}</select>`;
  }
  const mapped = BUTTONS.filter(([k]) => a.buttons[k]).map(([k, l]) => {
    const m = a.buttons[k];
    return `<tr><td>${esc(l)}</td><td>${esc(deviceById(m.deviceId)?.name ?? '?')}</td><td class="mono">${esc(m.command)}</td></tr>`;
  }).join('');
  return `<h1>Buttons</h1>
    <p class="lede">Choose what each button sends during an activity.</p>
    <div class="row" style="margin-bottom:16px"><label for="b-act" style="margin:0">Activity</label>
      <select id="b-act" data-act="pick-activity" style="width:auto">${config.activities.map((x) => `<option value="${x.id}" ${x.id === a.id ? 'selected' : ''}>${esc(x.name)}</option>`).join('')}</select>
      <button class="btn" data-act="auto-buttons">Fill in suggestions</button></div>
    <div class="layout"><div class="remote" aria-label="Remote buttons">${keys}</div>
      <div class="stack"><div class="card">${editor}</div>
      <div class="card"><h2>Mapped buttons</h2>${mapped ? `<table><thead><tr><th>Button</th><th>Device</th><th>Command</th></tr></thead><tbody>${mapped}</tbody></table>` : '<p class="muted">None yet.</p>'}</div></div></div>`;
}

// ---------- USB remote ----------

function remoteView() {
  if (!webHidSupported()) {
    return `<h1>USB remote</h1><div class="card"><p>This browser can't talk to USB devices. Use a recent Chrome or Edge on a computer (WebHID), served over HTTPS or localhost.</p></div>`;
  }
  const c = usb.conn;
  const info = c?.info;
  const props = usb.props ? Object.entries(usb.props).map(([k, v]) => `<tr><td class="mono">${esc(k)}</td><td class="mono">${esc(v)}</td></tr>`).join('') : '';
  const supported = REMOTES.map((r) => `<tr><td class="mono">${hex4(r.vid)}:${hex4(r.pid)}</td><td>${esc(r.name)}</td><td><span class="chip ${r.protocol === 'legacy' ? 'warn' : 'ok'}">${r.protocol === 'legacy' ? 'not yet' : r.protocol === 'mixed' ? 'some models' : 'supported'}</span></td></tr>`).join('');
  return `<h1>USB remote</h1>
    <p class="lede">Plug your remote or hub into this computer with a USB cable, then connect to read its model, firmware and serial number.</p>
    <div class="card stack">
      <div class="row">
        ${c ? `<span class="chip ok">Connected</span><strong>${esc(c.device.productName || info?.name || 'Remote')}</strong>
          <span class="muted small mono">${hex4(c.device.vendorId)}:${hex4(c.device.productId)} · ${c.width}-byte reports</span>`
          : '<span class="chip">Not connected</span>'}
      </div>
      <div class="row">
        ${c ? `<button class="btn primary" data-act="usb-identify" ${usb.busy ? 'disabled' : ''}>Read remote info</button>
               <button class="btn" data-act="usb-disconnect" ${usb.busy ? 'disabled' : ''}>Disconnect</button>`
            : '<button class="btn primary" data-act="usb-connect">Connect remote</button>'}
      </div>
      ${info?.protocol === 'legacy' ? '<p class="small" style="color:var(--danger)">This model uses an older protocol that Chorus can’t read yet.</p>' : ''}
      ${usb.progress ? `<progress value="${usb.progress[0]}" max="${usb.progress[1]}"></progress>` : ''}
      ${usb.error ? `<p class="small" style="color:var(--danger)">${esc(usb.error)}</p>` : ''}
    </div>
    ${props ? `<div class="card"><h2>Remote info</h2><table><tbody>${props}</tbody></table>
      <div class="row" style="margin-top:12px"><button class="btn" data-act="usb-save">Save to my remotes</button></div></div>` : ''}
    ${usb.log.length ? `<div class="card"><div class="row spread"><h2>Packet log</h2><button class="btn" data-act="usb-clear">Clear</button></div>
      <div class="log">${esc(usb.log.slice(-200).join('\n'))}</div></div>` : ''}
    ${config.remotes.length ? `<div class="card"><h2>My remotes</h2><table><thead><tr><th>Model</th><th>Firmware</th><th>Serial</th></tr></thead><tbody>
      ${config.remotes.map((r) => `<tr><td>${esc(r.name)}</td><td class="mono">${esc(r.props.fw_ver ?? '')}</td><td class="mono">${esc(r.props.serial_number ?? '')}</td></tr>`).join('')}</tbody></table></div>` : ''}
    <details class="card"><summary>Remotes Chorus recognises</summary><table style="margin-top:10px"><tbody>${supported}</tbody></table></details>`;
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
      config.remotes = config.remotes.filter((r) => r.props.serial_number !== usb.props.serial_number || !usb.props.serial_number);
      config.remotes.push({ id: uid(), name: usb.conn.device.productName || usb.conn.info?.name || 'Remote', props: usb.props });
      persist(); toast('Remote saved');
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

// ---------- Backup ----------

function backupView() {
  return `<h1>Backup</h1>
    <p class="lede">Your setup is saved in this browser only. Export it to keep a copy or move it to another computer.</p>
    <div class="card stack">
      <div class="row"><button class="btn primary" data-act="export">Export setup</button>
      <label class="btn" style="margin:0;color:inherit">Import setup<input type="file" accept="application/json,.json" data-act="import" hidden></label></div>
      <p class="muted small">${config.devices.length} devices · ${config.activities.length} activities · ${config.remotes.length} remotes</p>
    </div>
    <div class="card stack"><h2>Start over</h2><p class="muted small">Removes every device, activity and saved remote from this browser.</p>
      <div><button class="btn danger" data-act="reset">Delete everything</button></div></div>`;
}

function exportConfig() {
  const blob = new Blob([JSON.stringify(config, null, 2)], { type: 'application/json' });
  const a = Object.assign(document.createElement('a'), { href: URL.createObjectURL(blob), download: 'chorus-setup.json' });
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

async function importConfig(file) {
  try {
    config = normalize(JSON.parse(await file.text()));
    persist(); toast('Setup imported'); render();
  } catch (e) {
    toast(`Couldn’t import: ${e.message}`);
  }
}

// ---------- Wiring ----------

const views = { activities: activitiesView, devices: devicesView, buttons: buttonsView, remote: remoteView, backup: backupView };

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
  if (act === 'pick-activity') { ui.activityId = e.target.value; ui.button = null; render(); }
  if (act === 'set-button') {
    const a = config.activities.find((x) => x.id === ui.activityId);
    if (!e.target.value) delete a.buttons[ui.button];
    else { const [deviceId, command] = e.target.value.split('|'); a.buttons[ui.button] = { deviceId, command }; }
    persist(); render();
  }
  if (act === 'import' && e.target.files[0]) importConfig(e.target.files[0]);
});

view.addEventListener('click', (e) => {
  const el = e.target.closest('[data-act]');
  if (!el || el.tagName === 'SELECT' || el.tagName === 'INPUT') return;
  const { act, id } = el.dataset;
  switch (act) {
    case 'new-device': ui.editingDevice = { name: '', type: DEVICE_TYPES[0], manufacturer: '', model: '', commands: [] }; break;
    case 'edit-device': ui.editingDevice = structuredClone(deviceById(id)); break;
    case 'cancel-device': ui.editingDevice = null; break;
    case 'delete-device':
      if (!confirm('Delete this device? It will be removed from every activity.')) return;
      config.devices = config.devices.filter((d) => d.id !== id);
      for (const a of config.activities) {
        a.devices = a.devices.filter((x) => x.deviceId !== id);
        for (const [k, m] of Object.entries(a.buttons)) if (m.deviceId === id) delete a.buttons[k];
      }
      persist(); break;
    case 'new-activity': ui.editingActivity = { name: '', devices: [], roles: {}, buttons: {} }; break;
    case 'edit-activity': ui.editingActivity = structuredClone(config.activities.find((a) => a.id === id)); break;
    case 'cancel-activity': ui.editingActivity = null; break;
    case 'map-activity': ui.activityId = id; ui.button = null; setTab('buttons'); return;
    case 'delete-activity':
      if (!confirm('Delete this activity?')) return;
      config.activities = config.activities.filter((a) => a.id !== id); persist(); break;
    case 'pick-button': ui.button = el.dataset.key; break;
    case 'auto-buttons': {
      const a = config.activities.find((x) => x.id === ui.activityId);
      a.buttons = suggestButtons(a, config.devices); persist(); toast('Suggestions added'); break;
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
  const saved = localStorage.getItem('chorus.tab');
  if (saved && views[saved]) ui.tab = saved;
} catch { /* ignore */ }
setTab(ui.tab);
