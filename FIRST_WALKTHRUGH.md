This guide should help you with your first time setup for your Vintage Radio.

# Load your library
1. First, if your music files are already organized in folders by albums/playlists on your computer, create the album/playlist names on the **Vintage Radio Music Manager** under their corresponding sections:
![Named Albums](docs/images/first-time-walkthrough/naming_albums_1.png)
Even if you don't have playlists already made, creating them within the playlist section is easier by dragging and dropping directly into your empty playlists.
![Named Playlists](docs/images/first-time-walkthrough/named_playlists_1.png)

2. Drag and drop your albums/playlists/music files directly into your newly created empty ones. Everything should import and be ready to sync to your SD card.
![Populated Albums](docs/images/first-time-walkthrough/drag_n_drop_album.png)
![Populated Albums](docs/images/first-time-walkthrough/populated_album.png)

# Flash your SD Card
1. Now move on to the devices tab and click **Detect** and make sure to choose your SD card path
![Devices](docs/images/first-time-walkthrough/devices.png)
![Selecting SD Card](docs/images/first-time-walkthrough/selecting_SD_card.png)

2. Then, click on **Sync Library to SD**. Note that there are tooltips on each button if you need more information.
![Sync SD](docs/images/first-time-walkthrough/sync_sd.png)
Click **No** if your SD card isn't clean (not freshly formatted or contains old files). If this is your first time, either option should work, but it's best to work with a freshly formatted SD card.
![Sync Dialog](docs/images/first-time-walkthrough/sync_dialog.png)
_**Note:**_ This will take some time if files aren't already in mp3 format, as the software will convert them for you.
![Sync Progress](docs/images/first-time-walkthrough/sync_progress.png)

3. Once the syncing is complete, click on **Safely Remove SD Card**. You are now ready to install it in your DFPlayer.
![Eject SD](docs/images/first-time-walkthrough/safe_rem.png)

# Flash your RP2040
1. Now, plug in your RP2040 while holding the BOOT button (or hit the RESET button while holding down the BOOT button if it's already plugged in). This should cause your device to appear as a removable storage medium. Now, click on **Install MicroPython on Pico**

2. You should see a dialog window and your **RPI-RP2** should automatically be selected, along with the latest firmware (if not, please select and download the latest).
![Install on RP2040](docs/images/first-time-walkthrough/install_pico.png)
Click on **Install to Pico**.
![Install Complete](docs/images/first-time-walkthrough/install_pico_success.png)

3. Next, click on the **Install to Pico** button on the main devices screen to install the Vintage Radio software on the RP2040.
![Install Main Software](docs/images/first-time-walkthrough/installing_software.png)

# Test it out
That's it, your device should be ready to test (you may need to click the RESET button one more time on your RP2040)

# Physical Button Commands

## Basic Controls
- **Tap** = Next track (quick press and release)
- **Double-tap** = Previous track (two quick taps)
- **Triple-tap** = Restart album (three quick taps)
- **Hold** = Next album/playlist (press and hold for 500ms+)

## Combination Controls
- **Tap + Hold** = Toggle Album/Playlist mode
  - *How to do it:* Tap once (release), then press and hold
- **Double-tap + Hold** = Shuffle current album/playlist
  - *How to do it:* Double-tap (release after each tap), then press and hold
- **Triple-tap + Hold** = Shuffle entire library
  - *How to do it:* Triple-tap (release after each tap), then press and hold

_**Note:**_ For combination commands, complete the taps first (release after each tap), then press and hold. The system recognizes the taps and combines them with the hold gesture.

All button commands work on both the physical device and the emulator.