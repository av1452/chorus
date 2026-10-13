// The setup is stored in the Chorus configuration format (docs/config-format.md),
// so a file exported here works with `chorus config validate` and `chorus serve`,
// and a file made by the Python tool opens here. Fields this app doesn't edit (IR waveforms,
// delays, stop sequences, global buttons…) are kept as they are.

const CONFIG_KEY = 'chorus.setup.v1';
const REMOTES_KEY = 'chorus.remotes.v2';
// Where earlier versions kept the setup, newest first. The oldest used a different
// (array-based) format, which normalize() converts.
const OLDER_CONFIG_KEYS = ['harmonyforge.config.v1', 'chorus.config.v1'];
const OLDER_REMOTES_KEYS = ['harmonyforge.remotes.v1'];

export const SCHEMA_VERSION = 1;

export const DEVICE_TYPES = [
  ['television', 'TV'], ['av_receiver', 'AV receiver'], ['soundbar', 'Soundbar'],
  ['cable_satellite', 'Cable / satellite box'], ['streaming', 'Streaming player'],
  ['bluray_dvd', 'Blu-ray / DVD'], ['game_console', 'Game console'], ['projector', 'Projector'],
  ['amplifier', 'Amplifier'], ['lighting', 'Lights'], ['other', 'Other'],
];

export const POWER_STYLES = [
  ['discrete', 'Separate Power On and Power Off (most reliable)'],
  ['toggle', 'One power button that switches on and off'],
  ['none', 'Leave power alone'],
];

const DIGITS = ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9'];
const NAV = ['DirectionUp', 'DirectionDown', 'DirectionLeft', 'DirectionRight', 'OK', 'Menu', 'Back', 'Home'];
const TRANSPORT = ['Play', 'Pause', 'Stop', 'Rewind', 'FastForward'];

/** Starting command names for a new device of each type (no IR codes yet). */
export const DEFAULT_FUNCTIONS = {
  television: ['PowerOn', 'PowerOff', 'InputHDMI1', 'InputHDMI2', 'InputHDMI3', 'VolumeUp', 'VolumeDown', 'Mute', 'Menu', 'Back'],
  av_receiver: ['PowerOn', 'PowerOff', 'VolumeUp', 'VolumeDown', 'Mute', 'InputHDMI1', 'InputHDMI2'],
  soundbar: ['PowerOn', 'PowerOff', 'VolumeUp', 'VolumeDown', 'Mute', 'InputHDMI', 'InputOptical'],
  cable_satellite: ['PowerToggle', 'ChannelUp', 'ChannelDown', 'PrevChannel', 'Guide', 'Info', 'Exit', ...NAV, 'Record', ...TRANSPORT, ...DIGITS],
  streaming: ['PowerToggle', ...NAV, ...TRANSPORT],
  bluray_dvd: ['PowerOn', 'PowerOff', ...NAV, ...TRANSPORT, 'SkipBack', 'SkipForward'],
  game_console: ['PowerToggle'],
  projector: ['PowerOn', 'PowerOff', 'InputHDMI1', 'InputHDMI2', 'Menu', 'Back'],
  amplifier: ['PowerOn', 'PowerOff', 'VolumeUp', 'VolumeDown', 'Mute'],
  lighting: ['PowerOn', 'PowerOff'],
  other: ['PowerToggle'],
};

/** On-screen remote, using the physical button names chorus uses. */
export const REMOTE_LAYOUT = [
  ['PowerToggle', 'Power'], ['Menu', 'Menu'], ['Guide', 'Guide'],
  ['Info', 'Info'], ['DirectionUp', 'Up'], ['Back', 'Back'],
  ['DirectionLeft', 'Left'], ['OK', 'OK'], ['DirectionRight', 'Right'],
  ['Home', 'Home'], ['DirectionDown', 'Down'], ['Exit', 'Exit'],
  ['VolumeUp', 'Vol +'], ['Mute', 'Mute'], ['ChannelUp', 'Ch +'],
  ['VolumeDown', 'Vol −'], ['PrevChannel', 'Prev'], ['ChannelDown', 'Ch −'],
  ['Rewind', 'Rewind'], ['Play', 'Play'], ['FastForward', 'Fast fwd'],
  ['Stop', 'Stop'], ['Pause', 'Pause'], ['Record', 'Record'],
  ['1', '1'], ['2', '2'], ['3', '3'], ['4', '4'], ['5', '5'], ['6', '6'],
  ['7', '7'], ['8', '8'], ['9', '9'], [null, ''], ['0', '0'], [null, ''],
];

