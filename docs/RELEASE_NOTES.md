# Vintage Radio Music Manager

Desktop application for managing your music library and syncing it to a vintage-style radio device. Organize tracks, build albums and playlists, sync to SD (with optional conversion to MP3), and try everything in a built-in emulator before using the hardware.

---

# Release summary — **v0.2.1-beta**

> **Conversion and audio tools.** Release builds ship with **FFmpeg** bundled; the app **prefers FFmpeg** for MP3 conversion when syncing to SD. You **do not need to install VLC** for conversion to work.

## Your music in the app (library organizer)

The app gives you a full **library organizer**: import and browse tracks, build **stations** (the folders that become `01`, `02`, … on the SD card), and use **albums** and **playlists** to group and order music on the desktop. You can **drag songs** inside albums and playlists to **reorder** playback order, and drag from **File Explorer** into collections.

**Bring an existing folder layout in one step:** you can **drag entire folders** (or select many folders at once) from Explorer into the **Stations** area. If your music is already organized on disk—one folder per “station”—open the parent folder, select all of those station folders, and drag them in; the app adds the structure without you recreating it by hand.

## How the radio uses the SD card

The recommended device workflow is **basic mode**: the radio discovers **stations from the DFPlayer / SD folder layout** (`01`, `02`, …). The card’s folders are the source of truth on boot. After a big one-time sync, **swap cards** when you like; a **cold boot** after swapping helps the radio match the new card.

---

## What’s new in v0.2.1-beta

### Experimental: SD image sync (Windows)

**Experimental SD image sync** builds a **FAT32 disk image** of your station layout and **writes it straight to the SD card** (after a Windows security prompt for that step only). You can optionally **prepare everything on this PC first**, then flash—so the card stays untouched until you’re ready.

**Why use it**

- **Much faster than a “clean everything and copy again” normal sync** when you have a **very large library**. A full normal sync can take **hours**; image sync is aimed at getting a **fresh card** ready in **far less time** for that first big load.
- After that first pass, use **normal sync** for **small, day-to-day updates**—add or change a few tracks without redoing the whole job.

The card is formatted as **one FAT32 volume using the full size of the SD card**, so you keep **room to grow**. Optional **“flash last image only”** skips rebuild when you already have a matching cached image for retests.

**Safety and clarity**

- The wizard focuses on **USB / memory-card style** drives, shows **sizes and labels**, and explains what you’re about to erase.
- Progress and messages separate **prepare**, **build image**, and **flash**; problems show in the **session log** as well as on screen.

### Library and sync quality of life

- **Folder drag-and-drop into Stations** — see *Your music in the app* above.
- **Sync progress** — long syncs report status more clearly so the window doesn’t look stuck.

### Updates from inside the app

- **Check for updates** from the app (see **Help** / version area).
- **Update notifications** — when a newer release is available, you’ll be **notified after launch** (you can also check manually anytime).

### Radio firmware and playback

- Further fixes and polish for **basic-mode** playback on the Pico (station discovery, DFPlayer handling, and edge cases around track changes and visit/shuffle behavior).

---

**Full Changelog (GitHub):** https://github.com/alexnoctis76/Vintage_radio/compare/v0.2.0-beta...v0.2.1-beta

---

## Downloads

- **Windows** — Unzip `Vintage-Radio-Windows.zip`, open the `Vintage Radio` folder, and run `Vintage Radio.exe`.
- **macOS** — Unzip `Vintage-Radio-macOS.zip` and run the app inside the folder.

## Before you start

- **MP3 conversion:** In **release builds**, **FFmpeg is included**; you don’t need a separate FFmpeg or VLC install for typical sync-to-SD conversion.
- **From source:** Use Python 3.8+ and `requirements.txt` as in the README. If you run without the bundled binary, ensure FFmpeg is available on your `PATH` where the app expects it.

## Documentation

- Main [README](README.md) — setup, usage, and building from source.
- [Pi setup](docs/README_Pi.md) — running on Raspberry Pi.
- [RP2040](docs/README_RP2040.md) — RP2040 firmware notes.
