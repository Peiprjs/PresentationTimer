import math
from m5stack import *
from m5ui import *
import network
import socket
import time
from uiflow import *

# ==============================================================================
# 1. CONFIGURATION & STATE
# ==============================================================================
AP_SSID = "M5-Timer"
AP_PASS = "12345678"  # Minimum 8 characters for WPA2

# Default cumulative thresholds in minutes:
# 0 -> t_green_min  : GREEN phase
# t_green -> t_yellow: YELLOW phase
# t_yellow -> t_red  : RED phase (t_red_min is Total Presentation Time)
t_green_min = 5.0
t_yellow_min = 7.0
t_red_min = 9.0

# Colors (24-bit RGB hex)
COLOR_GREEN_LED = 0x00FF00
COLOR_YELLOW_LED = 0xFFAA00
COLOR_RED_LED = 0xFF0000
COLOR_OFF_LED = 0x000000

COLOR_GREEN_BG = 0x009933
COLOR_YELLOW_BG = 0xE6A800
COLOR_RED_BG = 0xCC0000
COLOR_INFO_BG = 0x1A1A2E

# Timer runtime state
is_running = False
showing_info = False
elapsed_ms = 0
last_tick_ms = 0

# Screen redraw tracking to avoid LCD flicker
current_bg_color = None
last_drawn_sec = -1
last_drawn_angle = -1
needs_full_redraw = True

# Circle geometry (320x240 display)
CX = 160
CY = 105
RADIUS = 78
THICKNESS = 10

# ==============================================================================
# 2. WI-FI ACCESS POINT & NON-BLOCKING WEB SERVER
# ==============================================================================
ap = network.WLAN(network.AP_IF)
ap.active(True)
ap.config(essid=AP_SSID, password=AP_PASS, authmode=network.AUTH_WPA_WPA2_PSK)

while not ap.active():
  wait_ms(50)

ip_addr = ap.ifconfig()[0]

server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server_sock.bind(("0.0.0.0", 80))
server_sock.listen(3)
server_sock.setblocking(False)


