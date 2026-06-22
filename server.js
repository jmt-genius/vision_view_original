import express from 'express';
import open from 'open';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const app = express();
const PORT = process.env.PORT || 3000;

app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

// Action State
let projectServerInstance = null;
let projectServerActive = false;
let lastGesture = 'None';
let lastGestureTime = null;
const systemLogs = [];

function logEvent(type, message) {
  const timestamp = new Date().toISOString();
  systemLogs.push({ timestamp, type, message });
  console.log(`[${type}] ${message}`);
  // Keep logs at max 100 entries
  if (systemLogs.length > 100) systemLogs.shift();
}

// Extract AFFERENS_API_KEY from mcp_config.json
let AFFERENS_API_KEY = process.env.AFFERENS_API_KEY || '';
if (!AFFERENS_API_KEY) {
  try {
    const userProfile = process.env.USERPROFILE || 'C:\\Users\\tarun';
    const mcpConfigPath = path.join(userProfile, '.gemini', 'antigravity-ide', 'mcp_config.json');
    if (fs.existsSync(mcpConfigPath)) {
      const configData = JSON.parse(fs.readFileSync(mcpConfigPath, 'utf8'));
      AFFERENS_API_KEY = configData.mcpServers?.afferens?.env?.AFFERENS_API_KEY || '';
      if (AFFERENS_API_KEY) {
        logEvent('SYSTEM', 'Successfully loaded Afferens API Key from mcp_config.json');
      }
    }
  } catch (err) {
    logEvent('SYSTEM', `Failed to parse mcp_config.json: ${err.message}`);
  }
}

if (!AFFERENS_API_KEY) {
  logEvent('SYSTEM', 'Warning: AFFERENS_API_KEY is not set. Ingestion to Afferens cloud will fail.');
}

// Ingest gesture event into Afferens Cloud API
async function ingestToAfferens(gesture) {
  if (!AFFERENS_API_KEY) {
    logEvent('INGEST', 'Skipping Afferens cloud ingestion (API Key missing)');
    return { error: 'API Key missing' };
  }

  const classification = gesture === 'open_hand' ? 'open hand' : gesture === 'peace_sign' ? 'peace sign' : 'pointing';
  
  try {
    const response = await fetch('https://afferens.com/api/ingest', {
      method: 'POST',
      headers: {
        'X-API-KEY': AFFERENS_API_KEY,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        modality: 'VISION',
        data: {
          gesture,
          confidence: 0.99,
          timestamp: new Date().toISOString()
        },
        classification
      })
    });

    const body = await response.json();
    if (response.ok) {
      logEvent('INGEST', `Ingested gesture event: "${classification}" (${body.entity_id})`);
      return body;
    } else {
      logEvent('INGEST', `Afferens Cloud API ingestion failed: ${JSON.stringify(body)}`);
      return { error: body };
    }
  } catch (err) {
    logEvent('INGEST', `Error posting to Afferens API: ${err.message}`);
    return { error: err.message };
  }
}

