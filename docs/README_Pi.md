# Vintage Radio – Raspberry Pi Setup

This guide covers setting up the Vintage Radio application on a **Raspberry Pi 2W or 3** (or compatible) with **VLC** for playback and optional **GPIO** for button and power sense.

## What You Need

- **Raspberry Pi 2W or 3** (or compatible board)
- **SD card** (or USB storage) for the OS and for media
- Optional: GPIO wiring for button and power sense (see Pinout below)
- **Raspberry Pi OS** (or compatible) on the Pi
- **Vintage Radio desktop app** (to prepare library and optionally deploy to the Pi)

## Prerequisites: Flash the Pi OS (One-Time)

You need an OS on the Pi before installing the application. There is no separate “firmware” image; you only flash a normal Raspberry Pi OS.

1. Install [Raspberry Pi Imager](https://www.raspberrypi.com/software/) on your PC.
2. Use Imager to write **Raspberry Pi OS** (or your preferred variant) to the Pi’s SD card.
3. During imaging, you can set hostname, enable SSH, configure Wi‑Fi, and set a user/password.
4. Eject the SD card, insert it into the Pi, and boot. Complete any first-run setup (locale, network, etc.).

After this, the Pi is ready for you to copy the Vintage Radio application onto it (see “Getting the application onto the Pi” below).

## Pinout / Connections (Optional)

If you use GPIO for button and power sense, the defaults in `components/pi_hardware.py` (BCM numbering) are:

| BCM GPIO | Use          | Notes                |
|----------|--------------|----------------------|
| 2        | Button       | Active low (pull-up) |
| 14       | Power sense  | High when “Rail 2” on |
| 15       | BUSY         | Optional; can use VLC state instead |

You can change these at the top of `components/pi_hardware.py` or via a config if you add one.

## Getting the Application onto the Pi

Copy the exported Vintage Radio Pi files to the Pi. No “firmware” flash is involved; it’s just copying Python files and installing dependencies.

**Option A – USB stick**

1. In the Vintage Radio desktop app, use **Export for Raspberry Pi** and choose a folder. Copy that folder onto a USB stick.
2. Plug the USB stick into the Pi, mount it, and copy the folder to e.g. `/home/pi/vintage_radio/`.

**Option B – SCP (network)**

1. Export **Export for Raspberry Pi** to a folder on your PC.
2. From your PC (with the Pi powered and on the same network), run:
   ```bash
   scp -r /path/to/exported_folder pi@<pi-ip-address>:/home/pi/vintage_radio/
   ```
   Use the Pi’s IP address and the `pi` user (or your configured user). Enter the password when prompted, or use SSH keys for passwordless copy.

**Option C – From the Vintage Radio app (Deploy to Pi)**

1. In the Vintage Radio app, use **Deploy to Raspberry Pi** (or **Copy to Pi**).
2. Enter the Pi’s IP address and, if needed, SSH user and path (e.g. `/home/pi/vintage_radio`).
3. The app will copy the same files as “Export for Raspberry Pi” to the Pi and can optionally run `pip3 install -r requirements_pi.txt` over SSH.

If you prefer not to use the app, Options A and B are enough; the README in the export folder summarizes these steps.

## Setup on the Pi

1. **SSH or local terminal** on the Pi:
   ```bash
   cd /home/pi/vintage_radio
   pip3 install -r requirements_pi.txt
   ```
   (Use a virtualenv if you prefer.)

2. **Set the media path:** The application reads media and metadata from a path that contains your `VintageRadio` folder (or library). Set it in one of these ways:
   - **Environment variable:** Before running the app:
     ```bash
     export VINTAGE_RADIO_MEDIA_ROOT=/path/to/sd_or_usb_root
     python3 main_pi.py
     ```
     Here `/path/to/sd_or_usb_root` is the mount point of the SD or USB that contains `VintageRadio/` (with `library/`, `radio_metadata.json`, `album_state.txt`, etc.).
   - **In code:** Edit `MEDIA_ROOT` at the top of `components/pi_hardware.py` to that same path.

3. Ensure the media storage (SD or USB) is mounted and that `VINTAGE_RADIO_MEDIA_ROOT` (or `MEDIA_ROOT`) points to its root so that `VintageRadio/radio_metadata.json` and `VintageRadio/library/` (or your media tree) exist under it.

## SD / Media Layout for the Pi

When you use the desktop app with **Audio target = Raspberry Pi 2W/3** and **Sync Library to SD** (or **Export SD contents to folder…**), it creates:

- **VintageRadio/library/** – Flat list of files with original-style filenames (or converted to MP3 if “Convert non-MP3 to MP3 when syncing for Pi” is enabled).
- **VintageRadio/radio_metadata.json** – Album/playlist and track mapping.
- **VintageRadio/album_state.txt** – Current album/track state.

Copy that whole structure to the Pi’s SD or USB and set `VINTAGE_RADIO_MEDIA_ROOT` to the root of that drive (so that `VintageRadio` is under it).

## Running

From the project directory on the Pi:

```bash
python3 main_pi.py
```

You can run it in a terminal or add a systemd service so it starts on boot; the README in the export folder or the app’s Deploy step may mention this.

## Troubleshooting

- **VLC / python-vlc errors:** Install VLC and the Python bindings: `pip3 install python-vlc`. On some systems you may need to install the VLC system package as well (e.g. `sudo apt install vlc`).
- **GPIO permission denied:** Run with `sudo` only if necessary, or add your user to the `gpio` group (e.g. `sudo usermod -aG gpio $USER` and log out/in).
- **No playback / wrong track:** Check that `VINTAGE_RADIO_MEDIA_ROOT` (or `MEDIA_ROOT` in `pi_hardware.py`) points to the root that contains `VintageRadio/`. Ensure `radio_metadata.json` and the media files exist and paths in the metadata are correct (the app resolves paths using `MEDIA_ROOT`).