const now = () => new Date().toISOString().replace(/\.\d{3}Z$/, '+00:00');

export function blankConfig(name = 'My Remote') {
  const t = now();
  return { schema_version: SCHEMA_VERSION, name, remote_model: '', remote_skin: null,
    created: t, modified: t, notes: '', devices: {}, activities: {}, global_buttons: {} };
}

// ---------- Loading and saving ----------

function readJson(key) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function writeJson(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* storage unavailable */ }
}

export function load() {
  const current = readJson(CONFIG_KEY);
  if (current) {
    try { return normalize(current); } catch { /* fall through */ }
  }
  for (const key of OLDER_CONFIG_KEYS) {
    const older = readJson(key);
    if (!older) continue;
    try {
      const migrated = normalize(older);
      writeJson(CONFIG_KEY, migrated);
      if (Array.isArray(older.remotes) && !readJson(REMOTES_KEY)) writeJson(REMOTES_KEY, older.remotes);
      return migrated;
    } catch { /* try the next one */ }
  }
  return blankConfig();
}

export function save(config) {
  config.modified = now();
  writeJson(CONFIG_KEY, config);
}

export function loadRemotes() {
  for (const key of [REMOTES_KEY, ...OLDER_REMOTES_KEYS]) {
    const r = readJson(key);
    if (Array.isArray(r)) return r;
  }
  return [];
}
export const saveRemotes = (remotes) => writeJson(REMOTES_KEY, remotes);

// Key order used by the Python tool's RemoteConfig.to_dict(), so files diff cleanly
// whichever side saved them. Keys not listed keep their place after these.
const ORDER = {
  config: ['schema_version', 'name', 'remote_model', 'remote_skin', 'created', 'modified', 'notes', 'devices', 'activities', 'global_buttons'],
  device: ['name', 'manufacturer', 'model', 'type', 'power_style', 'inputs', 'power_on_delay_ms', 'inter_command_delay_ms', 'repeat_count', 'notes', 'functions'],
  function: ['name', 'label', 'frequency', 'durations', 'protocol', 'source'],
  activity: ['name', 'label', 'icon', 'volume_device', 'channel_device', 'primary_device', 'buttons', 'start_sequence', 'stop_sequence'],
  step: ['device', 'function', 'delay_ms', 'repeat'],
};

function ordered(obj, keys) {
  const out = {};
  for (const k of keys) if (k in obj) out[k] = obj[k];
  for (const k of Object.keys(obj)) if (!(k in out)) out[k] = obj[k];
  return out;
}

const mapValues = (obj, fn) => Object.fromEntries(Object.entries(obj).map(([k, v]) => [k, fn(v)]));

/** Serialise for download, in the same shape and key order `chorus` writes. */
export function toJson(config) {
  const step = (s) => ordered(s, ORDER.step);
  const doc = ordered({
    ...config,
    devices: mapValues(config.devices, (d) => ordered({ ...d, functions: mapValues(d.functions, (f) => ordered(f, ORDER.function)) }, ORDER.device)),
    activities: mapValues(config.activities, (a) => ordered({ ...a, start_sequence: a.start_sequence.map(step), stop_sequence: a.stop_sequence.map(step) }, ORDER.activity)),
  }, ORDER.config);
  return JSON.stringify(doc, null, 2) + '\n';
}

/**
 * Accept a chorus config (or a setup exported by the earlier web app) and return a
 * complete chorus config with defaults filled in. Unknown fields are preserved.
 */
export function normalize(input) {
  if (!input || typeof input !== 'object' || Array.isArray(input)) throw new Error('Not a configuration file');
  if (Array.isArray(input.devices)) return fromLegacy(input);
  const version = input.schema_version ?? SCHEMA_VERSION;
  if (version > SCHEMA_VERSION) {
    throw new Error(`This file uses config version ${version}; this app understands up to ${SCHEMA_VERSION}.`);
  }
  const c = { ...blankConfig(), ...input, schema_version: version };
  c.devices = {};
  for (const [key, raw] of Object.entries(input.devices ?? {})) {
    const d = normalizeDevice({ ...raw, name: raw?.name || key });
    c.devices[d.name] = d;
  }
  c.activities = {};
  for (const [key, raw] of Object.entries(input.activities ?? {})) {
    const a = normalizeActivity({ ...raw, name: raw?.name || key });
    c.activities[a.name] = a;
  }
  c.global_buttons = { ...(input.global_buttons ?? {}) };
  return c;
}

