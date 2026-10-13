// USB identities of universal remotes and hubs, and whether Chorus can talk to them.
// `protocol: 'packet'` means the remote speaks the file-based packet protocol Chorus implements.
// Older remotes use a different, per-model protocol that Chorus does not support yet.

const LOGI = 0x046d;
const LEGACY = 0x0400;

export const REMOTES = [
  { vid: LEGACY, pid: 0xc359, name: 'Legacy 6xx/7xx series', protocol: 'legacy' },
  { vid: LOGI, pid: 0xc110, name: '720 / 785 / 880 / 885 series', protocol: 'legacy' },
  { vid: LOGI, pid: 0xc111, name: '360 / 5xx / 610 series', protocol: 'legacy' },
  { vid: LOGI, pid: 0xc112, name: '890 / 895 series', protocol: 'legacy' },
  { vid: LOGI, pid: 0xc114, name: '891 / 896 series', protocol: 'legacy' },
  { vid: LOGI, pid: 0xc11e, name: '882', protocol: 'legacy' },
  { vid: LOGI, pid: 0xc11f, name: '1000-series touch remote', protocol: 'legacy' },
  { vid: LOGI, pid: 0xc120, name: 'Model 51 remote', protocol: 'legacy' },
  { vid: LOGI, pid: 0xc121, name: 'Model 54 remote', protocol: 'legacy' },
  // Shared by model 66 (legacy) and model 96 (packet); Chorus tries the packet protocol.
  { vid: LOGI, pid: 0xc122, name: 'Model 66 / 96 remote', protocol: 'mixed' },
  { vid: LOGI, pid: 0xc124, name: 'Model 78 / 104 remote', protocol: 'packet' },
  { vid: LOGI, pid: 0xc125, name: 'Model 80 / 103 remote', protocol: 'packet' },
  { vid: LOGI, pid: 0xc126, name: 'Model 82 remote', protocol: 'packet' },
  { vid: LOGI, pid: 0xc127, name: 'Model 86 remote', protocol: 'packet' },
  { vid: LOGI, pid: 0xc129, name: 'Hub (models 97 / 106 / 400)', protocol: 'packet' },
  { vid: LOGI, pid: 0xc12b, name: 'Touch / RF remote (models 99–116)', protocol: 'packet' },
  { vid: LOGI, pid: 0xc131, name: 'Express hub (model 113)', protocol: 'packet' },
  { vid: LOGI, pid: 0xc132, name: 'Model 115 remote', protocol: 'packet' },
];

export const hidFilters = () => REMOTES.map(({ vid, pid }) => ({ vendorId: vid, productId: pid }));

export function lookupRemote(vendorId, productId) {
  return REMOTES.find((r) => r.vid === vendorId && r.pid === productId) ?? null;
}

export const hex4 = (n) => '0x' + n.toString(16).toUpperCase().padStart(4, '0');
