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
import random
import requests
import tkinter as tk
from tkinter import scrolledtext, messagebox
from PIL import Image, ImageTk, ImageGrab
from google import genai
import threading
import re
from pathlib import Path
import pyautogui


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
    global GEMINI_API_KEY, AFFERENS_API_KEY, gemini_client
    if os.path.exists(".env"):
        try:
            with open(".env", "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        if k.strip() == "GEMINI_API_KEY":
                            GEMINI_API_KEY = v.strip()
                        elif k.strip() == "AFFERENS_API_KEY":
                            AFFERENS_API_KEY = v.strip()
        except Exception as e:
            print(f"Failed to load .env: {e}")

    # Initialize Gemini SDK client
    if GEMINI_API_KEY:
        try:
            gemini_client = genai.Client(api_key=GEMINI_API_KEY)
            print("[SYSTEM] Gemini SDK client initialized (gemini-3.1-flash-lite-preview)")
        except Exception as e:
            print(f"[SYSTEM] Failed to initialize Gemini client: {e}")

# Load Afferens Configuration
def load_afferens_config():
    global AFFERENS_API_KEY, CONVERSATION_DIR
    try:
        home = Path.home()
        # Resolve active conversation ID. (AFFERENS_API_KEY is loaded exclusively from .env/environment).
        brain_path = home / ".gemini" / "antigravity-ide" / "brain"
        if brain_path.exists():
            subdirs = [d for d in brain_path.iterdir() if d.is_dir()]
            if subdirs:
                subdirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                CONVERSATION_DIR = str(subdirs[0])
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
            model="gemini-3.1-flash-lite-preview",
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

def run_async_action(title, action_func, *args, **kwargs):
    """Helper to run a heavy operation in a background thread and show a loading state popup."""
    # Instantiates the result popup immediately with a loading state
    loading_msg = "⏳ Thinking... Please wait while the HandShift agent processes your request..."
    popup, title_lbl, text_area = app_ui.show_result_popup(title, loading_msg)
    
    def worker():
        try:
            result = action_func(*args, **kwargs)
            if not result:
                result = "No response received."
        except Exception as e:
            result = f"Error during execution:\n{e}"
            
        def update_ui():
            if popup.winfo_exists():
                cleaned = app_ui.clean_markdown_text(result)
                text_area.configure(state="normal")
                text_area.delete("1.0", "end")
                text_area.insert("1.0", cleaned)
                text_area.configure(state="disabled")
        
        root.after(0, update_ui)
        
    threading.Thread(target=worker, daemon=True).start()

# ✊ Fist (0 fingers): Summarize Current File
def action_fist():
    log_session_event("fist", "Summarize Current File")
    
    def _perform():
        workspace_root = Path("c:/JMT/vision_view")
        if not workspace_root.exists():
            workspace_root = Path(".")
        valid_exts = (".js", ".py", ".json", ".html", ".css")

        newest_file = None
        newest_mtime = 0

        if not workspace_root.exists():
            return f"Workspace path not found: {workspace_root}"

        for file_path in workspace_root.rglob("*"):
            if any(exclude in file_path.parts for exclude in (".git", "node_modules", "__pycache__")):
                continue
            if file_path.is_file() and file_path.suffix in valid_exts and file_path.name != "vision_agent.py" and not file_path.name.startswith(".env"):
                try:
                    mtime = file_path.stat().st_mtime
                    if mtime > newest_mtime:
                        newest_mtime = mtime
                        newest_file = file_path
                except Exception:
                    continue

        if not newest_file:
            return "No active files found to summarize in workspace."

        try:
            with open(newest_file, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

            prompt = (
                f"Summarize the purpose, functions, structure, and any TODOs in this code file in clean, concise, plain English.\n"
                f"Do not use markdown bolding (**) or headers (#). Use plain lists and sections instead.\n\n"
                f"File: {newest_file.name}\n\nContent:\n{content[:8000]}"
            )
            summary = call_gemini_api(prompt)
            return f"File Summarized: {newest_file.name}\n\n{summary}"
        except Exception as e:
            return f"Error reading or summarizing file: {e}"
            
    run_async_action("Summarize File", _perform)

# ☝️ One Finger (1 finger): Explain Last Error
def action_one_finger():
    log_session_event("one_finger", "Explain Last Error")
    
    def _perform():
        if not CONVERSATION_DIR:
            return "Error: Conversation task log directory could not be resolved."
            
        tasks_dir = Path(CONVERSATION_DIR) / ".system_generated" / "tasks"
        if not tasks_dir.exists():
            return "No task error logs exist yet."
            
        log_files = list(tasks_dir.glob("*.log"))
        if not log_files:
            return "No log output found."
            
        log_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        latest_log = log_files[0]

        try:
            with open(latest_log, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            log_snippet = "".join(lines[-40:])

            prompt = (
                f"Explain this command error trace in plain English, and provide a clear suggested fix.\n"
                f"Do not use markdown formatting like asterisks or headers.\n\n{log_snippet}"
            )
            return call_gemini_api(prompt)
        except Exception as e:
            return f"Failed to parse error: {e}"
            
    run_async_action("Explain Last Error", _perform)

# ✌️ Peace Sign (2 fingers): AI Search from clipboard
def action_peace_sign(clipboard_text):
    log_session_event("peace_sign", "AI Search from Clipboard")
    if not clipboard_text:
        app_ui.show_result_popup("AI Search", "Clipboard is empty. Copy something first!")
        return

    def _perform():
        prompt = (
            f"The user wants an AI-powered answer for this query. Give a clear, concise, and helpful response.\n"
            f"Do not use markdown bolding or headers.\n\n{clipboard_text}"
        )
        return call_gemini_api(prompt)
        
    run_async_action(f"AI Search: {clipboard_text[:30]}...", _perform)

# 🤟 Three Fingers (3 fingers): Take Screenshot, Copy to Clipboard, Open Gemini & Paste
def action_three_fingers():
    log_session_event("three_fingers", "Take Screenshot & Paste to Gemini")
    
    try:
        screenshot = ImageGrab.grab()
        # Save to current workspace absolute path
        img_path = Path("screenshot.png").resolve()
        screenshot.save(img_path)

        # Copy image to clipboard natively depending on OS
        if sys.platform == "win32":
            powershell_cmd = f"Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.Clipboard]::SetImage([System.Drawing.Image]::FromFile('{img_path}'))"
            subprocess.run(["powershell", "-Command", powershell_cmd], check=True)
        elif sys.platform == "darwin":
            osascript_cmd = f"set the clipboard to (read (POSIX file \"{img_path}\") as «class PNGf»)"
            subprocess.run(["osascript", "-e", osascript_cmd], check=True)
        
        webbrowser.open("https://gemini.google.com")
        
        def paste_worker():
            # Wait for browser window and page load to focus the input area
            time.sleep(5.0)
            try:

                # Paste the copied screenshot image
                if sys.platform == "darwin":
                    pyautogui.hotkey("command", "v")
                else:
                    pyautogui.hotkey("ctrl", "v")
                
                # Wait for the paste/upload to start processing
                time.sleep(3.0)
                
                # Write the prompt text
                pyautogui.write("analyze and explain this image")
                time.sleep(2.0)
                pyautogui.press('enter')
            except Exception as e:
                print(f"Failed to paste screenshot or write prompt: {e}")
                
        threading.Thread(target=paste_worker, daemon=True).start()
        app_ui.show_result_popup("Gemini Screenshot Triggered", "Captured screenshot and copied it to your clipboard.\n\nOpening Gemini Web to paste and analyze the image...")
        
    except Exception as e:
        app_ui.show_result_popup("Screenshot Error", f"Failed to capture or copy screenshot: {e}")


# 🤘 Four Fingers (4 fingers): Git Add + Commit + Push
def action_four_fingers():
    log_session_event("four_fingers", "Git Add + Commit + Push")
    
    def _perform():
        workspace = Path("c:/JMT/vision_view")
        if not workspace.exists():
            workspace = Path(".")
        commit_id = str(random.randint(1000, 9999))

        commit_msg = f"handshift-{commit_id}"
        results = []
        
        try:
            # git add .
            add_res = subprocess.run(["git", "add", "."], capture_output=True, text=True, cwd=workspace, check=True)
            results.append(f"$ git add .\n{add_res.stdout}{add_res.stderr}".strip())

            # git commit -m "handshift-XXXX"
            commit_res = subprocess.run(["git", "commit", "-m", commit_msg], capture_output=True, text=True, cwd=workspace, check=True)
            results.append(f"$ git commit -m \"{commit_msg}\"\n{commit_res.stdout}{commit_res.stderr}".strip())

            # git push
            push_res = subprocess.run(["git", "push"], capture_output=True, text=True, cwd=workspace, timeout=20, check=True)
            results.append(f"$ git push\n{push_res.stdout}{push_res.stderr}".strip())
            
            results.append("\n✅ Push successfully completed!")
        except subprocess.CalledProcessError as e:
            results.append(f"Command failed: {e.cmd}\nReturn code: {e.returncode}\n{e.stderr}")
        except subprocess.TimeoutExpired:
            results.append("⚠️ git push timed out. Check your remote network configuration.")
        except Exception as e:
            results.append(f"Unexpected error: {e}")
            
        return "\n\n".join(results)
        
    run_async_action("Git Auto Commit & Push", _perform)

# ✋ Open Hand (5 fingers): Quick Google Search from clipboard
def action_open_hand(clipboard_text):
    log_session_event("open_hand", "Quick Google Search")
    if not clipboard_text:
        clipboard_text = "HandShift gesture agent"
    url = f"https://www.google.com/search?q={urllib.parse.quote(clipboard_text)}"
    webbrowser.open(url)
    app_ui.show_result_popup("Google Search Triggered", f"Searching Google for:\n\n'{clipboard_text}'")

# 🤙 Two Hands (Both hands): Gemini Open and Paste Clipboard
def action_two_hands():
    log_session_event("two_hands", "Gemini Open & Paste Clipboard")
    
    # Retrieve current clipboard content
    clipboard = ""
    try:
        clipboard = app_ui.root.clipboard_get()
    except Exception:
        pass

    webbrowser.open("https://gemini.google.com")
    
    def paste_worker():
        # Wait for browser window and page load to focus the input field
        time.sleep(5.0)
        try:

            # Paste the current clipboard content using PyAutoGUI (check for macOS cmd key)
            if sys.platform == "darwin":
                pyautogui.hotkey("command", "v")
            else:
                pyautogui.hotkey("ctrl", "v")
        except Exception as e:
            print(f"Failed to paste clipboard content: {e}")


    threading.Thread(target=paste_worker, daemon=True).start()
    app_ui.show_result_popup("Gemini Paste Triggered", "Opened Gemini in your browser.\n\nAttempting to paste the clipboard contents into the chat input area.")


def wake_up():
    """Resume from sleep mode."""
    app_ui.is_sleeping = False
    app_ui.gesture_lbl.configure(text="Gesture: NONE", fg="#f8fafc")
    app_ui.status_label.configure(text="Agent Running")
    app_ui.status_dot.configure(fg="#10b981")
    app_ui.append_log(f"[{datetime.now().strftime('%H:%M:%S')}] [SYSTEM] Woke up from sleep mode")

# Coordinator
def execute_gesture_action(gesture):
    global LAST_TRIGGERED_GESTURE

    clipboard = ""
    try:
        clipboard = app_ui.root.clipboard_get()
    except Exception:
        pass

    if gesture == "fist":
        action_fist()
    elif gesture == "one_finger":
        action_one_finger()
    elif gesture == "peace_sign":
        action_peace_sign(clipboard)
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
        self.root.geometry("720x280") # Start in compact mode with side-by-side layout
        self.root.resizable(False, False)
        
        self.is_expanded = False
        self.is_sleeping = False
        
        # Configure Grid weight
        self.root.columnconfigure(0, weight=3)
        self.root.columnconfigure(1, weight=2)
        
        # --- Left Pane (Controls and Status) ---
        left_pane = tk.Frame(root, bg="#0c0c0e")
        left_pane.grid(row=0, column=0, sticky="nsew", padx=15, pady=10)
        
        # 1. Header Frame inside Left Pane
        header = tk.Frame(left_pane, bg="#0c0c0e", height=40)
        header.pack(fill="x", pady=4)
        
        brand_label = tk.Label(header, text="HandShift", font=("Outfit", 14, "bold"), fg="#8b5cf6", bg="#0c0c0e")
        brand_label.pack(side="left")
        
        # Status dot
        self.status_dot = tk.Label(header, text="●", font=("Arial", 12), fg="#10b981", bg="#0c0c0e")
        self.status_dot.pack(side="right", padx=5)
        
        self.status_label = tk.Label(header, text="Agent Running", font=("Inter", 9), fg="#94a3b8", bg="#0c0c0e")
        self.status_label.pack(side="right")
        
        # 2. Compact Info Panel inside Left Pane
        self.info_panel = tk.Frame(left_pane, bg="#16161d", bd=1, relief="solid")
        self.info_panel.pack(fill="x", pady=5)
        
        self.gesture_lbl = tk.Label(self.info_panel, text="Gesture: NONE", font=("Outfit", 12, "bold"), fg="#f8fafc", bg="#16161d")
        self.gesture_lbl.pack(pady=6)
        
        self.bar_canvas = tk.Canvas(self.info_panel, width=200, height=6, bg="#2d2d38", bd=0, highlightthickness=0)
        self.bar_canvas.pack(pady=4)
        self.progress_bar = self.bar_canvas.create_rectangle(0, 0, 0, 6, fill="#8b5cf6", width=0)
        
        # 3. Toggle View Button (Arrow Button) inside Left Pane
        self.toggle_btn = tk.Button(left_pane, text="▼ Expand Camera Feed & Logs", font=("Inter", 8, "bold"), fg="#94a3b8", bg="#16161d", activeforeground="#f8fafc", activebackground="#8b5cf6", bd=0, padx=8, pady=4, cursor="hand2", command=self.toggle_expanded_view)
        self.toggle_btn.pack(pady=6)
        
        # --- Right Pane (Gesture Legend Table Box) ---
        right_pane = tk.LabelFrame(root, text=" GESTURE GUIDE ", font=("Outfit", 10, "bold"), fg="#8b5cf6", bg="#121216", bd=1, relief="solid", padx=10, pady=5)
        right_pane.grid(row=0, column=1, sticky="nsew", padx=15, pady=15)
        
        guide_items = [
            ("✊ Fist (0)", "Summarize active workspace file"),
            ("☝️ 1 Finger", "Explain last terminal command error"),
            ("✌️ Peace (2)", "AI Search query using clipboard text"),
            ("🤟 3 Fingers", "Copy screenshot & paste to Gemini"),
            ("🤘 4 Fingers", "Git add, commit & push changes"),
            ("✋ Open (5)", "Quick Google search from clipboard"),
            ("👐 2 Hands", "Open Gemini Web & paste clipboard")
        ]
        
        for idx, (gesture_name, action_name) in enumerate(guide_items):
            lbl_gest = tk.Label(right_pane, text=gesture_name, font=("Inter", 9, "bold"), fg="#a78bfa", bg="#121216", anchor="w")
            lbl_gest.grid(row=idx, column=0, sticky="w", padx=4, pady=1)
            
            lbl_sep = tk.Label(right_pane, text="→", font=("Inter", 9), fg="#4b5563", bg="#121216")
            lbl_sep.grid(row=idx, column=1, padx=4, pady=1)
            
            lbl_act = tk.Label(right_pane, text=action_name, font=("Inter", 9), fg="#e2e8f0", bg="#121216", anchor="w")
            lbl_act.grid(row=idx, column=2, sticky="w", padx=4, pady=1)
        
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
            self.root.geometry("720x280")
            self.toggle_btn.configure(text="▼ Expand Camera Feed & Logs")
            self.is_expanded = False
        else:
            # Expand
            self.exp_frame.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=15, pady=5)
            self.root.geometry("820x560")
            self.toggle_btn.configure(text="▲ Collapse Camera & Logs")
            self.is_expanded = True

    # Show Gemini Result in Toplevel Modal
    def show_result_popup(self, title, content):
        # Programmatically strip markdown formatting
        cleaned_content = self.clean_markdown_text(content)
        
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
        text_area.insert("1.0", cleaned_content)
        text_area.configure(state="disabled")
        
        # Close button
        btn_frame = tk.Frame(popup, bg="#121216")
        btn_frame.pack(fill="x", pady=10)
        close_btn = tk.Button(btn_frame, text="Close Report", font=("Inter", 9, "bold"), fg="#fff", bg="#8b5cf6", activeforeground="#fff", activebackground="#a78bfa", bd=0, padx=15, pady=6, cursor="hand2", command=popup.destroy)
        close_btn.pack(side="right", padx=15)
        
        return popup, title_lbl, text_area

    def clean_markdown_text(self, text):
        if not text:
            return ""
        # Remove bold/italic markers
        text = re.sub(r'\*+', '', text)
        # Remove header markers (#)
        text = re.sub(r'^#+\s*', '', text, flags=re.MULTILINE)
        # Remove code blocks and single backticks
        text = text.replace('```', '').replace('`', '')
        return text.strip()

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
                
    # If sleeping, only watch for two_hands wake-up gesture
    if app_ui.is_sleeping:
        if detected == "two_hands":
            if detected != STABLE_GESTURE:
                STABLE_GESTURE = detected
                HOLD_COUNT = 1
            else:
                HOLD_COUNT += 1
                if HOLD_COUNT >= REQUIRED_HOLD_FRAMES and LAST_TRIGGERED_GESTURE != "two_hands":
                    LAST_TRIGGERED_GESTURE = "two_hands"
                    wake_up()
        else:
            STABLE_GESTURE = "none"
            HOLD_COUNT = 0
    else:
        # Normal gesture processing
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
