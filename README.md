# M5Stack Fire Presentation Timer

Stage cue timer for the **M5Stack Fire IoT Kit** running **UIFlow 1.x** MicroPython. The 2.0″ LCD shows remaining time inside a shrinking ring, the Fire’s side RGB bars follow green / yellow / red phases, and a phone on the device’s own Wi-Fi can set the three interval times.

Firmware lives in `main.py`. Load it as the UIFlow 1.x main program (see below). This script is **not** written for UIFlow 2.x.

## Hardware and firmware

| | |
| --- | --- |
| **Kit** | [M5Stack Fire IoT Kit](https://docs.m5stack.com/en/core/fire) (M5Stack Fire core + M5GO charging base) |
| **SoC** | ESP32 |
| **Display** | 2.0″ ILI9342C, 320×240 |
| **Inputs** | Front buttons A, B, and C |
| **LEDs** | 10× SK6812 RGB on the M5GO base (two side strips of 5) |
| **Runtime** | UIFlow **1.x** MicroPython (`m5stack`, `m5ui`, `uiflow`) |

UIFlow 1.x APIs this script depends on include `setScreenColor`, `lcd.arc` / `lcd.rect` / `lcd.print`, `rgb.setColorAll` / `rgb.setBrightness`, `btnA.wasPressed` (and B/C), and `wait_ms`.

### Load on UIFlow 1.x

1. Install **UIFlow 1.x** firmware with M5Burner (Fire / M5GO profile), not UIFlow 2.
2. Open **UIFlow Desktop IDE 1.x** (or the 1.x web IDE), connect the Fire, and switch to Python mode.
3. Paste or open `main.py` and run it, or save it as the device’s main program so it starts on boot.

The Fire’s AP uses the ESP32 soft-AP (`network.WLAN(network.AP_IF)`), typically at `192.168.4.1`.

## Network (AP only)

On boot the device starts its own access point. It does not join another Wi-Fi network.

| | |
| --- | --- |
| **SSID** | `M5-Timer` |
| **Password** | `12345678` |
| **Setup page** | `http://192.168.4.1` (or the IP shown on the Wi-Fi screen) |

### Connect

1. Power on the Fire.
2. Join `M5-Timer` from a phone, tablet, or laptop.
3. Press **C** on the device to show SSID, password, and URL, then open that URL.

## Buttons

| Button | Action |
| --- | --- |
| **A** | Restart: elapsed time back to 0, timer paused |
| **B** | Start / pause. If the countdown already hit 00:00, B also resets elapsed time, then starts or pauses |
| **C** | Toggle the Wi-Fi setup screen and the timer screen |

Bottom-of-screen labels track those actions (`Restart`, `Start`/`Pause`, `Wi-Fi`/`Timer`).

## Timing phases

Thresholds are **cumulative minutes from the start**, not phase lengths.

| Elapsed time | LCD / RGB |
| --- | --- |
| `0` → green end | Green background, green LEDs, white ring and text |
| green end → yellow end | Yellow background, amber LEDs, black ring and text |
| yellow end → total time | Red background, red LEDs, white ring and text |

Defaults: green until **5 min**, yellow until **7 min**, red until **9 min** (total talk length).

The ring starts full and shrinks toward 0° as remaining time drops. The big digits are remaining `MM:SS`. When remaining time is 00:00 and the timer is still running, all ten side RGBs blink red / off.

The web form enforces `green < yellow < red` (each step at least 0.1 min). Saving from the browser applies the new values and **restarts** the timer (paused at 00 remaining of the new total).

## Display notes

- Timer view: colored full-screen background, circular remaining-time arc, countdown, `RUNNING` / `PAUSED` / `TIME UP`.
- Wi-Fi view: SSID, password, `http://<ip>`, and the current G / Y / R schedule. The Fire’s side RGBs still follow the timer while this screen is open.
- Redraws are incremental so the LCD does not full-refresh every frame.

## Web setup page

`GET /` with query params:

- `g` — minutes when green ends / yellow starts
- `y` — minutes when yellow ends / red starts
- `r` — total minutes (red ends)

Example: `http://192.168.4.1/?g=5&y=8&r=10`

The page also shows RUNNING/PAUSED and remaining time at the moment you load it. It does not auto-refresh.

## Runtime loop

The main loop (about every 20 ms) advances elapsed time while running, updates LCD/RGB, and accepts one HTTP client without blocking the countdown.