def build_html_page(message=""):
  total_sec = int(t_red_min * 60)
  rem_sec = max(0, total_sec - int(elapsed_ms // 1000))
  mins, secs = divmod(rem_sec, 60)
  status_str = "RUNNING" if is_running else "PAUSED"
  msg_block = (
      '<p style="color:#4cd137;font-weight:bold;">' + message + "</p>"
      if message
      else ""
  )

  html = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>M5Stack Presentation Timer</title>
  <style>
    body {{ font-family: sans-serif; background: #121212; color: #fff; text-align: center; padding: 16px; }}
    .card {{ max-width: 380px; margin: 0 auto; background: #1e1e2e; padding: 20px; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.5); }}
    h2 {{ margin-top: 0; }}
    .status {{ font-size: 1.4rem; margin: 12px 0; padding: 10px; background: #2a2a3c; border-radius: 8px; }}
    label {{ display: block; text-align: left; margin-top: 12px; font-size: 0.9rem; color: #ccc; }}
    input[type="number"] {{ width: 100%; padding: 10px; margin-top: 4px; border-radius: 6px; border: 1px solid #444; background: #121212; color: #fff; font-size: 1rem; box-sizing: border-box; }}
    button {{ width: 100%; margin-top: 18px; padding: 12px; background: #0099ff; color: #fff; border: none; border-radius: 8px; font-size: 1rem; font-weight: bold; cursor: pointer; }}
    .dot {{ display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 6px; }}
  </style>
</head>
<body>
  <div class="card">
    <h2>Presentation Timer</h2>
    <div class="status">{status}: <strong>{mm:02d}:{ss:02d}</strong></div>
    {msg}
    <form action="/" method="GET">
      <label><span class="dot" style="background:#00ff00;"></span>Green Ends / Yellow Starts (min):</label>
      <input type="number" step="0.1" min="0.1" name="g" value="{g}" required>

      <label><span class="dot" style="background:#ffaa00;"></span>Yellow Ends / Red Starts (min):</label>
      <input type="number" step="0.1" min="0.2" name="y" value="{y}" required>

      <label><span class="dot" style="background:#ff0000;"></span>Total Time / Red Ends (min):</label>
      <input type="number" step="0.1" min="0.3" name="r" value="{r}" required>

      <button type="submit">Save &amp; Restart Timer</button>
    </form>
  </div>
</body>
</html>""".format(
      status=status_str,
      mm=mins,
      ss=secs,
      msg=msg_block,
      g=t_green_min,
      y=t_yellow_min,
      r=t_red_min,
  )
  return html


def parse_query_params(request_str):
  global t_green_min, t_yellow_min, t_red_min
  try:
    first_line = request_str.split("\r\n")[0]
    parts = first_line.split(" ")
    if len(parts) < 2:
      return ""
    path = parts[1]
    if "?" not in path:
      return ""
    query = path.split("?", 1)[1]
    params = {}
    for pair in query.split("&"):
      if "=" in pair:
        k, v = pair.split("=", 1)
        params[k] = float(v)
    if "g" in params and "y" in params and "r" in params:
      g_val = max(0.1, params["g"])
      y_val = max(g_val + 0.1, params["y"])
      r_val = max(y_val + 0.1, params["r"])
      t_green_min = round(g_val, 2)
      t_yellow_min = round(y_val, 2)
      t_red_min = round(r_val, 2)
      restart_timer()
      return "Intervals updated & timer reset!"
  except Exception:
    return "Invalid input values."
  return ""


def poll_web_server():
  try:
    conn, addr = server_sock.accept()
  except OSError:
    return

  try:
    conn.settimeout(0.5)
    req = conn.recv(1024).decode("utf-8", "ignore")
    msg = ""
    if req.startswith("GET /"):
      msg = parse_query_params(req)
    body = build_html_page(msg)
    response = (
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: text/html; charset=utf-8\r\n"
        "Connection: close\r\n\r\n" + body
    )
    conn.sendall(response.encode("utf-8"))
  except Exception:
    pass
  finally:
    conn.close()


# ==============================================================================
# 3. TIMER & DISPLAY LOGIC
# ==============================================================================
def get_phase_colors(elapsed_sec):
  green_limit = t_green_min * 60.0
  yellow_limit = t_yellow_min * 60.0

  if elapsed_sec < green_limit:
    # Green Phase: White text/ring on Green background
    return COLOR_GREEN_BG, COLOR_GREEN_LED, 0xFFFFFF, 0x00551C
  elif elapsed_sec < yellow_limit:
    # Yellow Phase: Black text/ring for high contrast on Yellow background
    return COLOR_YELLOW_BG, COLOR_YELLOW_LED, 0x000000, 0x997000
  else:
    # Red Phase: White text/ring on Red background
    return COLOR_RED_BG, COLOR_RED_LED, 0xFFFFFF, 0x660000


def draw_button_bar(fg_color, bg_color):
  lcd.font(lcd.FONT_DejaVu18)
  lcd.setTextColor(fg_color, bg_color)
  lcd.print("Restart", 30, 214)
  mid_label = "Pause" if is_running else "Start"
  lcd.print(mid_label, 134, 214)
  right_label = "Timer" if showing_info else "Wi-Fi"
  lcd.print(right_label, 240, 214)


def draw_info_screen():
  global current_bg_color
  setScreenColor(COLOR_INFO_BG)
  current_bg_color = COLOR_INFO_BG

  lcd.font(lcd.FONT_DejaVu18)
  lcd.setTextColor(0x00D2FF, COLOR_INFO_BG)
  lcd.print("HTML Timer Setup", lcd.CENTER, 14)

  lcd.setTextColor(0xFFFFFF, COLOR_INFO_BG)
  lcd.print("1. Connect to Wi-Fi:", 20, 48)
  lcd.print("   SSID: " + AP_SSID, 20, 72)
  lcd.print("   PASS: " + AP_PASS, 20, 96)

  lcd.print("2. Open in Browser:", 20, 128)
  lcd.setTextColor(0x4CD137, COLOR_INFO_BG)
  lcd.print("   http://" + ip_addr, 20, 152)

  lcd.setTextColor(0xCCCCCC, COLOR_INFO_BG)
  sched = "G:{}m | Y:{}m | R:{}m".format(t_green_min, t_yellow_min, t_red_min)
  lcd.print(sched, lcd.CENTER, 184)

  draw_button_bar(0xFFFFFF, COLOR_INFO_BG)


def update_outputs(force=False):
  global current_bg_color, last_drawn_sec, last_drawn_angle, needs_full_redraw

  total_sec = max(1, int(round(t_red_min * 60.0)))
  elapsed_sec = elapsed_ms / 1000.0
  rem_sec = max(0, int(math.ceil(total_sec - elapsed_sec)))

  bg_color, led_color, fg_color, track_color = get_phase_colors(elapsed_sec)

  # Blink side RGBs when time reaches 00:00
  if rem_sec == 0 and is_running:
    if (int(elapsed_ms // 400) % 2) == 0:
      rgb.setColorAll(COLOR_RED_LED)
    else:
      rgb.setColorAll(COLOR_OFF_LED)
  else:
    rgb.setColorAll(led_color)

  # If viewing the HTML info screen, keep RGBs updated but don't overwrite LCD
  if showing_info:
    return

  # Full redraw only on phase color change or screen switch to prevent flicker
  if force or needs_full_redraw or (bg_color != current_bg_color):
    setScreenColor(bg_color)
    current_bg_color = bg_color
    lcd.arc(CX, CY, RADIUS, THICKNESS, 0, 360, fg_color, fg_color)
    draw_button_bar(fg_color, bg_color)
    last_drawn_sec = -1
    last_drawn_angle = 360
    needs_full_redraw = False

  # Calculate countdown angle (360 -> 0 degrees)
  progress = max(0.0, min(1.0, (total_sec - elapsed_sec) / float(total_sec)))
  rem_angle = int(round(360.0 * progress))

  if rem_angle != last_drawn_angle:
    if rem_angle < 360:
      # Overwrite elapsed segment with dimmed track color
      lcd.arc(
          CX, CY, RADIUS, THICKNESS, rem_angle, 360, track_color, track_color
      )
    if rem_angle > 0:
      # Ensure remaining segment stays crisp
      lcd.arc(CX, CY, RADIUS, THICKNESS, 0, rem_angle, fg_color, fg_color)
    last_drawn_angle = rem_angle

  # Redraw MM:SS only when the second ticks
  if rem_sec != last_drawn_sec:
    mins, secs = divmod(rem_sec, 60)
    time_str = "{:02d}:{:02d}".format(mins, secs)

    # Clear text box area inside the circle before printing
    lcd.rect(CX - 54, CY - 24, 108, 48, bg_color, bg_color)
    lcd.font(lcd.FONT_DejaVu40)
    lcd.setTextColor(fg_color, bg_color)
    lcd.print(time_str, lcd.CENTER, CY - 18)

    # Status subtitle inside the ring
    lcd.rect(CX - 42, CY + 24, 84, 20, bg_color, bg_color)
    lcd.font(lcd.FONT_DejaVu18)
    state_txt = (
        "TIME UP" if rem_sec == 0 else ("RUNNING" if is_running else "PAUSED")
    )
    lcd.print(state_txt, lcd.CENTER, CY + 24)

    last_drawn_sec = rem_sec


# ==============================================================================
# 4. BUTTON HANDLERS (A = Restart, B = Start/Pause, C = HTML Info)
# ==============================================================================
def restart_timer():
  global is_running, elapsed_ms, needs_full_redraw
  is_running = False
  elapsed_ms = 0
  needs_full_redraw = True
  if showing_info:
    draw_info_screen()
  else:
    update_outputs(force=True)


def buttonA_wasPressed():
  restart_timer()


btnA.wasPressed(buttonA_wasPressed)


def buttonB_wasPressed():
  global is_running, last_tick_ms, needs_full_redraw
  total_ms = int(t_red_min * 60000)
  if elapsed_ms >= total_ms:
    elapsed_ms = 0
  is_running = not is_running
  last_tick_ms = time.ticks_ms()
  needs_full_redraw = True
  if showing_info:
    draw_info_screen()
  else:
    update_outputs(force=True)


btnB.wasPressed(buttonB_wasPressed)


def buttonC_wasPressed():
  global showing_info, needs_full_redraw
  showing_info = not showing_info
  if showing_info:
    draw_info_screen()
  else:
    needs_full_redraw = True
    update_outputs(force=True)


btnC.wasPressed(buttonC_wasPressed)

# ==============================================================================
# 5. INITIALIZATION & MAIN LOOP
# ==============================================================================
rgb.setBrightness(40)
restart_timer()

while True:
  now = time.ticks_ms()
  if is_running:
    dt = time.ticks_diff(now, last_tick_ms)
    last_tick_ms = now
    total_ms = int(t_red_min * 60000)
    if elapsed_ms < total_ms:
      elapsed_ms = min(total_ms, elapsed_ms + dt)
  else:
    last_tick_ms = now

  update_outputs()
  poll_web_server()
  wait_ms(20)