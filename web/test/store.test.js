import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, writeFileSync } from 'node:fs';
import { blankConfig, normalize, toJson, newDevice, newActivity, putDevice, deleteDevice,
  setFunctionNames, activityName, activityDevices, buildSequences, suggestButtons, validate,
  irCoverage } from '../src/store.js';

const pythonExample = new URL('../../examples/living-room.json', import.meta.url);
const webFixture = new URL('./fixtures/web-export.json', import.meta.url);

/** A small setup built the way the web app's forms build it. */
function buildSample() {
  const c = blankConfig('Den');
  c.created = c.modified = '2026-10-13T00:00:00+00:00';
  const tv = newDevice('TV', 'television');
  setFunctionNames(tv, ['PowerOn', 'PowerOff', 'InputHDMI1', 'InputHDMI2', 'VolumeUp', 'VolumeDown', 'Mute']);
  putDevice(c, null, tv);
  const box = newDevice('Streamer', 'streaming');
  setFunctionNames(box, ['PowerToggle', 'DirectionUp', 'DirectionDown', 'Select', 'Play', 'Pause']);
  putDevice(c, null, box);
  const a = newActivity(activityName(c.activities, 'Watch a movie'), 'Watch a movie');
  Object.assign(a, { volume_device: 'TV', primary_device: 'Streamer' },
    buildSequences(c, [{ device: 'TV', input: 'InputHDMI2' }, { device: 'Streamer', input: '' }]));
  a.buttons = suggestButtons(c, a);
  c.activities[a.name] = a;
  return c;
}

test('the Python tool’s example config opens unchanged', () => {
  const original = JSON.parse(readFileSync(pythonExample, 'utf8'));
  assert.deepEqual(normalize(original), original);
});

test('saved files use the same key order as the Python tool', () => {
  const original = JSON.parse(readFileSync(pythonExample, 'utf8'));
  // Compact JSON text only matches when both the data and the key order match.
  assert.equal(JSON.stringify(JSON.parse(toJson(normalize(original)))), JSON.stringify(original));
});

test('a setup built here matches the fixture the Python tests load', () => {
  const json = toJson(buildSample());
  if (process.env.UPDATE_FIXTURES) writeFileSync(webFixture, json);
  assert.equal(json, readFileSync(webFixture, 'utf8'));
});

test('activity names follow the Python style', () => {
  assert.equal(activityName({}, 'Watch a movie'), 'WatchAMovie');
  assert.equal(activityName({ WatchTV: {} }, 'Watch TV'), 'WatchTV2');
  assert.equal(activityName({ WatchTV: {} }, 'Watch TV', 'WatchTV'), 'WatchTV');
});

test('sequences power on, then set inputs, and power off in reverse', () => {
  const c = buildSample();
  const a = c.activities.WatchAMovie;
  assert.deepEqual(a.start_sequence.map((s) => `${s.device}/${s.function}`),
    ['TV/PowerOn', 'Streamer/PowerToggle', 'TV/InputHDMI2']);
  assert.equal(a.start_sequence[0].delay_ms, 4000);
  assert.deepEqual(a.stop_sequence.map((s) => `${s.device}/${s.function}`), ['Streamer/PowerToggle', 'TV/PowerOff']);
  assert.deepEqual(activityDevices(c, a), [{ device: 'TV', input: 'InputHDMI2' }, { device: 'Streamer', input: '' }]);
});

test('devices set to leave power alone are not switched', () => {
  const c = buildSample();
  c.devices.Streamer.power_style = 'none';
  const { start_sequence, stop_sequence } = buildSequences(c, [{ device: 'Streamer', input: '' }]);
  assert.deepEqual(start_sequence, []);
  assert.deepEqual(stop_sequence, []);
});

test('suggested buttons use the volume and primary devices', () => {
  const b = buildSample().activities.WatchAMovie.buttons;
  assert.equal(b.VolumeUp, 'TV/VolumeUp');
  assert.equal(b.OK, 'Streamer/Select');
  assert.equal(b.Play, 'Streamer/Play');
  assert.equal(b.ChannelUp, undefined);
});