function normalizeDevice(raw) {
  const d = {
    manufacturer: '', model: '', power_on_delay_ms: 2000, inter_command_delay_ms: 100,
    repeat_count: 1, notes: '', ...raw,
    type: DEVICE_TYPES.some(([v]) => v === raw.type) ? raw.type : 'other',
    power_style: POWER_STYLES.some(([v]) => v === raw.power_style) ? raw.power_style : 'toggle',
    inputs: [...(raw.inputs ?? [])],
    functions: {},
  };
  for (const [key, f] of Object.entries(raw.functions ?? {})) {
    const fn = normalizeFunction({ ...f, name: f?.name || key });
    d.functions[fn.name] = fn;
  }
  return d;
}

const normalizeFunction = (raw) => ({ label: '', frequency: 38000, durations: [], protocol: '', source: '', ...raw });

function normalizeActivity(raw) {
  const step = (s) => ({ delay_ms: 500, repeat: 1, ...s });
  return {
    label: '', icon: '', volume_device: '', channel_device: '', primary_device: '', ...raw,
    buttons: { ...(raw.buttons ?? {}) },
    start_sequence: (raw.start_sequence ?? []).map(step),
    stop_sequence: (raw.stop_sequence ?? []).map(step),
  };
}

// The earlier web app kept arrays of devices and activities with random ids.
const LEGACY_TYPES = {
  'TV': 'television', 'Receiver / Soundbar': 'av_receiver', 'Streaming player': 'streaming',
  'Cable / Satellite box': 'cable_satellite', 'Game console': 'game_console',
  'Blu-ray / DVD': 'bluray_dvd', 'Projector': 'projector', 'Lights': 'lighting', 'Other': 'other',
};
const LEGACY_BUTTONS = {
  power: 'PowerToggle', menu: 'Menu', guide: 'Guide', back: 'Back', up: 'DirectionUp', left: 'DirectionLeft',
  ok: 'OK', right: 'DirectionRight', down: 'DirectionDown', volUp: 'VolumeUp', volDown: 'VolumeDown',
  mute: 'Mute', chUp: 'ChannelUp', chDown: 'ChannelDown', rew: 'Rewind', play: 'Play', pause: 'Pause',
  ff: 'FastForward', stop: 'Stop', rec: 'Record',
};

function fromLegacy(old) {
  const c = blankConfig();
  const nameOf = {};
  for (const d of old.devices) {
    const name = uniqueName(c.devices, d.name || 'Device');
    nameOf[d.id] = name;
    const cmds = Array.isArray(d.commands) ? d.commands : [];
    c.devices[name] = normalizeDevice({
      name, manufacturer: d.manufacturer || '', model: d.model || '',
      type: LEGACY_TYPES[d.type] ?? 'other',
      power_style: cmds.includes('PowerOn') && cmds.includes('PowerOff') ? 'discrete' : 'toggle',
      inputs: cmds.filter((x) => /^input/i.test(x)),
      functions: Object.fromEntries(cmds.map((x) => [x, { name: x }])),
    });
  }
  for (const a of old.activities ?? []) {
    const devices = (a.devices ?? []).filter((x) => nameOf[x.deviceId])
      .map((x) => ({ device: nameOf[x.deviceId], input: x.input || '' }));
    const playback = nameOf[a.roles?.playback] ?? '';
    const act = normalizeActivity({
      name: activityName(c.activities, a.name || 'Activity'), label: a.name || 'Activity',
      volume_device: nameOf[a.roles?.volume] ?? '', channel_device: playback, primary_device: playback,
      ...buildSequences(c, devices),
    });
    for (const [k, m] of Object.entries(a.buttons ?? {})) {
      if (LEGACY_BUTTONS[k] && nameOf[m.deviceId]) act.buttons[LEGACY_BUTTONS[k]] = `${nameOf[m.deviceId]}/${m.command}`;
    }
    c.activities[act.name] = act;
  }
  return c;
}

// ---------- Editing helpers ----------

