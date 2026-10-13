// WebHID transport plus the "identify remote" operation.
import { Cmd, Sequence, encodeCommand, isReplyTo, parseOpenReply, parseDataPacket,
  parseSystemInfo, param, toHex, END_MARKER, SERVICE_ID } from './protocol.js';
import { hidFilters, lookupRemote } from './models.js';

const PACKETS_PER_READ = 6;
const SYSINFO_PATH = '/sys/sysinfo';

export const webHidSupported = () => typeof navigator !== 'undefined' && 'hid' in navigator;

function reportBytes(report) {
  return (report.items ?? []).reduce((n, it) => n + (it.reportSize * it.reportCount) / 8, 0);
}

export class RemoteConnection {
  constructor(device, log = () => {}) {
    this.device = device;
    this.log = log;
    this.seq = new Sequence();
    this.queue = [];
    this.waiters = [];
    this.onReport = (e) => {
      const data = new Uint8Array(e.data.buffer, e.data.byteOffset, e.data.byteLength);
      this.log('in', data);
      const w = this.waiters.shift();
      if (w) w(data); else this.queue.push(data);
    };
  }

  static async request(log) {
    const [device] = await navigator.hid.requestDevice({ filters: hidFilters() });
    if (!device) return null;
    const conn = new RemoteConnection(device, log);
    await conn.open();
    return conn;
  }

  get info() {
    return lookupRemote(this.device.vendorId, this.device.productId);
  }

  async open() {
    if (!this.device.opened) await this.device.open();
    const out = this.device.collections.flatMap((c) => c.outputReports ?? [])[0];
    const inp = this.device.collections.flatMap((c) => c.inputReports ?? [])[0];
    this.reportId = out?.reportId ?? 0;
    this.width = reportBytes(out ?? {}) || 64;
    this.inWidth = reportBytes(inp ?? {}) || this.width;
    this.device.addEventListener('inputreport', this.onReport);
  }

  async close() {
    this.device.removeEventListener('inputreport', this.onReport);
    if (this.device.opened) await this.device.close();
  }

  receive(timeoutMs) {
    if (this.queue.length) return Promise.resolve(this.queue.shift());
    return new Promise((resolve, reject) => {
      const t = setTimeout(() => {
        this.waiters.splice(this.waiters.indexOf(done), 1);
        reject(new Error('Timed out waiting for the remote'));
      }, timeoutMs);
      const done = (d) => { clearTimeout(t); resolve(d); };
      this.waiters.push(done);
    });
  }

  async command(cmd, params = [], { timeout = 10000, expectReply = true } = {}) {
    const packet = encodeCommand(cmd, params, this.seq.next(), this.width);
    this.log('out', packet);
    await this.device.sendReport(this.reportId, packet);
    if (!expectReply) return null;
    const reply = await this.receive(timeout);
    if (!isReplyTo(reply, cmd)) {
      throw new Error(`Unexpected reply to command 0x${cmd.toString(16)}: ${toHex(reply.subarray(0, 8))}`);
    }
    return reply;
  }

  async readFile(path, onProgress = () => {}) {
    const open = parseOpenReply(await this.command(Cmd.OPEN, [param.string(path), param.string('R')], { timeout: 25000 }));
    const chunks = [];
    let received = 0;
    try {
      while (received < open.size) {
        await this.command(Cmd.READ, [param.byte(open.handle), param.byte(PACKETS_PER_READ)], { timeout: 25000 });
        for (let i = 0; i < PACKETS_PER_READ && received < open.size; i++) {
          const pkt = await this.receive(25000);
          if (pkt[0] === END_MARKER || pkt[0] === SERVICE_ID) break;
          const { payload } = parseDataPacket(pkt);
          if (!payload.length) break;
          chunks.push(payload.slice(0, open.size - received));
          received += payload.length;
          onProgress(Math.min(received, open.size), open.size);
        }
      }
    } finally {
      await this.command(Cmd.CLOSE, [param.byte(open.handle)], { timeout: 25000 }).catch(() => {});
    }
    const out = new Uint8Array(chunks.reduce((n, c) => n + c.length, 0));
    let o = 0;
    for (const c of chunks) { out.set(c, o); o += c.length; }
    return out;
  }

  /** Ping the remote, then read and parse its system-information file. */
  async identify(onProgress) {
    await this.command(Cmd.PING);
    const bytes = await this.readFile(SYSINFO_PATH, onProgress);
    return parseSystemInfo(bytes);
  }
}
