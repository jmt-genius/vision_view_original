import cv2
import mediapipe as mp
import math
import os
import sys
import json
import time
import subprocess
import webbrowser
import urllib.parse
from datetime import datetime
import requests
import tkinter as tk
from tkinter import scrolledtext, messagebox
from PIL import Image, ImageTk
from google import genai

# App Global State
AFFERENS_API_KEY = ""
GEMINI_API_KEY = ""
CONVERSATION_DIR = ""
LAST_TRIGGERED_GESTURE = "none"
STABLE_GESTURE = "none"
HOLD_COUNT = 0
REQUIRED_HOLD_FRAMES = 15 # Approx 0.75s
AFFERENS_STATUS = "Checking..."
GEMINI_STATUS = "Checking..."
SESSION_START_TIME = datetime.now()
SESSION_LOG_PATH = "session.log"
GESTURE_COUNTS = {}
gemini_client = None  # Will be initialized after loading env

# MediaPipe Hands setup
mp_hands = mp.solutions.hands
hands = mp_hands.Hands(
    static_image_mode=False,
    max_num_hands=2,
    min_detection_confidence=0.6,
    min_tracking_confidence=0.6
)

# Custom log mechanism
def log_session_event(gesture, action):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] Gesture: {gesture} | Action: {action}\n"
    
    # Increment count
    GESTURE_COUNTS[gesture] = GESTURE_COUNTS.get(gesture, 0) + 1
    
    try:
        with open(SESSION_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(log_entry)
    except Exception as e:
        print(f"Failed to write to session.log: {e}")
        
    if app_ui:
        app_ui.append_log(f"[{datetime.now().strftime('%H:%M:%S')}] [TRIGGER] {action}")

# Load .env variables manually and initialize Gemini SDK client
def load_env():
    global GEMINI_API_KEY, gemini_client
    if os.path.exists(".env"):
        try:
            with open(".env", "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        if k.strip() == "GEMINI_API_KEY":
                            GEMINI_API_KEY = v.strip()
        except Exception as e:
            print(f"Failed to load .env: {e}")

    # Initialize Gemini SDK client
    if GEMINI_API_KEY:
        try:
            gemini_client = genai.Client(api_key=GEMINI_API_KEY)
            print("[SYSTEM] Gemini SDK client initialized (gemini-3.5-flash)")
        except Exception as e:
            print(f"[SYSTEM] Failed to initialize Gemini client: {e}")

# Load Afferens Configuration
def load_afferens_config():
    global AFFERENS_API_KEY, CONVERSATION_DIR
    try:
        user_profile = os.environ.get("USERPROFILE", "C:\\Users\\tarun")
        mcp_config_path = os.path.join(user_profile, ".gemini", "antigravity-ide", "mcp_config.json")
        if os.path.exists(mcp_config_path):
            with open(mcp_config_path, "r", encoding="utf-8") as f:
                config_data = json.load(f)
                AFFERENS_API_KEY = config_data.get("mcpServers", {}).get("afferens", {}).get("env", {}).get("AFFERENS_API_KEY", "")
        
        # Resolve active conversation ID
        brain_path = os.path.join(user_profile, ".gemini", "antigravity-ide", "brain")
        if os.path.exists(brain_path):
            subdirs = [os.path.join(brain_path, d) for d in os.listdir(brain_path) if os.path.isdir(os.path.join(brain_path, d))]
            if subdirs:
                subdirs.sort(key=os.path.getmtime, reverse=True)
                CONVERSATION_DIR = subdirs[0]
    except Exception as e:
        print(f"Failed to load config: {e}")

# Initialize session log file
def init_session_log():
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(SESSION_LOG_PATH, "w", encoding="utf-8") as f:
            f.write(f"=== Session Started: {timestamp} ===\n")
    except Exception as e:
        print(f"Failed to init session.log: {e}")

# Call Gemini API using official google-genai SDK
def call_gemini_api(prompt):
    if not gemini_client:
        return "Error: Gemini client not initialized. Please add GEMINI_API_KEY to your .env file."

    try:
        response = gemini_client.models.generate_content(
            model="gemini-3.5-flash",
            contents=prompt
        )
        return response.text
    except Exception as e:
        return f"Gemini API error: {e}"

# Ingest event to Afferens cloud
def ingest_to_afferens(gesture):
    global AFFERENS_STATUS
    if not AFFERENS_API_KEY:
        AFFERENS_STATUS = "No Key"
        return
        
    classification = gesture.replace("_", " ")
    try:
        res = requests.post(
            "https://afferens.com/api/ingest",
            headers={
                "X-API-KEY": AFFERENS_API_KEY,
                "Content-Type": "application/json"
            },
            json={
                "modality": "VISION",
                "data": {"gesture": gesture, "timestamp": datetime.utcnow().isoformat() + "Z"},
                "classification": classification
            },
            timeout=3
        )
        if res.status_code == 200:
            AFFERENS_STATUS = "Connected"
        else:
            AFFERENS_STATUS = "Ingest Error"
    except Exception:
        AFFERENS_STATUS = "Network Error"

# Finger distance calculations
def get_distance(p1, p2):
    return math.hypot(p1.x - p2.x, p1.y - p2.y)

# 7-Gesture Classification Logic
def classify_frame_gestures(multi_hand_landmarks):
    if not multi_hand_landmarks:
        return "none"
        
    # Check for two hands
    if len(multi_hand_landmarks) == 2:
        return "two_hands"
        
    # Single hand classification
    landmarks = multi_hand_landmarks[0].landmark
    wrist = landmarks[0]
    
    # Check four fingers UP state
    index_up = get_distance(landmarks[8], wrist) > get_distance(landmarks[6], wrist)
    middle_up = get_distance(landmarks[12], wrist) > get_distance(landmarks[10], wrist)
    ring_up = get_distance(landmarks[16], wrist) > get_distance(landmarks[14], wrist)
    pinky_up = get_distance(landmarks[20], wrist) > get_distance(landmarks[18], wrist)
    
    # Calculate finger count
    fingers_count = sum([index_up, middle_up, ring_up, pinky_up])
    
    # Map fingers to gesture names
    if fingers_count == 4:
        return "open_hand"     # 4 fingers + thumb or full hand
    elif fingers_count == 3:
        return "four_fingers"  # 4 fingers up, ring/pinky up (depending on thumb/heuristics, mapping counts)
    elif fingers_count == 2:
        # Check if Index and Middle are up
        if index_up and middle_up:
            return "peace_sign"
        return "three_fingers"
    elif fingers_count == 1:
        # Check index up
        if index_up:
            return "one_finger"
        return "three_fingers"
    elif fingers_count == 0:
        return "fist"
        
    # General fallback based on count
    up_count = sum([index_up, middle_up, ring_up, pinky_up])
    # Let's map counts directly:
    # 0 = fist, 1 = one_finger, 2 = peace_sign (or three_fingers depending on which fingers),
    # 3 = three_fingers, 4 = four_fingers (or open_hand depending on thumb)
    # Let's check thumb state to differentiate between 4 and 5 fingers:
    thumb_tip = landmarks[4]
    thumb_base = landmarks[2]
    thumb_extended = get_distance(thumb_tip, landmarks[5]) > get_distance(thumb_base, landmarks[5])
    
    total_fingers = up_count + (1 if thumb_extended else 0)
    
    if total_fingers == 0:
        return "fist"
    elif total_fingers == 1:
        return "one_finger"
    elif total_fingers == 2:
        return "peace_sign"
    elif total_fingers == 3:
        return "three_fingers"
    elif total_fingers == 4:
        return "four_fingers"
    elif total_fingers >= 5:
        return "open_hand"
        
    return "none"

# 7-Gesture Actions Implementation

# ✊ Fist (0 fingers): Google Search clipboard
def action_fist(clipboard_text):
    log_session_event("fist", "Google Search Clipboard")
    if not clipboard_text:
        clipboard_text = "HandShift"
    url = f"https://www.google.com/search?q={urllib.parse.quote(clipboard_text)}"
    webbrowser.open(url)
    app_ui.show_result_popup("Google Search Triggered", f"Searching Google for:\n\n'{clipboard_text}'")

# ☝️ One Finger (1 finger): Explain Last Error
def action_one_finger():
    log_session_event("one_finger", "Explain Last Error")
    if not CONVERSATION_DIR:
        app_ui.show_result_popup("Explain Last Error", "Error: Conversation task log directory could not be resolved.")
        return
        
    tasks_dir = os.path.join(CONVERSATION_DIR, ".system_generated", "tasks")
    if not os.path.exists(tasks_dir):
        app_ui.show_result_popup("Explain Last Error", "No task error logs exist yet.")
        return
        
    log_files = [os.path.join(tasks_dir, f) for f in os.listdir(tasks_dir) if f.endswith(".log")]
    if not log_files:
        app_ui.show_result_popup("Explain Last Error", "No log output found.")
        return
        
    log_files.sort(key=os.path.getmtime, reverse=True)
    latest_log = log_files[0]
    
    try:
        with open(latest_log, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        log_snippet = "".join(lines[-40:])
        
        prompt = f"Explain this command error trace in plain English, and provide a clear suggested fix:\n\n{log_snippet}"
        explanation = call_gemini_api(prompt)
        app_ui.show_result_popup(f"Last Error Explained ({os.path.basename(latest_log)})", explanation)
    except Exception as e:
        app_ui.show_result_popup("Explain Last Error", f"Failed to parse error: {e}")

# ✌️ Peace Sign (2 fingers): Summarize Current File
def action_peace_sign():
    log_session_event("peace_sign", "Summarize Current File")
    workspace_root = "c:\\JMT\\vision_view"
    valid_exts = (".js", ".py", ".json", ".html", ".css")
    newest_file = None
    newest_mtime = 0
    
    for root, dirs, files in os.walk(workspace_root):
        if any(exclude in root for exclude in (".git", "node_modules", "__pycache__")):
            continue
        for file in files:
            if file.endswith(valid_exts) and file != "vision_agent.py" and not file.startswith(".env"):
                file_path = os.path.join(root, file)
                try:
                    mtime = os.path.getmtime(file_path)
                    if mtime > newest_mtime:
                        newest_mtime = mtime
                        newest_file = file_path
                except Exception:
                    continue
                    
    if not newest_file:
        app_ui.show_result_popup("Summarize File", "No active files found to summarize in workspace.")
        return
        
    try:
        with open(newest_file, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
            
        prompt = f"Summarize the purpose, functions, structure, and any TODOs in this code file in clean, concise, plain English:\n\nFile: {os.path.basename(newest_file)}\n\nContent:\n{content[:8000]}"
        summary = call_gemini_api(prompt)
        app_ui.show_result_popup(f"File Summary: {os.path.basename(newest_file)}", summary)
    except Exception as e:
        app_ui.show_result_popup("Summarize File", f"Error summarizing file: {e}")

# 🤟 Three Fingers (3 fingers): Git Status Snapshot
def action_three_fingers():
    log_session_event("three_fingers", "Git Status Snapshot")
    try:
        status_res = subprocess.run(["git", "status"], capture_output=True, text=True, cwd="c:\\JMT\\vision_view")
        diff_res = subprocess.run(["git", "diff", "--stat"], capture_output=True, text=True, cwd="c:\\JMT\vision_view")
        
        git_output = f"=== Status ===\n{status_res.stdout}\n=== Stats ===\n{diff_res.stdout}"
        
        prompt = f"Summarize this git status and diff statistics in clean, plain English, highlighting the biggest changes and what is currently staged vs unstaged:\n\n{git_output}"
        summary = call_gemini_api(prompt)
        app_ui.show_result_popup("Git Status Snapshot", summary)
    except Exception as e:
        app_ui.show_result_popup("Git Status", f"Failed to run git: {e}")

# 🤘 Four Fingers (4 fingers): Commit Check
def action_four_fingers():
    log_session_event("four_fingers", "Commit Check")
    try:
        diff_res = subprocess.run(["git", "diff", "--stat"], capture_output=True, text=True, cwd="c:\\JMT\\vision_view")
        duration = datetime.now() - SESSION_START_TIME
        duration_mins = int(duration.total_seconds() / 60)
        
        prompt = (f"Review these git changes, check if the session is ready for a commit (Session duration: {duration_mins} mins, triggers: {sum(GESTURE_COUNTS.values())}). "
                  f"Give a clear, one-line verdict starting with either ✅ (go ahead) or ⚠️ (with specific reason why not):\n\n{diff_res.stdout}")
        
        verdict = call_gemini_api(prompt)
        app_ui.show_result_popup("Commit Verdict", verdict)
    except Exception as e:
        app_ui.show_result_popup("Commit Check", f"Failed to execute commit check: {e}")

# ✋ Open Hand (5 fingers): Paste clipboard to Gemini
def action_open_hand(clipboard_text):
    log_session_event("open_hand", "Paste Clipboard to Gemini")
    if not clipboard_text:
        clipboard_text = "(Clipboard Empty)"
        
    # 1. Open browser Gemini pre-filled
    web_url = f"https://gemini.google.com/app?prompt={urllib.parse.quote(clipboard_text)}"
    webbrowser.open(web_url)
    
    # 2. Call API for local popup help
    prompt = f"The user is stuck on this code, error, or concept. Review this clipboard content and provide instant help, highlighting any issues or fixes:\n\n{clipboard_text}"
    response = call_gemini_api(prompt)
    app_ui.show_result_popup("Instant Help (Gemini API)", response)

# 🤙 Two Hands (Both hands): End of session report
def action_two_hands():
    log_session_event("two_hands", "End of Session Report")
    
    duration = datetime.now() - SESSION_START_TIME
    duration_str = str(duration).split('.')[0]
    
    try:
        with open(SESSION_LOG_PATH, "r", encoding="utf-8") as f:
            logs = f.read()
    except Exception:
        logs = "(No session logs captured)"
        
    prompt = f"Write a clean, 3-bullet summary of the user's development session based on the logs of executed actions. Keep it concise:\n\nSession Duration: {duration_str}\nTotal Gestures: {sum(GESTURE_COUNTS.values())}\n\nLogs:\n{logs}"
    report = call_gemini_api(prompt)
    
    # Save report file
    date_str = datetime.now().strftime("%Y-%m-%d")
    report_file = f"report_{date_str}.md"
    try:
        with open(report_file, "w", encoding="utf-8") as f:
            f.write(f"# HandShift Developer Session Report ({date_str})\n\n{report}")
        log_session_event("system", f"Saved session report to {report_file}")
    except Exception as e:
        print(f"Failed to save report: {e}")
        
    app_ui.show_result_popup(f"Session Ended! Report Saved ({report_file})", report)

# Coordinator
def execute_gesture_action(gesture):
    global LAST_TRIGGERED_GESTURE
    
    clipboard = ""
    try:
        clipboard = app_ui.root.clipboard_get()
    except Exception:
        pass
        
    if gesture == "fist":
        action_fist(clipboard)
    elif gesture == "one_finger":
        action_one_finger()
    elif gesture == "peace_sign":
        action_peace_sign()
    elif gesture == "three_fingers":
        action_three_fingers()
    elif gesture == "four_fingers":
        action_four_fingers()
    elif gesture == "open_hand":
        action_open_hand(clipboard)
    elif gesture == "two_hands":
        action_two_hands()

# Tkinter User Interface Class
class HandShiftUI:
    def __init__(self, root):
        self.root = root
        self.root.title("HandShift")
        self.root.configure(bg="#0c0c0e")
        self.root.geometry("400x200") # Start in compact mode
        self.root.resizable(False, False)
        
        self.is_expanded = False
        
        # Configure Grid weight
        self.root.columnconfigure(0, weight=1)
        
        # 1. Header Frame
        header = tk.Frame(root, bg="#0c0c0e", height=40)
        header.grid(row=0, column=0, sticky="ew", padx=15, pady=8)
        
        brand_label = tk.Label(header, text="HandShift", font=("Outfit", 14, "bold"), fg="#8b5cf6", bg="#0c0c0e")
        brand_label.pack(side="left")
        
        # Status dot
        self.status_dot = tk.Label(header, text="●", font=("Arial", 12), fg="#10b981", bg="#0c0c0e")
        self.status_dot.pack(side="right", padx=5)
        
        self.status_label = tk.Label(header, text="Agent Running", font=("Inter", 9), fg="#94a3b8", bg="#0c0c0e")
        self.status_label.pack(side="right")
        
        # 2. Compact Info Panel
        self.info_panel = tk.Frame(root, bg="#16161d", bd=1, relief="solid")
        self.info_panel.grid(row=1, column=0, sticky="ew", padx=15, pady=5)
        
        self.gesture_lbl = tk.Label(self.info_panel, text="Gesture: NONE", font=("Outfit", 12, "bold"), fg="#f8fafc", bg="#16161d")
        self.gesture_lbl.pack(pady=6)
        
        self.bar_canvas = tk.Canvas(self.info_panel, width=200, height=6, bg="#2d2d38", bd=0, highlightthickness=0)
        self.bar_canvas.pack(pady=4)
        self.progress_bar = self.bar_canvas.create_rectangle(0, 0, 0, 6, fill="#8b5cf6", width=0)
        
        # 3. Toggle View Button (Arrow Button)
        self.toggle_btn = tk.Button(root, text="▼ Expand Camera Feed & Logs", font=("Inter", 8, "bold"), fg="#94a3b8", bg="#16161d", activeforeground="#f8fafc", activebackground="#8b5cf6", bd=0, padx=8, pady=4, cursor="hand2", command=self.toggle_expanded_view)
        self.toggle_btn.grid(row=2, column=0, pady=8)
        
        # 4. Expanded Area (hidden initially)
        self.exp_frame = tk.Frame(root, bg="#0c0c0e")
        
        # Video label inside expanded area
        self.video_container = tk.Frame(self.exp_frame, bg="#000", width=320, height=240)
        self.video_container.pack(side="left", padx=5, pady=5)
        self.video_label = tk.Label(self.video_container, bg="#000")
        self.video_label.pack()
        
        # Logs text inside expanded area
        log_frame = tk.Frame(self.exp_frame, bg="#0c0c0e")
        log_frame.pack(side="right", fill="both", expand=True, padx=5, pady=5)
        
        self.log_txt = scrolledtext.ScrolledText(log_frame, width=32, height=14, font=("Courier", 8), fg="#c084fc", bg="#121216", bd=1, relief="solid", insertbackground="white")
        self.log_txt.pack(fill="both", expand=True)
        self.log_txt.insert("1.0", "--- Vision Agent Logs ---\n")
        self.log_txt.configure(state="disabled")

    def append_log(self, text):
        self.log_txt.configure(state="normal")
        self.log_txt.insert("end", text + "\n")
        self.log_txt.see("end")
        self.log_txt.configure(state="disabled")

    def update_progress(self, progress):
        width = int((progress / 100.0) * 200)
        self.bar_canvas.coords(self.progress_bar, 0, 0, width, 6)

    def update_gesture_ui(self, name, progress):
        self.update_progress(progress)
        
        colors = {
            "fist": "#ef4444",
            "one_finger": "#10b981",
            "peace_sign": "#c084fc",
            "three_fingers": "#3b82f6",
            "four_fingers": "#f59e0b",
            "open_hand": "#38bdf8",
            "two_hands": "#f472b6",
            "none": "#f8fafc"
        }
        
        col = colors.get(name, "#f8fafc")
        disp = name.upper().replace("_", " ")
        self.gesture_lbl.configure(text=f"Gesture: {disp}", fg=col)
        self.bar_canvas.itemconfig(self.progress_bar, fill=col)

    def toggle_expanded_view(self):
        if self.is_expanded:
            # Collapse
            self.exp_frame.grid_forget()
            self.root.geometry("400x200")
            self.toggle_btn.configure(text="▼ Expand Camera Feed & Logs")
            self.is_expanded = False
        else:
            # Expand
            self.exp_frame.grid(row=3, column=0, sticky="nsew", padx=15, pady=5)
            self.root.geometry("700x480")
            self.toggle_btn.configure(text="▲ Collapse Camera & Logs")
            self.is_expanded = True

    # Show Gemini Result in Toplevel Modal
    def show_result_popup(self, title, content):
        popup = tk.Toplevel(self.root)
        popup.title(title)
        popup.geometry("600x450")
        popup.configure(bg="#121216")
        popup.transient(self.root)
        
        # Title Header
        title_lbl = tk.Label(popup, text=title, font=("Outfit", 12, "bold"), fg="#8b5cf6", bg="#121216", anchor="w")
        title_lbl.pack(fill="x", padx=15, pady=10)
        
        # Scrollable Content
        text_area = scrolledtext.ScrolledText(popup, font=("Inter", 9), fg="#f8fafc", bg="#181822", bd=0, highlightthickness=0)
        text_area.pack(fill="both", expand=True, padx=15, pady=5)
        text_area.insert("1.0", content)
        text_area.configure(state="disabled")
        
        # Close button
        btn_frame = tk.Frame(popup, bg="#121216")
        btn_frame.pack(fill="x", pady=10)
        close_btn = tk.Button(btn_frame, text="Close Report", font=("Inter", 9, "bold"), fg="#fff", bg="#8b5cf6", activeforeground="#fff", activebackground="#a78bfa", bd=0, padx=15, pady=6, cursor="hand2", command=popup.destroy)
        close_btn.pack(side="right", padx=15)

# Tkinter setup
root = tk.Tk()
app_ui = HandShiftUI(root)

# Global video capture reference
cap = cv2.VideoCapture(0)

def update_frame():
    global STABLE_GESTURE, HOLD_COUNT, LAST_TRIGGERED_GESTURE
    
    if not cap.isOpened():
        return
        
    ret, frame = cap.read()
    if not ret:
        root.after(30, update_frame)
        return
        
    # Mirror image
    frame = cv2.flip(frame, 1)
    h, w, c = frame.shape
    
    # Process with MediaPipe
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    results = hands.process(rgb)
    
    detected = "none"
    
    if results.multi_hand_landmarks:
        detected = classify_frame_gestures(results.multi_hand_landmarks)
        
        # Draw joints and neon lines
        for hand_landmarks in results.multi_hand_landmarks:
            for connection in mp_hands.HAND_CONNECTIONS:
                p1 = hand_landmarks.landmark[connection[0]]
                p2 = hand_landmarks.landmark[connection[1]]
                cv2.line(frame, (int(p1.x * w), int(p1.y * h)), (int(p2.x * w), int(p2.y * h)), (255, 255, 0), 2)
            for lm in hand_landmarks.landmark:
                cx, cy = int(lm.x * w), int(lm.y * h)
                cv2.circle(frame, (cx, cy), 5, (246, 92, 139), -1)
                cv2.circle(frame, (cx, cy), 2, (255, 255, 255), -1)
                
    # Stable holds / debouncing
    if detected == "none":
        STABLE_GESTURE = "none"
        LAST_TRIGGERED_GESTURE = "none"
        HOLD_COUNT = 0
        app_ui.update_gesture_ui("none", 0)
    else:
        if detected != STABLE_GESTURE:
            STABLE_GESTURE = detected
            HOLD_COUNT = 1
            app_ui.update_gesture_ui(detected, 0)
        else:
            HOLD_COUNT += 1
            progress = int((min(HOLD_COUNT, REQUIRED_HOLD_FRAMES) / REQUIRED_HOLD_FRAMES) * 100)
            app_ui.update_gesture_ui(detected, progress)
            
            if HOLD_COUNT >= REQUIRED_HOLD_FRAMES and LAST_TRIGGERED_GESTURE != STABLE_GESTURE:
                LAST_TRIGGERED_GESTURE = STABLE_GESTURE
                
                # Ingest & Execute Action
                ingest_to_afferens(STABLE_GESTURE)
                execute_gesture_action(STABLE_GESTURE)
                
    # Display in GUI if expanded
    if app_ui.is_expanded:
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(frame_rgb)
        img = img.resize((320, 240))
        imgtk = ImageTk.PhotoImage(image=img)
        app_ui.video_label.imgtk = imgtk
        app_ui.video_label.configure(image=imgtk)
        
    root.after(30, update_frame)

def on_close():
    cap.release()
    root.destroy()

def main():
    load_env()
    load_afferens_config()
    init_session_log()
    
    if not cap.isOpened():
        messagebox.showerror("Camera Error", "Webcam could not be opened. Please verify video device connections.")
        sys.exit(1)
        
    app_ui.append_log("[SYSTEM] HandShift Vision Agent Ready.")
    if GEMINI_API_KEY:
        app_ui.append_log("[SYSTEM] Gemini API loaded from .env")
    else:
        app_ui.append_log("[WARNING] GEMINI_API_KEY is missing in .env")
        
    root.protocol("WM_DELETE_WINDOW", on_close)
    root.after(30, update_frame)
    root.mainloop()

if __name__ == "__main__":
    main()
