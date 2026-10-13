// Tiny static file server for running Chorus locally. No dependencies.
// Usage: node serve.mjs [port]      (default port 8080)
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { extname, join, normalize, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { exec } from 'node:child_process';

const root = fileURLToPath(new URL('.', import.meta.url));
const port = Number(process.argv[2] ?? process.env.PORT ?? 8080);
const types = {
  '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8', '.svg': 'image/svg+xml', '.json': 'application/json',
  '.webmanifest': 'application/manifest+json', '.png': 'image/png', '.ico': 'image/x-icon',
};

const server = createServer(async (req, res) => {
  let path = decodeURIComponent(new URL(req.url, 'http://localhost').pathname);
  if (path.endsWith('/')) path += 'index.html';
  const file = normalize(join(root, path));
  if (!file.startsWith(root.endsWith(sep) ? root : root + sep)) {
    res.writeHead(403).end('Forbidden');
    return;
  }
  try {
    const body = await readFile(file);
    res.writeHead(200, { 'Content-Type': types[extname(file)] ?? 'application/octet-stream', 'Cache-Control': 'no-store' });
    res.end(body);
  } catch {
    res.writeHead(404, { 'Content-Type': 'text/plain' }).end('Not found');
  }
});

server.on('error', (e) => {
  if (e.code === 'EADDRINUSE') {
    console.error(`Port ${port} is already in use. Try another one:  node serve.mjs ${port + 1}`);
  } else {
    console.error(e.message);
  }
  process.exit(1);
});

server.listen(port, '127.0.0.1', () => {
  const url = `http://localhost:${port}/`;
  console.log(`Chorus is running at ${url}`);
  console.log('Leave this window open while you use the app. Press Ctrl+C to stop.');
  if (!process.argv.includes('--no-open')) {
    const cmd = process.platform === 'win32' ? `start "" "${url}"` : process.platform === 'darwin' ? `open "${url}"` : `xdg-open "${url}"`;
    exec(cmd, () => {});
  }
});