export function uniqueName(map, wanted, except) {
  const base = wanted.trim() || 'Device';
  let name = base;
  for (let i = 2; name in map && name !== except; i++) name = `${base} ${i}`;
  return name;
}

/** Activity keys follow chorus's style: "Watch TV" → "WatchTV". */
export function activityName(activities, label, except) {
  const base = label.replace(/[^A-Za-z0-9]+(.)?/g, (_, ch) => (ch ? ch.toUpperCase() : ''))
    .replace(/^./, (ch) => ch.toUpperCase()) || 'Activity';
  let name = base;
  for (let i = 2; name in activities && name !== except; i++) name = `${base}${i}`;
  return name;
}

export const newDevice = (name, type) => normalizeDevice({ name, type,
  power_style: (DEFAULT_FUNCTIONS[type] ?? []).includes('PowerOn') ? 'discrete' : 'toggle',
  power_on_delay_ms: ['television', 'projector'].includes(type) ? 4000 : 2000 });

export const newActivity = (name, label) => normalizeActivity({ name, label });

const ROLES = ['volume_device', 'channel_device', 'primary_device'];

/** Store a device edit, renaming references across the config when its name changed. */
export function putDevice(config, oldName, device) {
  if (oldName && oldName !== device.name) {
    // Rebuild the map so the renamed device keeps its place in the file.
    config.devices = Object.fromEntries(Object.entries(config.devices)
      .map(([k, v]) => (k === oldName ? [device.name, device] : [k, v])));
    const fix = (t) => (t?.startsWith(`${oldName}/`) ? device.name + t.slice(oldName.length) : t);
    for (const a of Object.values(config.activities)) {
      for (const s of [...a.start_sequence, ...a.stop_sequence]) if (s.device === oldName) s.device = device.name;
      for (const k of Object.keys(a.buttons)) a.buttons[k] = fix(a.buttons[k]);
      for (const role of ROLES) if (a[role] === oldName) a[role] = device.name;
    }
    for (const k of Object.keys(config.global_buttons)) config.global_buttons[k] = fix(config.global_buttons[k]);
  }
  config.devices[device.name] = device;
}

/** Remove a device and everything that points at it. */
export function deleteDevice(config, name) {
  delete config.devices[name];
  const pointsHere = (t) => t?.startsWith(`${name}/`);
  for (const a of Object.values(config.activities)) {
    a.start_sequence = a.start_sequence.filter((s) => s.device !== name);
    a.stop_sequence = a.stop_sequence.filter((s) => s.device !== name);
    for (const k of Object.keys(a.buttons)) if (pointsHere(a.buttons[k])) delete a.buttons[k];
    for (const role of ROLES) if (a[role] === name) a[role] = '';
  }
  for (const k of Object.keys(config.global_buttons)) if (pointsHere(config.global_buttons[k])) delete config.global_buttons[k];
}

/** Keep existing commands (and their IR codes) whose names survive; add empty ones for new names. */
export function setFunctionNames(device, names) {
  const next = {};
  for (const n of names) next[n] = device.functions[n] ?? normalizeFunction({ name: n });
  device.functions = next;
  const kept = device.inputs.filter((i) => i in next);
  device.inputs = [...kept, ...names.filter((n) => /^input/i.test(n) && !kept.includes(n))];
}

export function powerOnFunction(device) {
  const has = (n) => n in device.functions;
  if (device.power_style === 'none') return null;
  if (device.power_style === 'discrete') return has('PowerOn') ? 'PowerOn' : null;
  return ['PowerToggle', 'Power', 'PowerOn'].find(has) ?? null;
}

export function powerOffFunction(device) {
  const has = (n) => n in device.functions;
  if (device.power_style === 'none') return null;
  if (device.power_style === 'discrete') return has('PowerOff') ? 'PowerOff' : null;
  return ['PowerToggle', 'Power', 'PowerOff'].find(has) ?? null;
}

/** Which devices an activity uses, and the input each is set to, read from its start sequence. */
export function activityDevices(config, activity) {
  const out = [];
  for (const s of activity.start_sequence) {
    const d = config.devices[s.device];
    if (!d) continue;
    let entry = out.find((x) => x.device === s.device);
    if (!entry) { entry = { device: s.device, input: '' }; out.push(entry); }
    if (d.inputs.includes(s.function) || /^input/i.test(s.function)) entry.input = s.function;
  }
  return out;
}

