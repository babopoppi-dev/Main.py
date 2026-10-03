// MCP Andrea local backend. Upstream engine: Desktop Commander, MIT licensed.
// Fixed caller-selected install path; never accept this path from a tool call.
import { pathToFileURL } from 'node:url';
import path from 'node:path';
import fs from 'node:fs/promises';

// Set before the first filesystem request initializes libuv's worker pool.
process.env.UV_THREADPOOL_SIZE ??= '16';

if (process.env.DESKTOP_COMMANDER_DISABLE_TELEMETRY !== '1') {
  throw new Error('Telemetry kill switch must be set before loading the backend');
}
const root = process.argv[2];
if (!root || !path.isAbsolute(root)) throw new Error('Absolute backend path required');
const pkg = JSON.parse(await fs.readFile(path.join(root, 'package.json'), 'utf8'));
if (pkg.name !== '@wonderwhy-er/desktop-commander' || pkg.version !== '0.2.52') {
  throw new Error('Unreviewed backend version');
}
global.disableOnboarding = true;
const load = name => import(pathToFileURL(path.join(root, 'dist', name)).href);
await load('bootstrap.js');
const { configManager } = await load('config-manager.js');
await configManager.loadConfig();
if (await configManager.getValue('telemetryEnabled') !== false) {
  throw new Error('Telemetry must also be disabled in local configuration');
}
const { server, flushDeferredMessages } = await load('server.js');
const { FilteredStdioServerTransport } = await load('custom-stdio.js');
const transport = new FilteredStdioServerTransport();
global.mcpTransport = transport;
server.oninitialized = () => {
  transport.enableNotifications();
  flushDeferredMessages();
};
// Deliberately use the local server entry point: no remote pairing, onboarding,
// feature-flag refresh, setup, update, or Chrome pre-download is started here.
await server.connect(transport);

async function stop() {
  try { await server.close(); } finally { process.exit(0); }
}
process.once('SIGTERM', stop);
process.once('SIGINT', stop);