test('renaming a device updates every reference', () => {
  const c = buildSample();
  const tv = structuredClone(c.devices.TV);
  tv.name = 'Lounge TV';
  putDevice(c, 'TV', tv);
  const a = c.activities.WatchAMovie;
  assert.deepEqual(Object.keys(c.devices), ['Lounge TV', 'Streamer']);
  assert.equal(a.volume_device, 'Lounge TV');
  assert.equal(a.buttons.VolumeUp, 'Lounge TV/VolumeUp');
  assert.ok(a.start_sequence.every((s) => s.device !== 'TV'));
  assert.deepEqual(validate(c), []);
});

test('deleting a device removes everything that points at it', () => {
  const c = buildSample();
  deleteDevice(c, 'Streamer');
  const a = c.activities.WatchAMovie;
  assert.equal(a.primary_device, '');
  assert.ok(!Object.values(a.buttons).some((t) => t.startsWith('Streamer/')));
  assert.deepEqual(validate(c), []);
});

test('changing command names keeps existing IR codes', () => {
  const d = newDevice('TV', 'television');
  setFunctionNames(d, ['PowerOn', 'InputHDMI1']);
  d.functions.PowerOn.durations = [9000, 4500, 560];
  setFunctionNames(d, ['PowerOn', 'PowerOff', 'InputHDMI1', 'InputHDMI2']);
  assert.deepEqual(d.functions.PowerOn.durations, [9000, 4500, 560]);
  assert.deepEqual(d.inputs, ['InputHDMI1', 'InputHDMI2']);
});

test('validation catches the same problems as the Python tool', () => {
  const c = buildSample();
  assert.deepEqual(validate(c), []);
  c.devices.TV.power_style = 'toggle';
  c.activities.WatchAMovie.buttons.Mute = 'TV/Nope';
  const w = validate(c).join('\n');
  assert.match(w, /single power button/);
  assert.match(w, /TV\/Nope/);
});

test('IR coverage counts commands with real codes', () => {
  const c = normalize(JSON.parse(readFileSync(pythonExample, 'utf8')));
  const { withCode, total } = irCoverage(c);
  assert.ok(total > 0 && withCode > 0 && withCode <= total);
});

test('setups saved by the earlier web app are converted', () => {
  const old = {
    version: 1,
    devices: [
      { id: 'a1', name: 'TV', type: 'TV', commands: ['PowerOn', 'PowerOff', 'InputHdmi1', 'VolumeUp'] },
      { id: 'b2', name: 'Box', type: 'Cable / Satellite box', commands: ['PowerToggle', 'ChannelUp'] },
    ],
    activities: [{ id: 'x', name: 'Watch TV', devices: [{ deviceId: 'a1', input: 'InputHdmi1' }, { deviceId: 'b2', input: '' }],
      roles: { volume: 'a1', playback: 'b2' }, buttons: { volUp: { deviceId: 'a1', command: 'VolumeUp' }, chUp: { deviceId: 'b2', command: 'ChannelUp' } } }],
    remotes: [],
  };
  const c = normalize(old);
  assert.equal(c.devices.TV.type, 'television');
  assert.equal(c.devices.TV.power_style, 'discrete');
  assert.equal(c.devices.Box.power_style, 'toggle');
  const a = c.activities.WatchTV;
  assert.equal(a.label, 'Watch TV');
  assert.deepEqual(a.buttons, { VolumeUp: 'TV/VolumeUp', ChannelUp: 'Box/ChannelUp' });
  assert.deepEqual(validate(c), []);
});

test('files from a newer schema are refused', () => {
  assert.throws(() => normalize({ schema_version: 99 }), /version 99/);
  assert.throws(() => normalize(null));
  assert.throws(() => normalize([]));
});
