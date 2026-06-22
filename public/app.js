// DOM Elements
const videoElement = document.getElementById('webcam');
const canvasElement = document.getElementById('overlay');
const canvasCtx = canvasElement.getContext('2d');
const loadingOverlay = document.getElementById('loading-overlay');

const badgeCamera = document.getElementById('badge-camera');
const badgeModel = document.getElementById('badge-model');
const badgeAfferens = document.getElementById('badge-afferens');

const currentGestureEl = document.getElementById('current-gesture');
const holdProgressEl = document.getElementById('hold-progress');

const stateProjectServer = document.getElementById('state-project-server');
const stateHelloFile = document.getElementById('state-hello-file');
const stateAfferensApi = document.getElementById('state-afferens-api');

const logsContainer = document.getElementById('logs-container');
const btnClearLogs = document.getElementById('btn-clear-logs');

// App State
let activeGesture = 'none';
let stableGesture = 'none';
let gestureStartTime = null;
let lastTriggeredGesture = 'none';
const HOLD_DURATION = 800; // ms required to trigger
let knownLogCount = 0;

// Setup canvas size
function resizeCanvas() {
  canvasElement.width = videoElement.clientWidth || 640;
  canvasElement.height = videoElement.clientHeight || 480;
}
window.addEventListener('resize', resizeCanvas);
videoElement.addEventListener('loadedmetadata', resizeCanvas);

// Log message to UI feed
function appendUILog(type, text) {
  const entry = document.createElement('div');
  entry.className = `log-entry log-${type.toLowerCase()}`;
  const time = new Date().toLocaleTimeString();
  entry.innerText = `[${time}] [${type}] ${text}`;
  logsContainer.appendChild(entry);
  logsContainer.scrollTop = logsContainer.scrollHeight;
}

// Clear UI logs
btnClearLogs.addEventListener('click', () => {
  logsContainer.innerHTML = '<div class="log-entry log-system">[SYSTEM] Logs cleared.</div>';
});

// Gesture classification logic
function classifyHandGesture(landmarks) {
  const wrist = landmarks[0];
  
  // Calculate distance from wrist (0) to any landmark
  const getWristDist = (lm) => {
    return Math.hypot(lm.x - wrist.x, lm.y - wrist.y);
  };

  // Check extended state of the four fingers
  // Finger is "UP" if tip distance to wrist > pip joint distance to wrist
  const indexUp = getWristDist(landmarks[8]) > getWristDist(landmarks[6]);
  const middleUp = getWristDist(landmarks[12]) > getWristDist(landmarks[10]);
  const ringUp = getWristDist(landmarks[16]) > getWristDist(landmarks[14]);
  const pinkyUp = getWristDist(landmarks[20]) > getWristDist(landmarks[18]);

  // Gesture mapping heuristics
  if (indexUp && middleUp && ringUp && pinkyUp) {
    return 'open_hand';
  } else if (indexUp && middleUp && !ringUp && !pinkyUp) {
    return 'peace_sign';
  } else if (indexUp && !middleUp && !ringUp && !pinkyUp) {
    return 'pointing';
  }
  
  return 'none';
}

// Trigger backend action & Afferens Ingest
async function triggerGestureAction(gesture) {
  appendUILog('ACTION', `Executing trigger for: ${gesture}`);
  
  try {
    const res = await fetch('/api/gesture', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({ gesture })
    });
    
    const data = await res.json();
    if (data.success) {
      appendUILog('INGEST', `Successfully registered gesture with agent.`);
      fetchStatus();
      fetchLogs();
    } else {
      appendUILog('ERROR', `Backend error: ${data.error}`);
    }
  } catch (err) {
    appendUILog('ERROR', `Failed to contact server: ${err.message}`);
  }
}

// Custom skeletal drawing logic
function drawHandSkeleton(landmarks) {
  canvasCtx.clearRect(0, 0, canvasElement.width, canvasElement.height);
  
  // Draw connection lines
  const drawLine = (pt1, pt2) => {
    canvasCtx.beginPath();
    canvasCtx.moveTo(pt1.x * canvasElement.width, pt1.y * canvasElement.height);
    canvasCtx.lineTo(pt2.x * canvasElement.width, pt2.y * canvasElement.height);
    canvasCtx.stroke();
  };

  // Set line styles (neon blue glow)
  canvasCtx.strokeStyle = 'rgba(59, 130, 246, 0.8)';
  canvasCtx.lineWidth = 4;
  canvasCtx.shadowBlur = 10;
  canvasCtx.shadowColor = 'rgba(59, 130, 246, 0.5)';

  // Define Hand skeletons
  const fingers = [
    [0, 1, 2, 3, 4],       // Thumb
    [0, 5, 6, 7, 8],       // Index
    [9, 10, 11, 12],       // Middle
    [13, 14, 15, 16],      // Ring
    [0, 17, 18, 19, 20]    // Pinky
  ];

  // Draw connections
  fingers.forEach(chain => {
    for (let i = 0; i < chain.length - 1; i++) {
      drawLine(landmarks[chain[i]], landmarks[chain[i+1]]);
    }
  });

  // Knuckle connectors
  drawLine(landmarks[5], landmarks[9]);
  drawLine(landmarks[9], landmarks[13]);
  drawLine(landmarks[13], landmarks[17]);

  // Draw joints/landmarks (glowing white dots with purple borders)
  canvasCtx.shadowBlur = 0; // disable shadow for dots
  landmarks.forEach(lm => {
    const cx = lm.x * canvasElement.width;
    const cy = lm.y * canvasElement.height;
    
    // Outer purple ring
    canvasCtx.fillStyle = '#8b5cf6';
    canvasCtx.beginPath();
    canvasCtx.arc(cx, cy, 6, 0, 2 * Math.PI);
    canvasCtx.fill();

    // Inner white center
    canvasCtx.fillStyle = '#ffffff';
    canvasCtx.beginPath();
    canvasCtx.arc(cx, cy, 3, 0, 2 * Math.PI);
    canvasCtx.fill();
  });
}

