// Wire format for the HID command protocol used by USB universal remotes.
// See docs/PROTOCOL.md for how each rule was derived and how sure we are of it.

export const SERVICE_ID = 0xff;
export const ERROR_MARKER = 0xff;
export const END_MARKER = 0xfe;
export const MAX_SEQUENCE = 63;

export const Cmd = Object.freeze({
  PING: 0x00,
  OPEN: 0x01,
  READ: 0x04,
  CLOSE: 0x07,
  RESET: 0xff,
});

const utf8 = new TextEncoder();

/** Parameter helpers. Each returns the encoded bytes, including the length prefix. */
export const param = {
  byte: (v) => [0x01, v & 0xff],
  word: (v) => [0x02, (v >> 8) & 0xff, v & 0xff],
  dword: (v) => [0x04, (v >>> 24) & 0xff, (v >> 16) & 0xff, (v >> 8) & 0xff, v & 0xff],
  // Null-terminated strings use the 0x80 marker with no length.
  string: (s) => [0x80, ...utf8.encode(s), 0x00],
  // Sized blobs set the high bit and carry their length in the low bits.
  bytes: (arr) => {
    if (arr.length > 0x7f) throw new RangeError('sized parameter longer than 127 bytes');
    return [0x80 | arr.length, ...arr];
  },
};

/** Rolling sequence counter: first value is 0, wraps after 63. */
export class Sequence {
  constructor() { this.value = 0xff; }
  next() {
    this.value = this.value >= MAX_SEQUENCE ? 0 : this.value + 1;
    return this.value;
  }
}

/**
 * Build one command report.
 * @param {number} cmd command id
 * @param {number[][]} params encoded parameters (from `param.*`)
 * @param {number} seq sequence number
 * @param {number} width report length in bytes; the packet is zero-padded to it
 */
export function encodeCommand(cmd, params, seq, width) {
  if (!(width > 0)) throw new RangeError('invalid packet width');
  const body = [SERVICE_ID, cmd & 0xff, seq & 0xff, params.length, ...params.flat()];
  if (body.length > width) throw new RangeError(`packet size overflow (${body.length} > ${width})`);
  const out = new Uint8Array(width);
  out.set(body);
  return out;
}

/** True when `report` is a successful reply to `cmd`. */
export function isReplyTo(report, cmd) {
  return report[0] === SERVICE_ID && report[1] === cmd && report[2] !== ERROR_MARKER;
}

/** Fields carried by the reply to OPEN. */
export function parseOpenReply(report) {
  const handle = report[5];
  const size = ((report[7] << 24) | (report[8] << 16) | (report[9] << 8) | report[10]) >>> 0;
  return { handle, size };
}

/** Data packets returned by READ: [sequence, length, ...payload]. */
export function parseDataPacket(report) {
  const length = Math.min(report[1], report.length - 2);
  return { sequence: report[0], payload: report.subarray(2, 2 + length) };
}

/**
 * Parse the remote's system-information file: text up to the first NUL,
 * one "key value" pair per line.
 */
export function parseSystemInfo(bytes) {
  let text = new TextDecoder().decode(bytes);
  const nul = text.indexOf('\0');
  if (nul >= 0) text = text.slice(0, nul);
  const props = {};
  for (const raw of text.split('\n')) {
    const line = raw.trim();
    if (!line) continue;
    const sp = line.indexOf(' ');
    if (sp < 0) props[line] = '';
    else props[line.slice(0, sp)] = line.slice(sp + 1).trim();
  }
  return props;
}

export const toHex = (bytes) => Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join(' ');
