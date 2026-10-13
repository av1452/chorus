import { test } from 'node:test';
import assert from 'node:assert/strict';
import { Cmd, Sequence, encodeCommand, isReplyTo, param, parseDataPacket, parseOpenReply,
  parseSystemInfo } from '../src/protocol.js';
import { normalize, startSequence, suggestButtons } from '../src/store.js';
import { lookupRemote } from '../src/models.js';

test('ping is header-only and zero-padded to the report width', () => {
  const p = encodeCommand(Cmd.PING, [], 0, 16);
  assert.deepEqual([...p], [0xff, 0x00, 0x00, 0x00, ...Array(12).fill(0)]);
});

test('open encodes two null-terminated string parameters', () => {
  const p = encodeCommand(Cmd.OPEN, [param.string('/a'), param.string('R')], 5, 16);
  assert.deepEqual([...p.subarray(0, 12)], [0xff, 0x01, 0x05, 0x02, 0x80, 0x2f, 0x61, 0x00, 0x80, 0x52, 0x00, 0x00]);
});

test('byte, word and sized parameters carry their length', () => {
  assert.deepEqual(param.byte(0x1ff), [0x01, 0xff]);
  assert.deepEqual(param.word(0x1234), [0x02, 0x12, 0x34]);
  assert.deepEqual(param.bytes([9, 8, 7]), [0x83, 9, 8, 7]);
  assert.throws(() => param.bytes(new Array(128).fill(0)), RangeError);
});

test('oversized packets are rejected', () => {
  assert.throws(() => encodeCommand(Cmd.OPEN, [param.string('/sys/sysinfo')], 0, 8), /overflow/);
  assert.throws(() => encodeCommand(Cmd.PING, [], 0, 0), /width/);
});

test('sequence starts at 0 and wraps after 63', () => {
  const s = new Sequence();
  const seen = Array.from({ length: 66 }, () => s.next());
  assert.equal(seen[0], 0);
  assert.equal(seen[63], 63);
  assert.equal(seen[64], 0);
});

test('reply checks and open reply fields', () => {
  const reply = Uint8Array.from([0xff, 0x01, 0x00, 0x00, 0x00, 0x07, 0x00, 0x00, 0x00, 0x01, 0x2c]);
  assert.ok(isReplyTo(reply, Cmd.OPEN));
  assert.ok(!isReplyTo(reply, Cmd.READ));
  assert.ok(!isReplyTo(Uint8Array.from([0xff, 0x01, 0xff]), Cmd.OPEN));
  assert.deepEqual(parseOpenReply(reply), { handle: 7, size: 300 });
});

test('data packets are [sequence, length, payload]', () => {
  const { sequence, payload } = parseDataPacket(Uint8Array.from([3, 2, 0x41, 0x42, 0x43]));
  assert.equal(sequence, 3);
  assert.deepEqual([...payload], [0x41, 0x42]);
});

test('system info is cut at NUL and split into key/value lines', () => {
  const bytes = new TextEncoder().encode('arch 18\nskin 100\nfw_ver 4.1.3\nserial_number ABC 123\n\0garbage');
  assert.deepEqual(parseSystemInfo(bytes), { arch: '18', skin: '100', fw_ver: '4.1.3', serial_number: 'ABC 123' });
});

test('known remotes are looked up by USB ids', () => {
  assert.equal(lookupRemote(0x046d, 0xc12b).protocol, 'packet');
  assert.equal(lookupRemote(0x046d, 0xc111).protocol, 'legacy');
  assert.equal(lookupRemote(0x1234, 0x5678), null);
});

test('activities derive start steps and button suggestions from devices', () => {
  const config = normalize({
    devices: [
      { id: 'tv', name: 'TV', commands: ['PowerOn', 'InputHdmi2', 'VolumeUp'] },
      { id: 'box', name: 'Box', commands: ['PowerToggle', 'ChannelUp', 'Select'] },
    ],
    activities: [{ id: 'a', name: 'Watch', devices: [{ deviceId: 'tv', input: 'InputHdmi2' }, { deviceId: 'box' }], roles: { volume: 'tv', playback: 'box' } }],
  });
  const [a] = config.activities;
  assert.deepEqual(startSequence(a, config.devices), [
    { device: 'TV', command: 'PowerOn' }, { device: 'Box', command: 'PowerToggle' }, { device: 'TV', command: 'InputHdmi2' },
  ]);
  const b = suggestButtons(a, config.devices);
  assert.deepEqual(b.volUp, { deviceId: 'tv', command: 'VolumeUp' });
  assert.deepEqual(b.chUp, { deviceId: 'box', command: 'ChannelUp' });
  assert.deepEqual(b.ok, { deviceId: 'box', command: 'Select' });
  assert.equal(b.mute, undefined);
});

test('normalize rejects junk and fills missing lists', () => {
  assert.throws(() => normalize(null));
  assert.deepEqual(normalize({}).devices, []);
});