// Action executor based on gesture
async function executeGestureAction(gesture) {
  lastGesture = gesture;
  lastGestureTime = new Date().toISOString();

  switch (gesture) {
    case 'open_hand':
      logEvent('ACTION', 'Triggered: Debug Workspace Page');
      // If the project server is active, open port 5000, else open port 3000
      const debugUrl = projectServerActive ? 'http://localhost:5000' : `http://localhost:${PORT}`;
      logEvent('ACTION', `Opening browser debug window for: ${debugUrl}`);
      await open(debugUrl);

      // Perform a mock diagnostics sweep of the workspace files
      const files = fs.readdirSync(__dirname);
      const projectState = projectServerActive ? 'ONLINE (Port 5000)' : 'OFFLINE';
      const helloExists = fs.existsSync(path.join(__dirname, 'hello.js'));
      const report = `
=== AGENT DIAGNOSTICS REPORT ===
Timestamp: ${new Date().toISOString()}
Project Server Status: ${projectState}
Workspace Files Found: ${files.join(', ')}
"hello.js" File Created: ${helloExists ? 'YES' : 'NO'}
Afferens API Key Connected: ${AFFERENS_API_KEY ? 'YES' : 'NO'}
================================`;
      logEvent('ACTION', `Diagnostics output: ${report}`);
      break;

    case 'peace_sign':
      logEvent('ACTION', 'Triggered: Run Project Automatically');
      if (projectServerActive) {
        logEvent('ACTION', 'Project server is already active on port 5000.');
        break;
      }

      // Spin up the secondary server
      const projectApp = express();
      projectApp.get('/', (req, res) => {
        res.send(`
          <!DOCTYPE html>
          <html>
          <head>
            <title>Running Project Dashboard</title>
            <style>
              body {
                background: #0d0d12;
                color: #f1f5f9;
                font-family: 'Outfit', -apple-system, sans-serif;
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100vh;
                margin: 0;
                overflow: hidden;
              }
              .card {
                background: rgba(30, 30, 45, 0.55);
                backdrop-filter: blur(16px);
                border: 1px solid rgba(255, 255, 255, 0.08);
                padding: 3rem;
                border-radius: 28px;
                box-shadow: 0 10px 40px 0 rgba(0, 0, 0, 0.4);
                text-align: center;
                max-width: 480px;
                animation: fadeIn 0.8s cubic-bezier(0.16, 1, 0.3, 1);
              }
              h1 {
                background: linear-gradient(135deg, #a855f7 0%, #3b82f6 100%);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                margin-top: 0;
                margin-bottom: 0.75rem;
                font-size: 2.6rem;
                font-weight: 700;
                letter-spacing: -0.025em;
              }
              p {
                color: #94a3b8;
                font-size: 1.15rem;
                line-height: 1.6;
                margin-bottom: 1.5rem;
              }
              .pulse {
                width: 90px;
                height: 90px;
                background: rgba(168, 85, 247, 0.15);
                border-radius: 50%;
                display: flex;
                align-items: center;
                justify-content: center;
                margin: 0 auto 2rem auto;
                border: 2px solid #a855f7;
                box-shadow: 0 0 25px rgba(168, 85, 247, 0.35);
                animation: pulse-glow 2s infinite ease-in-out;
              }
              @keyframes pulse-glow {
                0% { transform: scale(1); box-shadow: 0 0 25px rgba(168, 85, 247, 0.35); }
                50% { transform: scale(1.06); box-shadow: 0 0 45px rgba(168, 85, 247, 0.65); }
                100% { transform: scale(1); box-shadow: 0 0 25px rgba(168, 85, 247, 0.35); }
              }
              @keyframes fadeIn {
                from { opacity: 0; transform: translateY(24px); }
                to { opacity: 1; transform: translateY(0); }
              }
            </style>
          </head>
          <body>
            <div class="card">
              <div class="pulse">
                <svg width="45" height="45" viewBox="0 0 24 24" fill="none" stroke="#a855f7" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <polygon points="5 3 19 12 5 21 5 3"></polygon>
                </svg>
              </div>
              <h1>Project Active</h1>
              <p>The developer project workspace was spun up automatically on port 5000 using your hand gestures.</p>
            </div>
          </body>
          </html>
        `);
      });

      projectServerInstance = projectApp.listen(5000, () => {
        projectServerActive = true;
        logEvent('ACTION', 'Project server started successfully on port 5000.');
      });
      break;

    case 'pointing':
      logEvent('ACTION', 'Triggered: Write Hello World Code');
      const helloPath = path.join(__dirname, 'hello.js');
      const codeContent = 'console.log("Hello, World!");\n';
      
      try {
        fs.writeFileSync(helloPath, codeContent, 'utf8');
        logEvent('ACTION', `Successfully wrote file: ${helloPath}`);
      } catch (err) {
        logEvent('ACTION', `Failed to write hello.js file: ${err.message}`);
      }
      break;

    default:
      logEvent('ACTION', `Unhandled gesture type: ${gesture}`);
  }
}

// Ingest + Execute endpoint
app.post('/api/gesture', async (req, res) => {
  const { gesture } = req.body;
  
  if (!gesture || !['open_hand', 'peace_sign', 'pointing'].includes(gesture)) {
    return res.status(400).json({ error: 'Invalid gesture type' });
  }

  logEvent('SYSTEM', `Received gesture from webcam: "${gesture}"`);
  
  // 1. Ingest to Afferens cloud
  const ingestResult = await ingestToAfferens(gesture);

  // 2. Perform local action
  await executeGestureAction(gesture);

  res.json({
    success: true,
    gesture,
    actionExecuted: true,
    ingestResult
  });
});

// Logs feed endpoint
app.get('/api/logs', (req, res) => {
  res.json(systemLogs);
});

// Current status endpoint
app.get('/api/status', (req, res) => {
  const helloExists = fs.existsSync(path.join(__dirname, 'hello.js'));
  res.json({
    projectServerActive,
    helloFileCreated: helloExists,
    lastGesture,
    lastGestureTime,
    afferensConnected: !!AFFERENS_API_KEY
  });
});

// Start Main server
app.listen(PORT, () => {
  logEvent('SYSTEM', `Vision Control Center coordinator started at http://localhost:${PORT}`);
});
