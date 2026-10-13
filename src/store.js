// Local configuration: devices, activities and button mappings. Everything stays in the browser.

const KEY = 'chorus.config.v1';

export const DEVICE_TYPES = ['TV', 'Receiver / Soundbar', 'Streaming player', 'Cable / Satellite box',
  'Game console', 'Blu-ray / DVD', 'Projector', 'Lights', 'Other'];

export const DEFAULT_COMMANDS = {
  'TV': ['PowerOn', 'PowerOff', 'InputHdmi1', 'InputHdmi2', 'InputHdmi3', 'VolumeUp', 'VolumeDown', 'Mute', 'Menu'],
  'Receiver / Soundbar': ['PowerOn', 'PowerOff', 'VolumeUp', 'VolumeDown', 'Mute', 'InputHdmi1', 'InputHdmi2'],
  'Streaming player': ['PowerToggle', 'Home', 'Back', 'DirectionUp', 'DirectionDown', 'DirectionLeft', 'DirectionRight', 'Select', 'Play', 'Pause', 'Rewind', 'FastForward'],
  'Cable / Satellite box': ['PowerToggle', 'Guide', 'ChannelUp', 'ChannelDown', 'Select', 'Back', 'Record', 'Number0', 'Number1', 'Number2', 'Number3', 'Number4', 'Number5', 'Number6', 'Number7', 'Number8', 'Number9'],
};

export const BUTTONS = [
  ['power', 'Power'], ['menu', 'Menu'], ['guide', 'Guide'], ['back', 'Back'],
  ['up', 'Up'], ['left', 'Left'], ['ok', 'OK'], ['right', 'Right'], ['down', 'Down'],
  ['volUp', 'Vol +'], ['volDown', 'Vol −'], ['mute', 'Mute'], ['chUp', 'Ch +'], ['chDown', 'Ch −'],
  ['rew', 'Rewind'], ['play', 'Play'], ['pause', 'Pause'], ['ff', 'Fast fwd'], ['stop', 'Stop'], ['rec', 'Record'],
];

const blank = () => ({ version: 1, devices: [], activities: [], remotes: [] });

export const uid = () => Math.random().toString(36).slice(2, 10);

export function load() {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? normalize(JSON.parse(raw)) : blank();
  } catch {
    return blank();
  }
}

export function save(config) {
  try { localStorage.setItem(KEY, JSON.stringify(config)); } catch { /* storage unavailable */ }
}

export function normalize(input) {
  if (!input || typeof input !== 'object') throw new Error('Not a Chorus configuration');
  const c = { ...blank(), ...input };
  for (const k of ['devices', 'activities', 'remotes']) if (!Array.isArray(c[k])) c[k] = [];
  c.devices = c.devices.map((d) => ({ inputs: [], commands: [], ...d }));
  c.activities = c.activities.map((a) => ({ devices: [], roles: {}, buttons: {}, ...a }));
  return c;
}

/** Fill unmapped buttons from the activity's volume / channel / playback devices. */
export function suggestButtons(activity, devices) {
  const byId = Object.fromEntries(devices.map((d) => [d.id, d]));
  const pick = (deviceId, names) => {
    const d = byId[deviceId];
    const cmd = d && names.find((n) => d.commands.includes(n));
    return cmd ? { deviceId, command: cmd } : null;
  };
  const { volume, playback } = activity.roles;
  const rules = {
    volUp: [volume, ['VolumeUp']], volDown: [volume, ['VolumeDown']], mute: [volume, ['Mute']],
    chUp: [playback, ['ChannelUp']], chDown: [playback, ['ChannelDown']],
    up: [playback, ['DirectionUp']], down: [playback, ['DirectionDown']], left: [playback, ['DirectionLeft']],
    right: [playback, ['DirectionRight']], ok: [playback, ['Select', 'OK']], menu: [playback, ['Menu', 'Home']],
    guide: [playback, ['Guide']], back: [playback, ['Back']], play: [playback, ['Play']],
    pause: [playback, ['Pause']], rew: [playback, ['Rewind']], ff: [playback, ['FastForward']],
    stop: [playback, ['Stop']], rec: [playback, ['Record']],
  };
  const buttons = { ...activity.buttons };
  for (const [btn, [dev, names]] of Object.entries(rules)) {
    if (!buttons[btn]) {
      const m = pick(dev, names);
      if (m) buttons[btn] = m;
    }
  }
  return buttons;
}

/** Power-on sequence for an activity: power on each device, then set inputs. */
export function startSequence(activity, devices) {
  const byId = Object.fromEntries(devices.map((d) => [d.id, d]));
  const steps = [];
  for (const { deviceId } of activity.devices) {
    const d = byId[deviceId];
    if (!d) continue;
    const on = ['PowerOn', 'PowerToggle'].find((c) => d.commands.includes(c));
    if (on) steps.push({ device: d.name, command: on });
  }
  for (const { deviceId, input } of activity.devices) {
    const d = byId[deviceId];
    if (d && input) steps.push({ device: d.name, command: input });
  }
  return steps;
}