// MediaPipe Hands callback
function onResults(results) {
  // Hide initialisation overlay once first frame is processed
  if (loadingOverlay.style.opacity !== '0') {
    loadingOverlay.style.opacity = '0';
    setTimeout(() => loadingOverlay.style.display = 'none', 500);
    badgeModel.className = 'badge badge-success';
    badgeModel.innerText = 'Hand Model Active';
  }

  // Clear canvas if no hands are visible
  if (!results.multiHandLandmarks || results.multiHandLandmarks.length === 0) {
    canvasCtx.clearRect(0, 0, canvasElement.width, canvasElement.height);
    updateGestureState('none');
    return;
  }

  const handLandmarks = results.multiHandLandmarks[0];
  
  // Render modern skeleton overlay
  drawHandSkeleton(handLandmarks);
  
  // Classify current pose
  const detected = classifyHandGesture(handLandmarks);
  updateGestureState(detected);
}

// Update gesture classification & debounce timing
function updateGestureState(detected) {
  activeGesture = detected;
  
  // UI Display updates
  if (detected === 'none') {
    currentGestureEl.innerText = 'None';
    currentGestureEl.className = 'gesture-val';
  } else {
    const formatted = detected.toUpperCase().replace('_', ' ');
    currentGestureEl.innerText = formatted;
    currentGestureEl.className = `gesture-val state-${detected.replace('_', '-')}`;
  }

  // Debounce stable gestures
  if (detected === 'none') {
    stableGesture = 'none';
    lastTriggeredGesture = 'none';
    holdProgressEl.style.width = '0%';
    return;
  }

  if (detected !== stableGesture) {
    // New gesture detected, reset stable hold timing
    stableGesture = detected;
    gestureStartTime = Date.now();
    holdProgressEl.style.width = '0%';
  } else {
    // Stable gesture being held, check duration
    const elapsed = Date.now() - gestureStartTime;
    const progress = Math.min(100, (elapsed / HOLD_DURATION) * 100);
    holdProgressEl.style.width = `${progress}%`;

    if (elapsed >= HOLD_DURATION && lastTriggeredGesture !== stableGesture) {
      lastTriggeredGesture = stableGesture;
      triggerGestureAction(stableGesture);
    }
  }
}

// Initialise Camera
async function startCamera() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      video: { width: 640, height: 480, facingMode: 'user' }
    });
    videoElement.srcObject = stream;
    videoElement.addEventListener('loadeddata', () => {
      badgeCamera.className = 'badge badge-success';
      badgeCamera.innerText = 'Webcam Connected';
      resizeCanvas();
    });

    // Create frame processor
    const processFrame = async () => {
      if (videoElement.readyState === videoElement.HAVE_ENOUGH_DATA) {
        await hands.send({ image: videoElement });
      }
      requestAnimationFrame(processFrame);
    };
    requestAnimationFrame(processFrame);

  } catch (err) {
    badgeCamera.className = 'badge badge-error';
    badgeCamera.innerText = 'Camera Error';
    appendUILog('ERROR', `Could not access camera: ${err.message}`);
    alert('Webcam permission is required to track gestures.');
  }
}

// Initialize MediaPipe Hands
const hands = new Hands({
  locateFile: (file) => `https://cdn.jsdelivr.net/npm/@mediapipe/hands/${file}`
});

hands.setOptions({
  maxNumHands: 1,
  modelComplexity: 1,
  minDetectionConfidence: 0.5,
  minTrackingConfidence: 0.5
});

hands.onResults(onResults);

// Status Poller
async function fetchStatus() {
  try {
    const res = await fetch('/api/status');
    const data = await res.json();
    
    // Update server badges
    stateProjectServer.innerText = data.projectServerActive ? 'Online' : 'Offline';
    stateProjectServer.className = `state-value ${data.projectServerActive ? 'val-active' : 'val-inactive'}`;
    
    stateHelloFile.innerText = data.helloFileCreated ? 'Yes' : 'No';
    stateHelloFile.className = `state-value ${data.helloFileCreated ? 'val-active' : 'val-inactive'}`;

    stateAfferensApi.innerText = data.afferensConnected ? 'Connected' : 'Offline';
    stateAfferensApi.className = `state-value ${data.afferensConnected ? 'val-active' : 'val-error'}`;

    badgeAfferens.innerText = data.afferensConnected ? 'Afferens: Connected' : 'Afferens: Key Missing';
    badgeAfferens.className = `badge ${data.afferensConnected ? 'badge-success' : 'badge-error'}`;
  } catch (err) {
    console.error('Error fetching status:', err);
  }
}

// Server Logs Poller
async function fetchLogs() {
  try {
    const res = await fetch('/api/logs');
    const logs = await res.json();
    
    if (logs.length > knownLogCount) {
      // Append only new logs
      for (let i = knownLogCount; i < logs.length; i++) {
        appendUILog(logs[i].type, logs[i].message);
      }
      knownLogCount = logs.length;
    }
  } catch (err) {
    console.error('Error fetching logs:', err);
  }
}

// Initialise App
startCamera();
fetchStatus();
fetchLogs();

// Start pollers
setInterval(fetchStatus, 2000);
setInterval(fetchLogs, 1500);