/**
 * Start: power on every device (each followed by its warm-up delay), then select inputs.
 * Stop: power off in reverse order.
 */
export function buildSequences(config, devices) {
  const start = [];
  const stop = [];
  for (const { device } of devices) {
    const d = config.devices[device];
    const on = d && powerOnFunction(d);
    if (on) start.push({ device, function: on, delay_ms: d.power_on_delay_ms, repeat: 1 });
  }
  for (const { device, input } of devices) {
    if (input && config.devices[device]) start.push({ device, function: input, delay_ms: 500, repeat: 1 });
  }
  for (const { device } of [...devices].reverse()) {
    const d = config.devices[device];
    const off = d && powerOffFunction(d);
    if (off) stop.push({ device, function: off, delay_ms: 500, repeat: 1 });
  }
  return { start_sequence: start, stop_sequence: stop };
}

const ROLE_BUTTONS = {
  volume_device: ['VolumeUp', 'VolumeDown', 'Mute'],
  channel_device: ['ChannelUp', 'ChannelDown', 'PrevChannel', ...DIGITS],
  primary_device: [...NAV, 'Guide', 'Info', 'Exit', ...TRANSPORT, 'Record', 'SkipBack', 'SkipForward'],
};

/** Fill unmapped buttons from the activity's volume / channel / primary devices. */
export function suggestButtons(config, activity) {
  const buttons = { ...activity.buttons };
  for (const [role, names] of Object.entries(ROLE_BUTTONS)) {
    const d = config.devices[activity[role]];
    if (!d) continue;
    for (const button of names) {
      if (buttons[button]) continue;
      const candidates = button === 'OK' ? ['OK', 'Select', 'Enter'] : [button];
      const fn = candidates.find((n) => n in d.functions);
      if (fn) buttons[button] = `${d.name}/${fn}`;
    }
  }
  return buttons;
}

/** The same checks as `chorus config validate`, so problems show up here first. */
export function validate(config) {
  const warnings = [];
  for (const d of Object.values(config.devices)) {
    const fns = Object.keys(d.functions);
    if (!fns.length) warnings.push(`Device “${d.name}” has no commands.`);
    if (d.power_style === 'discrete' && !(fns.includes('PowerOn') && fns.includes('PowerOff'))) {
      warnings.push(`Device “${d.name}” is set to separate power buttons but is missing PowerOn and/or PowerOff.`);
    }
    if (d.power_style === 'toggle' && ['television', 'av_receiver'].includes(d.type)) {
      warnings.push(`Device “${d.name}” uses a single power button, so activities can leave it in the wrong state.`);
    }
    for (const i of d.inputs) if (!fns.includes(i)) warnings.push(`Device “${d.name}” lists input “${i}”, which isn't one of its commands.`);
  }
  for (const a of Object.values(config.activities)) {
    const label = a.label || a.name;
    const check = (device, fn, where) => {
      const d = config.devices[device];
      if (!d) warnings.push(`Activity “${label}”: ${where} uses unknown device “${device}”.`);
      else if (!(fn in d.functions)) warnings.push(`Activity “${label}”: ${where} uses “${device}/${fn}”, which doesn't exist.`);
    };
    a.start_sequence.forEach((s, i) => check(s.device, s.function, `start step ${i + 1}`));
    a.stop_sequence.forEach((s, i) => check(s.device, s.function, `stop step ${i + 1}`));
    for (const [button, target] of Object.entries(a.buttons)) {
      const slash = target.indexOf('/');
      if (slash < 0) warnings.push(`Activity “${label}”: button ${button} isn't in Device/Command form.`);
      else check(target.slice(0, slash), target.slice(slash + 1), `button ${button}`);
    }
    if (!a.start_sequence.length) warnings.push(`Activity “${label}” has no start-up steps, so it won't turn anything on.`);
  }
  if (!Object.keys(config.activities).length) warnings.push('There are no activities yet.');
  return warnings;
}

/** How many commands have real IR codes (learned or imported) versus a name only. */
export function irCoverage(config) {
  let withCode = 0;
  let total = 0;
  for (const d of Object.values(config.devices)) {
    for (const f of Object.values(d.functions)) {
      total++;
      if (f.durations?.length) withCode++;
    }
  }
  return { withCode, total };
}
