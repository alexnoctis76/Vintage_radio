# Vintage Radio – RP2040 + DFPlayer Setup

This guide covers setting up the Vintage Radio application on a **Raspberry Pi Pico** (or Pico W) with a **DFPlayer Mini** module.

## What You Need

- **Raspberry Pi Pico** (or Pico W)
- **DFPlayer Mini** module (MP3 playback from SD card)
- **SD card** for music (formatted FAT32)
- Wiring (see Pinout below)
- **MicroPython** on the Pico (one-time install)
- **Vintage Radio desktop app** (to prepare library and optionally install to Pico)

## Prerequisites: Install MicroPython (One-Time)

The Pico must run **MicroPython** before it can execute the Vintage Radio Python code. You only need to do this once.

**Option A – Thonny**

1. Install [Thonny](https://thonny.org/).
2. Connect the Pico via USB.
3. In Thonny: **Tools → Options → Interpreter** → choose **MicroPython (Raspberry Pi Pico)**.
4. If the Pico has no MicroPython yet, Thonny will prompt to install it; confirm and wait for it to finish.

**Option B – Raspberry Pi Imager**

1. Install [Raspberry Pi Imager](https://www.raspberrypi.com/software/).
2. Run it, then **Choose OS → Other specific-purpose OS → MicroPython** and pick the **Raspberry Pi Pico** variant.
3. Choose your Pico’s drive (hold BOOTSEL on the Pico when plugging in USB to expose the drive).
4. Write the image; when done, the Pico will reboot with MicroPython.

After this step, you do **not** need Thonny or Imager for normal use; you can install and update the Vintage Radio application from the desktop app (see “Installing the application” below).

## Pinout / Connections

Pins are defined in `components/dfplayer_hardware.py`. Wire as follows (GPIO numbers are for the Pico):

| Pico GPIO | Use            | Notes                          |
|-----------|----------------|--------------------------------|
| 0         | UART TX        | To DFPlayer RX                 |
| 1         | UART RX        | To DFPlayer TX                 |
| 2         | Button         | Active low (pull-up)           |
| 3         | AM audio PWM   | Output to amp for AM overlay   |
| 14        | Power sense    | Rail 2 on (pull-down)          |
| 15        | DFPlayer BUSY  | 0 = playing, 1 = idle          |
| 16        | NeoPixel data  | Status LED                     |

- **DFPlayer:** Power (3.3V or 5V per module), GND, TX→Pico RX (GP1), RX→Pico TX (GP0), SPK_1/SPK_2 or DAC to amplifier.
- **Button:** One side to GP2, other to GND (internal pull-up).
- **Power sense:** Optional; pull GP14 high when “Rail 2” is on so the firmware can detect power state.

## SD Card Layout

The DFPlayer expects **folders at the SD root** and **MP3 files** with three-digit names inside each folder.

- **SD root:** Folders named `01`, `02`, `03`, … (two digits). Each folder = one album or playlist in order.
- **Inside each folder:** `001.mp3`, `002.mp3`, … (three digits + `.mp3`). Track index in the folder = file number.
- **VintageRadio/** (at SD root): Used for state and metadata only:
  - `AMradioSound.wav` – AM overlay sound
  - `album_state.txt` – current album/track and learned track counts
  - `radio_metadata.json` – album/playlist and track mapping

**Preparing the SD card:** In the Vintage Radio desktop app, set **Audio target** to **DFPlayer + RP2040**, choose your SD root, then use **Sync Library to SD**. The app will create the `01/`, `02/`, … layout and `VintageRadio/` with the correct contents. You can also use **Export SD contents to folder…** and then copy that folder to the SD card.

## Installing the Application

You need to copy the Vintage Radio Python files onto the Pico. The Pico does **not** appear as a USB drive when running MicroPython; use one of the following.

**Option A – Manual (Thonny)**

1. Export **Export for RP2040** from the Vintage Radio app to a folder on your PC.
2. In Thonny, connect to the Pico (MicroPython interpreter).
3. Copy to the Pico:
   - `main.py` → Pico root
   - `radio_core.py` → Pico root
   - Entire `components` folder → Pico root (so that `components/dfplayer_hardware.py` exists on the Pico)

**Option B – From the Vintage Radio app (Install to Pico)**

1. Install [mpremote](https://docs.micropython.org/en/latest/reference/mpremote.html): `pip install mpremote`
2. Connect the Pico via USB (MicroPython already installed).
3. In the Vintage Radio app, use **Install to Pico** (or **Copy to Pico**). The app will copy `main.py`, `radio_core.py`, and `components/` to the Pico using mpremote.

If mpremote is not installed, the app will show a message; install it and try again.

## Running

1. Insert the prepared SD card into the DFPlayer (or SD slot used by the DFPlayer).
2. Power the Pico (USB or your board’s power). The script runs automatically (e.g. `main.py` is the default run target on boot).
3. Use the button: tap = next track, double-tap = previous, triple-tap = restart album, hold = next album, tap+hold = switch mode, etc.

## Troubleshooting

- **No sound / wrong track:** Check SD layout (01/, 02/, 001.mp3, 002.mp3) and that **Sync Library to SD** was run with **DFPlayer + RP2040** selected. Ensure `radio_metadata.json` and `album_state.txt` are in `VintageRadio/` on the SD card.
- **DFPlayer not responding:** Check UART wiring (TX→RX, RX→TX), baud rate 9600, and power to the DFPlayer. Try another SD card (FAT32, small capacity often more reliable).
- **Button or BUSY not working:** Verify GPIO connections (GP2 = button, GP15 = BUSY) and that the firmware’s pin numbers match your wiring (see `components/dfplayer_hardware.py`).
- **AM overlay missing:** Ensure `AMradioSound.wav` is in `VintageRadio/` on the SD card. The desktop app copies it there when you export or sync.
