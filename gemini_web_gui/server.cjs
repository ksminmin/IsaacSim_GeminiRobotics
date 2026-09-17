/**
 * Gemini Robotics ER 2 Backend control server.
 */

const express = require('express');
const cors = require('cors');
const { spawn } = require('child_process');

/* ── WSL2 environment (override via env vars) ─────────────── */
const WSL_DISTRO = process.env.WSL_DISTRO || 'Ubuntu-24.04';
const WSL_WS = process.env.WSL_WS || '/home/min/catkin_ws';
const ROS_SETUP = process.env.ROS_SETUP || '/opt/ros/jazzy/setup.bash';

const app = express();
app.use(cors());
app.use(express.json());

/* ── State ────────────────────────────────────────────────── */
let bringupProc = null;
let logBuffer = [];
const MAX_LOG_LINES = 2000;
let sseClients = [];

function broadcast(data) {
  const payload = `data: ${JSON.stringify(data)}\n\n`;
  sseClients.forEach(res => res.write(payload));
}

function appendLog(line) {
  logBuffer.push(line);
  if (logBuffer.length > MAX_LOG_LINES) logBuffer = logBuffer.slice(-MAX_LOG_LINES);
  broadcast({ type: 'log', line });
}

/* ── SSE endpoint ─────────────────────────────────────────── */
app.get('/api/logs', (req, res) => {
  res.writeHead(200, {
    'Content-Type': 'text/event-stream',
    'Cache-Control': 'no-cache',
    'Connection': 'keep-alive',
  });
  logBuffer.forEach(line => res.write(`data: ${JSON.stringify({ type: 'log', line })}\n\n`));
  sseClients.push(res);
  req.on('close', () => { sseClients = sseClients.filter(c => c !== res); });
});

/* ── Status ───────────────────────────────────────────────── */
app.get('/api/status', (_req, res) => {
  res.json({ running: bringupProc !== null && !bringupProc.killed });
});

/* ── Build ────────────────────────────────────────────────── */
app.post('/api/build', (_req, res) => {
  appendLog('[GUI] Triggering colcon build in WSL2...');
  const buildProc = spawn('wsl', ['-d', WSL_DISTRO, 'bash', '-c', `cd ${WSL_WS} && source ${ROS_SETUP} && colcon build`]);
  buildProc.stdout.on('data', d => appendLog(d.toString()));
  buildProc.stderr.on('data', d => appendLog(d.toString()));
  buildProc.on('close', code => {
    appendLog(`[GUI] colcon build finished with code ${code}`);
  });
  res.json({ ok: true });
});

/* ── Start bringup ────────────────────────────────────────── */
app.post('/api/start', (_req, res) => {
  if (bringupProc && !bringupProc.killed) {
    return res.json({ ok: false, msg: 'Already running' });
  }

  logBuffer = [];
  appendLog('[GUI] Cleaning up old processes before start...');
  const pkill = require('child_process').spawnSync('wsl', ['-d', WSL_DISTRO, 'bash', '-c', 'pkill -f gemini_controller; pkill -f rosbridge; pkill -f multi_robot; pkill -f bringup.bash']);
  appendLog('[GUI] Starting bringup.bash (Gemini mode)...');

  const cmd = `echo 1 | bash ${WSL_WS}/bringup.bash`;

  bringupProc = spawn('wsl', ['-d', WSL_DISTRO, 'bash', '-c', cmd], {
    stdio: ['ignore', 'pipe', 'pipe'],
  });

  bringupProc.stdout.on('data', (chunk) => {
    chunk.toString().split('\n').filter(Boolean).forEach(line => appendLog(line));
  });

  bringupProc.stderr.on('data', (chunk) => {
    chunk.toString().split('\n').filter(Boolean).forEach(line => appendLog('[stderr] ' + line));
  });

  bringupProc.on('exit', (code) => {
    appendLog(`[GUI] bringup.bash exited with code ${code}`);
    broadcast({ type: 'status', running: false });
    bringupProc = null;
  });

  broadcast({ type: 'status', running: true });
  res.json({ ok: true });
});

/* ── Stop bringup ─────────────────────────────────────────── */
app.post('/api/stop', (_req, res) => {
  if (!bringupProc || bringupProc.killed) {
    return res.json({ ok: false, msg: 'Not running' });
  }

  appendLog('[GUI] Stopping bringup processes...');
  spawn('wsl', ['-d', WSL_DISTRO, 'bash', '-c',
    'pkill -f gemini_controller.launch.py; pkill -f rosbridge_websocket; pkill -f multi_robot_controller',
  ]);

  bringupProc.kill('SIGINT');
  setTimeout(() => {
    if (bringupProc && !bringupProc.killed) bringupProc.kill('SIGKILL');
    bringupProc = null;
    broadcast({ type: 'status', running: false });
  }, 2000);

  res.json({ ok: true });
});

const PORT = 3001;
app.listen(PORT, () => {
  console.log(`[Gemini GUI Server] Running on http://localhost:${PORT}`);
});
