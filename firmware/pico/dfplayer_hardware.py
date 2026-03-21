"""
DFPlayer Hardware Interface for MicroPython

This module implements the HardwareInterface from radio_core.py
for the actual DFPlayer Mini hardware on the Raspberry Pi Pico.

This allows the firmware to run the exact same logic as the GUI emulator.
"""

from machine import Pin, PWM, Timer, UART
import neopixel
import ustruct
import time
import os

# Try to import SD card support
try:
    from machine import SPI
    from sdcard import SDCard
    SD_CARD_AVAILABLE = True
except ImportError:
    SD_CARD_AVAILABLE = False

# Try to import json
try:
    import ujson as json
except ImportError:
    import json

# Import shared constants and interface from radio_core
from radio_core import HardwareInterface, FADE_IN_S, DF_BOOT_MS

# Import pin configuration (reads pin_config.json, falls back to defaults)
from pin_config_loader import load_pin_config, get_spi_config, get_dfplayer_config

# ===========================
#      PIN CONFIGURATION
# ===========================

_cfg = load_pin_config()
_pins = _cfg.get("pins", {})

PIN_AUDIO       = _pins.get("audio_pwm", 3)
PIN_BUTTON      = _pins.get("button", 2)
PIN_NEOPIX      = _pins.get("neopixel", 16)
PIN_UART_TX     = _pins.get("uart_tx", 0)
PIN_UART_RX     = _pins.get("uart_rx", 1)
PIN_SENSE       = _pins.get("power_sense", 14)
PIN_BUSY        = _pins.get("busy", 15)

# ===========================
#      CONSTANTS
# ===========================

_df_cfg = get_dfplayer_config()
DFPLAYER_VOL    = _df_cfg.get("max_volume", 28)  # Max volume (0-30 scale)
VOLUME_SCALE    = 1.0
WAV_FILE        = "VintageRadio/AMradioSound.wav"
PWM_CARRIER     = 125_000
ALBUM_FILE      = "VintageRadio/album_state.txt"
METADATA_FILE   = "VintageRadio/radio_metadata.json"

BUSY_CONFIRM_MS = 1800
POST_CMD_GUARD_MS = 120
ALBUM_PROBE_MS  = 650

# DFPlayer response (command) codes (from DFPlayer TX -> Pico RX)
DF_RESP_ACK = 0x41           # Command acknowledgment (when feedback=0x01)
DF_RESP_ERROR = 0x40         # Error occurred, param_lo = error code
DF_RESP_TRACK_FINISHED = 0x3D  # Track finished on TF card, p1:p2 = track number
DF_RESP_INIT = 0x3F         # Init/Reset complete, p2 = device bitmap
DF_RESP_MEDIA_INSERTED = 0x3A
DF_RESP_MEDIA_EJECTED = 0x3B
DF_RESP_STATUS = 0x42       # Response to status query: p1=device, p2=0 stopped / 1 playing
DF_RESP_VOLUME = 0x43       # Response to volume query: p2 = 0..30
DF_RESP_TF_FILES = 0x48     # Response: total TF files (p1<<8|p2)
DF_RESP_CURRENT_TRACK = 0x4C  # Response: current track on TF (p1<<8|p2)
DF_RESP_FOLDER_FILES = 0x4E   # Response: file count in queried folder (p1<<8|p2)
DF_RESP_FOLDER_COUNT = 0x4F   # Response: total folder count on TF (p1<<8|p2)

# DFPlayer 0x40 error codes (param_lo)
DF_ERROR_MSGS = {
    0x01: "Module busy", 0x02: "Sleep mode", 0x03: "Serial receiving error",
    0x04: "Checksum error", 0x05: "File index out of bound", 0x06: "File not found",
    0x07: "Insert TF card",
}

MID = 32768

# ===========================
#      WAV LOADER
# ===========================

def load_wav_u8(path):
    """Load a WAV file and return (data, samplerate)."""
    with open(path, "rb") as f:
        if f.read(4) != b"RIFF":
            raise ValueError("Not RIFF")
        f.read(4)
        if f.read(4) != b"WAVE":
            raise ValueError("Not WAVE")
        samplerate = 8000
        while True:
            cid = f.read(4)
            if not cid:
                raise ValueError("No data chunk")
            clen = ustruct.unpack("<I", f.read(4))[0]
            if cid == b"fmt ":
                fmt = f.read(clen)
                samplerate = ustruct.unpack("<I", fmt[4:8])[0]
            elif cid == b"data":
                data = f.read(clen)
                break
            else:
                f.seek(clen, 1)
    return data, samplerate


class DFPlayerHardware(HardwareInterface):
    """
    Hardware implementation using DFPlayer Mini and WAV playback on Pico.
    
    This class handles:
    - UART commands to DFPlayer
    - AM static sound via PWM overlay on GPIO 3 (preferred, requires AMradioSound.wav on Pico flash)
    - AM static sound via DFPlayer SD card folder 99 (fallback if WAV not on Pico)
    - NeoPixel status indicator
    - State persistence to SD card
    - Loading album/playlist metadata
    """
    
    def __init__(self):
        # Initialize hardware pins
        self.np = neopixel.NeoPixel(Pin(PIN_NEOPIX), 1)
        self.np[0] = (4, 4, 4)
        self.np.write()
        
        self.button = Pin(PIN_BUTTON, Pin.IN, Pin.PULL_UP)
        self.power_sense = Pin(PIN_SENSE, Pin.IN, Pin.PULL_DOWN)
        self.pin_busy = Pin(PIN_BUSY, Pin.IN)
        
        self.uart = UART(0, baudrate=9600, tx=Pin(PIN_UART_TX), rx=Pin(PIN_UART_RX))
        
        # Two-way UART state (must be initialized before any _df_send / _df_read_pending calls)
        self._uart_rx_buf = bytearray()
        self._track_finished_via_uart = False
        self._track_finished_track_num = None
        self._last_error_code = None
        self._pending_ack = False
        self._query_status_result = None
        self._query_current_track_result = None
        self._query_file_count_result = None
        self._query_folder_count_result = None
        self._query_folder_files_result = None
        
        # GPIO 3 (PIN_AUDIO) is used for PWM AM overlay only.
        # Start it as high-impedance input so it doesn't inject noise
        # into the amplifier during normal DFPlayer playback.
        Pin(PIN_AUDIO, Pin.IN)
        self.pwm = None
        self.tim = None
        
        # Give DFPlayer time to power up before first UART (avoids missed ACKs / no play)
        time.sleep_ms(400)
        # Reset DFPlayer to ensure it's in a known state
        self._df_reset()
        
        # Volume — matches original baseline: fixed at DFPLAYER_VOL (28)
        # The potentiometer controls power on/off via GP14, not volume.
        self._volume = 100
        self._df_volume = DFPLAYER_VOL
        self._df_set_vol(self._df_volume)
        
        # Ignore BUSY edges after manual skips
        self.ignore_busy_until = 0
        
        # Load WAV data for PWM-based AM overlay (plays through GPIO 3)
        self.wav_data = None
        self.wav_sr = 8000
        self.lut = None
        self._load_wav()
        
        # Cached metadata
        self._albums = []
        self._playlists = []
        self._all_tracks = []
        self._known_tracks = {}
        
        # AM sound DFPlayer folder/track (loaded from metadata)
        self._am_folder = 99
        self._am_track = 1
        self._am_duration_ms = 3000
        
        # Flag to prevent duplicate playback when AM overlay is playing
        self._am_overlay_active = False
        
        # When True, play_track() no-ops so firmware can play AM overlay first (mode switch / power-on)
        self._delay_playback = False
    
    def set_delay_playback(self, delay):
        """When True, play_track() will no-op so the firmware can run start_with_am() first."""
        self._delay_playback = bool(delay)
    
    def _try_mount_sd(self):
        """Try to mount SD card if available. Returns True if mounted."""
        if not SD_CARD_AVAILABLE:
            return False
        
        try:
            # Check if already mounted
            if "sd" in os.listdir("/"):
                print("SD card already mounted at /sd")
                return True
            
            # Try to mount SD card (typical SPI pins for Pico)
            # Note: These pins may need to be adjusted based on your hardware
            # Common SD card module connections:
            # CS = GP5, SCK = GP2, MOSI = GP3, MISO = GP4
            spi_cfg = get_spi_config(alt=False)
            spi_bus = spi_cfg.get("bus", 1)
            spi_sck = spi_cfg.get("sck", 10)
            spi_mosi = spi_cfg.get("mosi", 11)
            spi_miso = spi_cfg.get("miso", 12)
            spi_cs = spi_cfg.get("cs", 13)
            try:
                spi = SPI(spi_bus, baudrate=1000000, polarity=0, phase=0, sck=Pin(spi_sck), mosi=Pin(spi_mosi), miso=Pin(spi_miso))
                cs = Pin(spi_cs, Pin.OUT)
                sd = SDCard(spi, cs)
                os.mount(sd, "/sd")
                print("SD card mounted at /sd")
                return True
            except Exception as e:
                print(f"SD card mount failed (SPI method): {e}")
                spi_alt = get_spi_config(alt=True)
                if spi_alt:
                    alt_bus = spi_alt.get("bus", 0)
                    alt_sck = spi_alt.get("sck", 18)
                    alt_mosi = spi_alt.get("mosi", 19)
                    alt_miso = spi_alt.get("miso", 16)
                    alt_cs = spi_alt.get("cs", 17)
                    try:
                        spi = SPI(alt_bus, baudrate=1000000, polarity=0, phase=0, sck=Pin(alt_sck), mosi=Pin(alt_mosi), miso=Pin(alt_miso))
                        cs = Pin(alt_cs, Pin.OUT)
                        sd = SDCard(spi, cs)
                        os.mount(sd, "/sd")
                        print("SD card mounted at /sd (alt pins)")
                        return True
                    except Exception as e2:
                        print(f"SD card mount failed (alt pins): {e2}")
                # Fallback: RP2040 default SPI pins (no custom pins - avoids "bad SCK pin" from config)
                try:
                    spi = SPI(1, baudrate=1000000, polarity=0, phase=0)  # default sck=10, mosi=11, miso=8
                    cs = Pin(13, Pin.OUT)
                    sd = SDCard(spi, cs)
                    os.mount(sd, "/sd")
                    print("SD card mounted at /sd (default SPI1 pins)")
                    return True
                except Exception as e3:
                    print(f"SD card mount failed (default pins): {e3}")
                return False
        except Exception as e:
            print(f"SD card mount error: {e}")
            return False
    
    def _load_wav(self):
        """Try to load AM radio WAV file into Pico memory for PWM overlay.
        
        If loaded, the AM static can play through GPIO 3 simultaneously with
        DFPlayer music (true overlay). If not found, we fall back to playing
        the AM sound through the DFPlayer itself (sequential, not overlaid).
        """
        paths_to_try = [
            "/VintageRadio/AMradioSound.wav",
            WAV_FILE,
            "/" + WAV_FILE,
            "AMradioSound.wav",
        ]
        
        for path in paths_to_try:
            try:
                self.wav_data, self.wav_sr = load_wav_u8(path)
                print(f"AM WAV loaded from Pico flash: {path} -> PWM overlay enabled")
                break
            except Exception:
                continue
        
        if self.wav_data is not None:
            self.lut = [0] * 256
            scale = int(256 * VOLUME_SCALE)
            for i in range(256):
                d = MID + (i - 128) * scale
                d = max(0, min(65535, d))
                self.lut[i] = d
            print(f"AM WAV: {len(self.wav_data)} samples, {self.wav_sr}Hz — overlay will play through GPIO {PIN_AUDIO}")
        else:
            print("AM WAV not on Pico flash — will use DFPlayer SD card for AM sound (sequential, not overlaid)")
            print("  For overlay: copy AMradioSound.wav to Pico flash via 'Install to Pico'")
    
    # ===========================
    #   DFPLAYER COMMANDS
    # ===========================
    
    def _df_send(self, cmd, p1=0, p2=0, feedback=False):
        """Send a command to DFPlayer.
        
        feedback=False (default): byte 4 = 0x00, fire-and-forget. Matches original
            working firmware. DFPlayer still sends unsolicited events (0x3D track
            finished, 0x40 error, 0x3F init) regardless.
        feedback=True: byte 4 = 0x01. Use ONLY for query commands (0x42, 0x4C, 0x48)
            that need a specific response. Many DFPlayer clones misbehave with 0x01.
        """
        fb = 0x01 if feedback else 0x00
        pkt = bytearray([0x7E, 0xFF, 0x06, cmd, fb, p1 & 0xFF, p2 & 0xFF])
        csum = -sum(pkt[1:7]) & 0xFFFF
        pkt.append((csum >> 8) & 0xFF)
        pkt.append(csum & 0xFF)
        pkt.append(0xEF)
        n = self.uart.write(pkt)
        if n != len(pkt):
            print(f"UART WRITE ERROR: wrote {n}/{len(pkt)} bytes for cmd 0x{cmd:02X}")
        # DFPlayer needs ~20-30ms to process each command before the next one.
        # Without this, back-to-back commands get dropped silently.
        time.sleep_ms(30)
    
    def _df_reset(self):
        """Reset DFPlayer."""
        print("DF: RESET")
        self._df_send(0x3F, 0x00, 0x00)
        time.sleep_ms(800)
        self._df_read_pending()
    
    def _df_set_vol(self, v):
        """Set DFPlayer volume (0-30)."""
        v = max(0, min(30, v))
        if not getattr(self, '_am_overlay_active', False):
            print("DF: set volume", v)
        self._df_send(0x06, 0x00, v)
    
    def _df_play_folder_track(self, folder, track):
        """Play a specific folder/track on DFPlayer.
        
        DFPlayer command 0x0F format:
        - Command: 0x0F (Play folder track)
        - Parameter 1: Folder number (1-99, maps to folders "01" to "99" on SD card)
        - Parameter 2: Track number (1-999, maps to files "001.mp3" to "999.mp3" in folder)
        """
        # Validate folder/track numbers
        if folder < 1 or folder > 99:
            print(f"ERROR: Invalid folder number {folder} (must be 1-99)")
            return
        if track < 1 or track > 999:
            print(f"ERROR: Invalid track number {track} (must be 1-999)")
            return
        
        # Try to get track info from metadata for better logging
        track_info = f"folder={folder:02d}, track={track:03d}"
        try:
            # Find track in albums or playlists
            for album in self._albums:
                if album.get('id') == folder:
                    tracks = album.get('tracks', [])
                    for t in tracks:
                        if t.get('track_number') == track:
                            title = t.get('title', 'Unknown')
                            artist = t.get('artist', 'Unknown')
                            track_info = f"'{title}' by {artist} (folder={folder:02d}, track={track:03d})"
                            break
            for playlist in self._playlists:
                if playlist.get('id') == folder:
                    tracks = playlist.get('tracks', [])
                    for t in tracks:
                        if t.get('track_number') == track:
                            title = t.get('title', 'Unknown')
                            artist = t.get('artist', 'Unknown')
                            track_info = f"'{title}' by {artist} (folder={folder:02d}, track={track:03d})"
                            break
        except Exception as e:
            print(f"Error looking up track info: {e}")
        
        print(f"DF: Playing {track_info} -> Sending command 0x0F (folder={folder}, track={track})")
        print(f"DF: Expected SD path: {folder:02d}/{track:03d}.mp3")
        self._df_send(0x0F, folder, track)
    
    def _df_set_time(self, seconds):
        """Set playback time position (seek) in seconds (0-65535).
        Note: Some DFPlayer docs use 0x03 for 'play track in root'; if the module
        does not support in-track seek, this may have no effect and track plays from start.
        """
        # Command 0x03: attempt seek; p1 = high byte of seconds, p2 = low byte
        seconds = max(0, min(65535, int(seconds)))
        p1 = (seconds >> 8) & 0xFF
        p2 = seconds & 0xFF
        print("DF: set time", seconds, "seconds")
        self._df_send(0x03, p1, p2)
    
    def _df_stop(self):
        """Stop DFPlayer playback."""
        print("DF: stop")
        self._df_send(0x16, 0, 0)
    
    # ===========================
    #   DFPLAYER RESPONSE PARSING (two-way UART)
    # ===========================
    
    def _df_read_response(self):
        """Read one 10-byte DFPlayer response packet from UART if available.
        
        Handles partial reads and resync (scan for 0x7E). Returns (cmd, param_hi, param_lo)
        or None if no complete packet. Updates _uart_rx_buf with any leftover bytes.
        """
        n = self.uart.any()
        if n > 0:
            data = self.uart.read(n)
            if data:
                self._uart_rx_buf.extend(data)
        # Need at least 10 bytes for a packet
        while len(self._uart_rx_buf) >= 10:
            # Find start byte
            start = -1
            for i in range(len(self._uart_rx_buf)):
                if self._uart_rx_buf[i] == 0x7E:
                    start = i
                    break
            if start < 0:
                self._uart_rx_buf.clear()
                return None
            if start > 0:
                # Discard bytes before start
                # MicroPython: slice deletion (del buf[:n]) is not supported;
                # use slice assignment instead.
                self._uart_rx_buf[:] = self._uart_rx_buf[start:]
            if len(self._uart_rx_buf) < 10:
                return None
            pkt = self._uart_rx_buf[:10]
            # Validate: byte 1 = 0xFF, byte 2 = 0x06, byte 9 = 0xEF
            if pkt[1] != 0xFF or pkt[2] != 0x06 or pkt[9] != 0xEF:
                self._uart_rx_buf[:] = self._uart_rx_buf[1:]
                continue
            csum = -sum(pkt[1:7]) & 0xFFFF
            if (pkt[7] != ((csum >> 8) & 0xFF)) or (pkt[8] != (csum & 0xFF)):
                self._uart_rx_buf[:] = self._uart_rx_buf[1:]
                continue
            cmd, p1, p2 = pkt[3], pkt[5], pkt[6]
            self._uart_rx_buf[:] = self._uart_rx_buf[10:]
            return (cmd, p1, p2)
        return None
    
    def _df_read_pending(self):
        """Drain all available DFPlayer responses and dispatch unsolicited events.
        
        Sets _track_finished_via_uart / _track_finished_track_num on 0x3D,
        _last_error_code and logs on 0x40, _pending_ack on 0x41, and stores
        query results for 0x42/0x4C/0x48. Call this every main loop iteration.
        """
        while True:
            r = self._df_read_response()
            if r is None:
                break
            cmd, p1, p2 = r
            if cmd == DF_RESP_TRACK_FINISHED:
                track_num = (p1 << 8) | p2
                self._track_finished_via_uart = True
                self._track_finished_track_num = track_num
                print("DF: UART track finished, track=", track_num)
            elif cmd == DF_RESP_ERROR:
                self._last_error_code = p2
                err_msg = DF_ERROR_MSGS.get(p2, "Unknown error 0x%02X" % p2)
                print("DF: Error:", err_msg)
            elif cmd == DF_RESP_ACK:
                self._pending_ack = True
            elif cmd == DF_RESP_INIT:
                print("DF: Init complete, device bitmap=", p2)
            elif cmd == DF_RESP_STATUS:
                self._query_status_result = p2  # 0=no play, 1=play
            elif cmd == DF_RESP_CURRENT_TRACK:
                self._query_current_track_result = (p1 << 8) | p2
            elif cmd == DF_RESP_TF_FILES:
                self._query_file_count_result = (p1 << 8) | p2
            elif cmd == DF_RESP_FOLDER_FILES:
                self._query_folder_files_result = (p1 << 8) | p2
            elif cmd == DF_RESP_FOLDER_COUNT:
                self._query_folder_count_result = (p1 << 8) | p2
    
    def check_track_finished_uart(self):
        """Return True if a track-finished event was received via UART (0x3D).
        Caller should clear the event by consuming it (see consume_track_finished_uart)."""
        return self._track_finished_via_uart
    
    def consume_track_finished_uart(self):
        """Clear the UART track-finished flag and return the track number that finished (or None)."""
        track_num = self._track_finished_track_num
        self._track_finished_via_uart = False
        self._track_finished_track_num = None
        return track_num
    
    def query_status(self):
        """Query playback status (0x42). Returns 0=stopped, 1=playing, or None on timeout."""
        self._query_status_result = None
        self._df_send(0x42, 0, 0, feedback=True)
        start = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), start) < 200:
            self._df_read_pending()
            if self._query_status_result is not None:
                return self._query_status_result
            time.sleep_ms(10)
        return None
    
    def query_current_track(self):
        """Query current track on TF card (0x4C). Returns track number or None."""
        self._query_current_track_result = None
        self._df_send(0x4C, 0, 0, feedback=True)
        start = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), start) < 200:
            self._df_read_pending()
            if self._query_current_track_result is not None:
                return self._query_current_track_result
            time.sleep_ms(10)
        return None
    
    def query_file_count(self):
        """Query total file count on TF card (0x48). Returns count or None."""
        self._query_file_count_result = None
        self._df_send(0x48, 0, 0, feedback=True)
        start = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), start) < 200:
            self._df_read_pending()
            if self._query_file_count_result is not None:
                return self._query_file_count_result
            time.sleep_ms(10)
        return None
    
    def query_folder_count(self):
        """Query total folder count on TF card (0x4F). Returns count or None."""
        self._query_folder_count_result = None
        self._df_send(0x4F, 0, 0, feedback=True)
        start = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), start) < 300:
            self._df_read_pending()
            if self._query_folder_count_result is not None:
                return self._query_folder_count_result
            time.sleep_ms(10)
        return None

    def query_files_in_folder(self, folder_num, suppress_errors=False):
        """Query file count in a specific folder (0x4E). Returns count or None.

        If the DFPlayer returns an error (e.g. 0x06 = file not found for a
        non-existent folder), returns 0 immediately rather than waiting for timeout.

        suppress_errors: if True, do not print the error message (used during
            station discovery to avoid spamming the console).
        """
        self._query_folder_files_result = None
        self._last_error_code = None
        self._df_send(0x4E, 0, folder_num & 0xFF, feedback=True)
        start = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), start) < 300:
            # Drain UART manually so we can intercept error responses
            while True:
                r = self._df_read_response()
                if r is None:
                    break
                cmd, p1, p2 = r
                if cmd == DF_RESP_FOLDER_FILES:
                    self._query_folder_files_result = (p1 << 8) | p2
                elif cmd == DF_RESP_ERROR:
                    self._last_error_code = p2
                    if not suppress_errors:
                        err_msg = DF_ERROR_MSGS.get(p2, "Unknown error 0x%02X" % p2)
                        print("DF: Error:", err_msg)
                    # Any error means folder doesn't exist or is empty
                    return 0
                else:
                    # Pass other responses to normal dispatch
                    if cmd == DF_RESP_TRACK_FINISHED:
                        self._track_finished_via_uart = True
                        self._track_finished_track_num = (p1 << 8) | p2
                    elif cmd == DF_RESP_STATUS:
                        self._query_status_result = p2
                    elif cmd == DF_RESP_CURRENT_TRACK:
                        self._query_current_track_result = (p1 << 8) | p2
                    elif cmd == DF_RESP_TF_FILES:
                        self._query_file_count_result = (p1 << 8) | p2
                    elif cmd == DF_RESP_FOLDER_COUNT:
                        self._query_folder_count_result = (p1 << 8) | p2
            if self._query_folder_files_result is not None:
                return self._query_folder_files_result
            time.sleep_ms(10)
        return None

    def discover_stations(self):
        """Discover stations from DFPlayer SD card folder structure via UART queries.

        Queries the DFPlayer for total folder count (0x4F), then for each folder
        01..98 (skipping folder 99 reserved for AM WAV), queries the file count
        (0x4E). Stops early after 3 consecutive empty/missing folders since valid
        station folders are always numbered consecutively from 01.

        Error responses (0x40) from the DFPlayer for non-existent folders are
        treated as empty and suppressed from the console.

        Returns:
            List of dicts: [{"name": "Station 1", "folder": 1, "tracks": [...]}, ...]
        """
        print("BASIC: Discovering stations from DFPlayer SD card...")

        folder_count = self.query_folder_count()
        if folder_count is None:
            print("BASIC: Failed to query folder count (0x4F returned None)")
            return []
        print(f"BASIC: DFPlayer reports {folder_count} total folders (including root)")

        stations = []
        station_num = 0
        consecutive_empty = 0
        MAX_CONSECUTIVE_EMPTY = 3

        for folder in range(1, 99):
            file_count = self.query_files_in_folder(folder, suppress_errors=True)

            if file_count is None or file_count == 0:
                consecutive_empty += 1
                if consecutive_empty >= MAX_CONSECUTIVE_EMPTY:
                    print(f"BASIC: {MAX_CONSECUTIVE_EMPTY} consecutive empty folders, stopping scan at folder {folder:02d}")
                    break
                continue

            consecutive_empty = 0
            station_num += 1
            tracks = []
            for track_idx in range(1, file_count + 1):
                tracks.append({
                    "id": folder * 1000 + track_idx,
                    "title": f"Track {track_idx}",
                    "artist": "",
                    "duration": 0,
                    "folder": folder,
                    "track_number": track_idx,
                })

            station = {
                "id": folder,
                "name": f"Station {station_num}",
                "tracks": tracks,
            }
            stations.append(station)
            self._known_tracks[folder] = file_count
            print(f"BASIC: Station {station_num} -> folder {folder:02d}, {file_count} tracks")

        print(f"BASIC: Discovered {len(stations)} stations")
        return stations

    def get_last_error_code(self):
        """Return last DFPlayer error code (0x40) or None. Cleared when next error arrives."""
        return self._last_error_code
    
    # ===========================
    #   BUSY DETECTION
    # ===========================
    # We still need BUSY even with 2-way UART because play commands use feedback=False
    # (fire-and-forget). DFPlayer does not send ACK (0x41) for play. It may send 0x40
    # on error, but many clones do not send it reliably or send it late. BUSY is the
    # only definitive hardware signal that playback has actually started.
    
    def _wait_for_busy_low(self, timeout_ms=BUSY_CONFIRM_MS):
        """Wait for BUSY pin to go LOW (indicating playback started)."""
        start = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), start) < timeout_ms:
            if self.pin_busy.value() == 0:
                return True
            time.sleep_ms(25)
        return False
    
    def is_playing(self):
        """Return True if DFPlayer is currently playing."""
        return self.pin_busy.value() == 0
    
    def get_playback_position_ms(self):
        """Return current playback position (not supported by DFPlayer Mini)."""
        return 0
    
    # ===========================
    #   HardwareInterface IMPLEMENTATION
    # ===========================
    
    def play_track(self, folder, track, start_ms=0):
        """Play a track with optional seeking to start_ms position."""
        # If AM overlay is active, skip this call (start_with_am already started the track)
        if self._am_overlay_active:
            print(f"AM overlay active, skipping play_track (folder={folder}, track={track})")
            return True
        # Delay playback until firmware runs start_with_am() (mode switch / power-on)
        if self._delay_playback:
            print(f"Delay playback set, skipping play_track (folder={folder}, track={track})")
            return True
        
        print(f"play_track: Starting folder={folder}, track={track}, start_ms={start_ms}")
        self._df_stop()
        time.sleep_ms(POST_CMD_GUARD_MS)
        self._df_set_vol(self._df_volume)
        time.sleep_ms(POST_CMD_GUARD_MS)
        self._df_play_folder_track(folder, track)
        
        # Poll UART and BUSY in parallel: catch 0x40 errors (which may arrive late)
        # and wait for BUSY LOW (definitive playback confirmation)
        self._last_error_code = None
        confirmed = False
        start = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), start) < BUSY_CONFIRM_MS:
            self._df_read_pending()
            if self._last_error_code is not None:
                err_msg = DF_ERROR_MSGS.get(self._last_error_code, f"Unknown 0x{self._last_error_code:02X}")
                print(f"DF: play rejected (0x{self._last_error_code:02X}): {err_msg}")
                self.ignore_busy_until = time.ticks_add(time.ticks_ms(), 4000)
                return False
            if self.pin_busy.value() == 0:
                confirmed = True
                break
            time.sleep_ms(25)
        
        if confirmed:
            print("DF: BUSY went LOW -> playback started")
        elif self.query_status() == 1:
            confirmed = True
            print("DF: query_status -> playing")
        
        if confirmed:
            self._note_track_learned(folder, track)
            self.ignore_busy_until = time.ticks_add(time.ticks_ms(), 4000)
            if start_ms > 0:
                start_seconds = start_ms // 1000
                time.sleep_ms(80)
                self._df_set_time(start_seconds)
                print(f"DF: seeking to {start_seconds}s ({start_ms}ms)")
            return True
        
        print(f"DF: playback not confirmed (folder={folder}, track={track})")
        print(f"DF: Expected SD path: {folder:02d}/{track:03d}.mp3")
        if self._last_error_code is not None:
            err_msg = DF_ERROR_MSGS.get(self._last_error_code, f"Unknown 0x{self._last_error_code:02X}")
            print(f"DF: UART error received: 0x{self._last_error_code:02X} ({err_msg})")
        else:
            print("DF: No UART error received; BUSY stayed HIGH (DFPlayer may not have responded)")
            print("DF: Tip: If UART errors never appear, ensure DFPlayer TX is wired to Pico GP1 (UART RX)")
        self.ignore_busy_until = time.ticks_add(time.ticks_ms(), 4000)
        return False
    
    def stop(self):
        """Stop playback."""
        self._df_stop()
    
    def set_volume(self, level):
        """Set volume (0-100)."""
        self._volume = max(0, min(100, level))
        # Map 0-100 to 0-DFPLAYER_VOL for DFPlayer (capped at 28)
        self._df_volume = int((self._volume / 100.0) * DFPLAYER_VOL)
        self._df_set_vol(self._df_volume)
    
    def play_am_overlay(self):
        """Play AM radio sound with DFPlayer volume fade-in."""
        self._play_am_and_fade()
    
    def _play_am_and_fade(self, folder=None, track=None):
        """
        Play AM static sound overlaid on the music track fade-in.
        
        Two modes depending on whether the AM WAV is on Pico flash:
        
        MODE A — PWM overlay (wav_data loaded from Pico flash):
          Plays AM static through GPIO 3 PWM while simultaneously starting
          the music track on DFPlayer at low volume and fading it in.
          This gives a true "tuning in" effect where static and music overlap.
          
        MODE B — DFPlayer sequential (wav_data not available):
          Plays AM static from DFPlayer SD card (folder 99), then switches
          to the music track with a volume fade-in. Not a true overlay, but
          still provides the AM-then-music transition effect.
        """
        self._am_overlay_active = True
        
        self.np[0] = (0, 10, 0)
        self.np.write()
        
        # Match original baseline: set volume to 0 before AM overlay
        # (original start_sequence_synced and play_album_change_with_am both
        # call df_set_vol(0) before play_am_and_fade_df_confirming)
        self._df_set_vol(0)
        
        if self.wav_data is not None:
            confirmed = self._play_am_overlay_pwm(folder, track)
        else:
            confirmed = self._play_am_dfplayer_sequential(folder, track)
        
        self.np[0] = (0, 0, 0)
        self.np.write()
        
        self._am_overlay_active = False
        self._delay_playback = False
        self.ignore_busy_until = time.ticks_add(time.ticks_ms(), 4000)
        
        return confirmed
    
    def _play_am_overlay_pwm(self, folder=None, track=None):
        """MODE A: True overlay — AM static on GPIO PWM + DFPlayer music fade-in.
        
        Matches original baseline play_am_and_fade_df_confirming():
        - Volume already set to 0 by _play_am_and_fade() caller
        - df_stop() → guard → df_play_folder_track() (no extra set_vol before play)
        - Fade from 0 to DFPLAYER_VOL during AM playback
        """
        print("AM: PWM overlay mode (GPIO 3 + DFPlayer simultaneous)")
        
        # Start the music track on DFPlayer (volume already at 0 from caller)
        # Matches original: df_stop() → POST_CMD_GUARD_MS → df_play_folder_track()
        confirmed = False
        if folder is not None and track is not None:
            self._df_stop()
            time.sleep_ms(POST_CMD_GUARD_MS)
            print(f"AM: Starting music at volume 0 (folder={folder}, track={track})")
            self._df_play_folder_track(folder, track)
            # Give DFPlayer time to process the play command and begin reading
            # from SD card BEFORE starting the 8kHz Timer ISR. Without this,
            # the ISR can starve the CPU and interfere with DFPlayer startup.
            time.sleep_ms(300)
            # Check for DFPlayer errors (e.g. file not found)
            self._last_error_code = None
            self._df_read_pending()
            if self._last_error_code is not None:
                print(f"AM: DFPlayer error after play cmd: code={self._last_error_code}")
            # Check if BUSY already went LOW during that wait
            if self.pin_busy.value() == 0:
                confirmed = True
                print("AM: BUSY LOW -> music playing (confirmed before overlay)")
            else:
                print(f"AM: BUSY still HIGH after play cmd (pin={self.pin_busy.value()})")
        
        # Start PWM AM static sound simultaneously
        print("AM: Starting PWM static on GPIO", PIN_AUDIO)
        p = Pin(PIN_AUDIO)
        self.pwm = PWM(p)
        self.pwm.freq(PWM_CARRIER)
        self.pwm.duty_u16(MID)
        
        state = {"idx": 0, "n": len(self.wav_data), "done": False}
        
        # Fade out AM static near the end for smooth transition
        fade_out_s = 0.8
        fo = int(self.wav_sr * fade_out_s)
        if fo > state["n"]:
            fo = state["n"]
        state["fade_out_samples"] = fo
        
        self.tim = Timer()
        data = self.wav_data
        lut = self.lut
        
        def isr_cb(_t):
            idx = state["idx"]
            n = state["n"]
            if idx >= n:
                # Set to silence (midpoint = no audio) when done
                try:
                    self.pwm.duty_u16(MID)
                except:
                    pass
                state["done"] = True
                return
            raw_duty = lut[data[idx]]
            fo2 = state["fade_out_samples"]
            if fo2 > 0 and idx >= n - fo2:
                into = idx - (n - fo2)
                remaining = fo2 - into
                if remaining < 0:
                    remaining = 0
                scale_val = (remaining * 256) // fo2
                duty = MID + ((raw_duty - MID) * scale_val) // 256
            else:
                duty = raw_duty
            self.pwm.duty_u16(duty)
            state["idx"] = idx + 1
        
        self.tim.init(freq=self.wav_sr, mode=Timer.PERIODIC, callback=isr_cb)
        
        # Fade in DFPlayer volume while AM static plays
        # Matches original: df_set_vol(int((step / fade_steps) * DFPLAYER_VOL))
        fade_steps = 20
        fade_delay = int((FADE_IN_S * 1000) / fade_steps)
        if fade_delay < 40:
            fade_delay = 40
        
        try:
            for step in range(fade_steps + 1):
                # Match original: fade from 0 to DFPLAYER_VOL
                vol = int((step / fade_steps) * self._df_volume)
                self._df_set_vol(vol)
                
                t_start = time.ticks_ms()
                while time.ticks_diff(time.ticks_ms(), t_start) < fade_delay:
                    # Check BUSY throughout the entire overlay (no deadline)
                    # Some tracks take longer to start (e.g., larger files)
                    if not confirmed and self.pin_busy.value() == 0:
                        confirmed = True
                        print("AM: BUSY LOW -> music playing (confirmed during overlay)")
                    if state["done"]:
                        break
                    time.sleep_ms(10)
                
                if state["done"]:
                    break
            
            # Wait for AM WAV to finish if it hasn't yet, keep checking BUSY
            while not state["done"]:
                if not confirmed and self.pin_busy.value() == 0:
                    confirmed = True
                    print("AM: BUSY LOW -> music playing (confirmed late during overlay)")
                time.sleep_ms(20)
        
        finally:
            # CRITICAL: Fully shut down Timer and PWM to stop GPIO 3 from
            # injecting a 125kHz carrier signal into the amplifier during
            # normal DFPlayer playback. Leaving PWM active causes popping/noise.
            try:
                self.tim.deinit()
                self.tim = None
            except:
                pass
            try:
                self.pwm.deinit()
                self.pwm = None
            except:
                pass
            # Set GPIO 3 to input (high-impedance) so it doesn't drive
            # any signal into the amplifier after the overlay finishes
            try:
                Pin(PIN_AUDIO, Pin.IN)
            except:
                pass
        
        # Ensure volume is at target after fade
        self._df_set_vol(self._df_volume)
        print(f"AM: PWM overlay complete, vol={self._df_volume}, confirmed={confirmed}")
        # If BUSY never went LOW, retry play once (helps when nothing plays after AM on some hardware)
        if not confirmed and folder is not None and track is not None:
            print("AM: Playback not confirmed, retrying play command...")
            self._df_stop()
            time.sleep_ms(POST_CMD_GUARD_MS)
            self._df_play_folder_track(folder, track)
            if self._wait_for_busy_low(2000):
                confirmed = True
                print("AM: Retry confirmed (BUSY LOW)")
        return confirmed
    
    def _play_am_dfplayer_sequential(self, folder=None, track=None):
        """MODE B: Fallback — play AM from DFPlayer SD card, then switch to music.
        
        Volume already set to 0 by _play_am_and_fade() caller.
        Plays AM sound at current volume, then switches to music with fade-in.
        """
        print("AM: DFPlayer sequential mode (folder 99 on SD card)")
        
        # Play AM sound at full volume so it's audible
        self._df_stop()
        time.sleep_ms(POST_CMD_GUARD_MS)
        self._df_set_vol(self._df_volume)
        
        print(f"AM: Playing static sound (folder={self._am_folder}, track={self._am_track})")
        self._df_play_folder_track(self._am_folder, self._am_track)
        
        am_started = self._wait_for_busy_low()
        if am_started:
            print("AM: Static sound playing (BUSY confirmed)")
        else:
            print("AM: Static sound not confirmed (BUSY didn't go LOW)")
        
        time.sleep_ms(self._am_duration_ms)
        
        confirmed = False
        if folder is not None and track is not None:
            self._df_stop()
            time.sleep_ms(POST_CMD_GUARD_MS)
            
            # Start music at volume 0, then fade up (matches original approach)
            self._df_set_vol(0)
            time.sleep_ms(POST_CMD_GUARD_MS)
            
            print(f"AM: Switching to music (folder={folder}, track={track})")
            self._df_play_folder_track(folder, track)
            
            confirmed = self._wait_for_busy_low()
            if confirmed:
                print("AM: Music started (BUSY confirmed)")
            
            # Fade from 0 to DFPLAYER_VOL
            fade_steps = 15
            fade_delay = int((FADE_IN_S * 1000) / fade_steps)
            if fade_delay < 40:
                fade_delay = 40
            
            for step in range(1, fade_steps + 1):
                vol = int((step / fade_steps) * self._df_volume)
                self._df_set_vol(vol)
                time.sleep_ms(fade_delay)
            
            self._df_set_vol(self._df_volume)
            print(f"AM: Sequential complete, vol={self._df_volume}")
        else:
            self._df_stop()
        
        return confirmed
    
    def save_state(self, state_dict):
        """Persist state to SD card."""
        try:
            # Format compatible with old album_state.txt; optional ;mode= for shuffle/playlist/radio
            album_idx = state_dict.get('album_index', 0) + 1  # 1-based for DFPlayer folders
            track = state_dict.get('track', 1)
            known = state_dict.get('known_tracks', {})
            mode = state_dict.get('mode', 'album')
            
            track_str = ",".join("%d:%d" % (a, c) for a, c in sorted(known.items()))
            payload = f"{album_idx},{track};tracks={track_str};mode={mode}"
            
            with open(ALBUM_FILE, "w") as f:
                f.write(payload)
            print(f"Saved state: album={album_idx} (idx={album_idx-1}), track={track}, mode={mode}")
        except Exception as e:
            print(f"State save error: {e}")
    
    def load_state(self):
        """Load state from SD card."""
        state = {}
        
        # First try to load metadata
        self._load_metadata()
        
        # Then load saved state
        try:
            with open(ALBUM_FILE, "r") as f:
                raw = f.read().strip()
            print("Loaded raw album_state:", raw)
            
            parts = raw.split(";")
            a_str, t_str = parts[0].split(",")
            album_idx = int(a_str) - 1  # Convert to 0-based
            track = int(t_str)
            
            known_tracks = {}
            mode = 'album'
            for i in range(1, len(parts)):
                if parts[i].startswith("tracks="):
                    track_part = parts[i][7:]
                    if track_part:
                        for pair in track_part.split(","):
                            if not pair:
                                continue
                            a, c = pair.split(":")
                            known_tracks[int(a)] = int(c)
                elif parts[i].startswith("mode="):
                    mode = parts[i][5:].strip().lower()
                    if mode not in ('album', 'playlist', 'shuffle', 'radio'):
                        mode = 'album'
            
            state = {
                'mode': mode,
                'album_index': album_idx,
                'track': track,
                'known_tracks': known_tracks,
            }
            print(f"Loaded state: album_idx={album_idx} (folder={album_idx+1}), track={track}, mode={mode}, known_tracks={len(known_tracks)}")
            
        except Exception as e:
            print("No valid album_state.txt:", e)
            state = {
                'mode': 'album',
                'album_index': 0,
                'track': 1,
                'known_tracks': self._known_tracks,
            }
        
        return state
    
    def _load_metadata(self):
        """Load album/playlist metadata from radio_metadata.json."""
        # Prevent multiple loads
        if self._albums or self._playlists:
            print("Metadata already loaded, skipping")
            return
        
        # Mount SD if available (so /sd paths can be used)
        self._try_mount_sd()
        
        # Try multiple paths: SD card first (where it should be), then Pico flash
        metadata_paths = [
            "/sd/VintageRadio/radio_metadata.json",  # SD card (preferred)
            "/sd/radio_metadata.json",  # SD root (fallback)
            "VintageRadio/radio_metadata.json",  # Pico flash VintageRadio folder
            "radio_metadata.json",  # Pico flash root (fallback)
        ]
        
        data = None
        used_path = None
        
        for path in metadata_paths:
            try:
                print(f"Trying metadata path: {path}")
                with open(path, "r") as f:
                    data = json.load(f)
                    used_path = path
                    print(f"Successfully loaded metadata from {path}")
                    break
            except OSError as e:
                if e.args[0] == 2:  # ENOENT - file not found
                    continue  # Try next path
                else:
                    print(f"Error reading {path}: {e}")
                    continue
            except Exception as e:
                print(f"Error parsing {path}: {e}")
                continue
        
        if data is None:
            print("ERROR: Could not find radio_metadata.json in any location!")
            print("Tried paths:")
            for path in metadata_paths:
                print(f"  - {path}")
            print("\nPlease ensure:")
            print("  1. SD card is inserted and contains VintageRadio/radio_metadata.json")
            print("  2. Or copy radio_metadata.json to Pico flash memory")
            return
        
        try:
            # Load AM sound location from metadata
            am_sound = data.get("am_sound")
            if am_sound:
                self._am_folder = am_sound.get("folder", 99)
                self._am_track = am_sound.get("track", 1)
                print(f"AM sound: folder={self._am_folder:02d}, track={self._am_track:03d}")
            else:
                print("AM sound: not in metadata, using default folder=99, track=1")

            songs = data.get("songs", {})
            self._albums = []
            self._playlists = []
        except Exception as e:
            print("Error reading metadata header:", e)
            return

        # Helper: parse a list of collections (albums or playlists) from the
        # deduplicated format.  Each collection failure is logged but does not
        # prevent other collections from loading.
        def _parse_collections(collection_list, ctype):
            for col in (collection_list or []):
                try:
                    name = col.get("name", "Unknown")
                    col_id = col.get("id", 0)
                    tracks_data = col.get("tracks", [])
                    tracks = []
                    for idx, t in enumerate(tracks_data):
                        song_id = t.get("song_id", idx + 1)
                        song_data = songs.get(str(song_id), {})
                        folder = t.get("folder", song_data.get("folder", 1))
                        track_num = t.get("track", song_data.get("track", idx + 1))
                        tracks.append({
                            "id": song_id,
                            "title": song_data.get("title", f"Track {idx + 1}"),
                            "artist": song_data.get("artist", "Unknown"),
                            "duration": song_data.get("duration", 180),
                            "folder": folder,
                            "track_number": track_num,
                        })
                        prev = self._known_tracks.get(folder, 0)
                        if track_num > prev:
                            self._known_tracks[folder] = track_num
                    entry = {"id": col_id, "name": name, "tracks": tracks}
                    if ctype == "playlist":
                        self._playlists.append(entry)
                    else:
                        self._albums.append(entry)
                    label = "Album" if ctype == "album" else "Playlist"
                    print(f"  {label}: '{name}' - {len(tracks)} tracks")
                except Exception as e:
                    print(f"  ERROR loading {ctype} '{col.get('name', '?')}': {e}")

        # ── New deduplicated format: "albums" + "playlists" lists ──
        new_albums = data.get("albums")
        new_playlists = data.get("playlists")
        if new_albums is not None or new_playlists is not None:
            print(f"Deduplicated format: {len(new_albums or [])} albums, {len(new_playlists or [])} playlists, {len(songs)} songs")
            _parse_collections(new_albums, "album")
            _parse_collections(new_playlists, "playlist")
        else:
            # ── Legacy format: "folders" dict (one folder per album/playlist) ──
            folders = data.get("folders", {})
            print(f"Legacy format: {len(folders)} folders, {len(songs)} songs")
            if not folders:
                print("WARNING: No folders found in metadata!")
                return
            for folder_id_str, folder in folders.items():
                try:
                    folder_id = int(folder_id_str)
                except Exception:
                    print(f"Skipping invalid folder key: {folder_id_str}")
                    continue
                folder_type = folder.get("type", "album")
                name = folder.get("name", f"Folder {folder_id}")
                tracks_data = folder.get("tracks", [])
                tracks = []
                for idx, t in enumerate(tracks_data):
                    song_id = t.get("song_id", idx + 1)
                    song_data = songs.get(str(song_id), {})
                    tfolder = t.get("folder", folder_id)
                    ttrack = t.get("sd_track", t.get("track", idx + 1))
                    tracks.append({
                        "id": song_id,
                        "title": song_data.get("title", t.get("title", f"Track {idx + 1}")),
                        "artist": song_data.get("artist", t.get("artist", "Unknown")),
                        "duration": song_data.get("duration", t.get("duration", 180)),
                        "folder": tfolder,
                        "track_number": ttrack,
                    })
                entry = {"id": folder_id, "name": name, "tracks": tracks}
                if folder_type == "playlist":
                    self._playlists.append(entry)
                else:
                    self._albums.append(entry)
                if tracks:
                    self._known_tracks[folder_id] = len(tracks)
                    print(f"  Folder {folder_id:02d} ({folder_type}): '{name}' - {len(tracks)} tracks")

        print(f"Loaded metadata: {len(self._albums)} albums, {len(self._playlists)} playlists")
    
    def _note_track_learned(self, folder, track):
        """Note that a track was confirmed to play."""
        prev = self._known_tracks.get(folder, 0)
        if track > prev:
            self._known_tracks[folder] = track
            print("Learned track", track, "for folder", folder)
    
    def log(self, message):
        """Log a message."""
        print(message)
    
    def get_albums(self):
        """Return list of albums."""
        # Ensure metadata is loaded (lazy loading)
        if not self._albums and not self._playlists:
            self._load_metadata()
        return self._albums
    
    def get_playlists(self):
        """Return list of playlists."""
        # Ensure metadata is loaded (lazy loading)
        if not self._albums and not self._playlists:
            self._load_metadata()
        return self._playlists
    
    def get_all_tracks(self):
        """Return all unique tracks from all albums and playlists."""
        if not self._albums and not self._playlists:
            self._load_metadata()
        seen_ids = set()
        all_tracks = []
        for collection in self._albums + self._playlists:
            for track in collection.get('tracks', []):
                tid = track.get('id')
                if tid not in seen_ids:
                    seen_ids.add(tid)
                    all_tracks.append(track)
        return all_tracks
    
    # ===========================
    #   ADDITIONAL HARDWARE ACCESS
    # ===========================
    
    def is_power_on(self):
        """Check if power rail is on."""
        return self.power_sense.value() == 1
    
    def is_button_pressed(self):
        """Check if button is pressed (active low)."""
        return self.button.value() == 0
    
    def reset_dfplayer(self):
        """Reset DFPlayer and wait for boot."""
        self._df_reset()
        print("Waiting for DFPlayer boot:", DF_BOOT_MS, "ms")
        time.sleep_ms(DF_BOOT_MS)
    
    def test_play_track(self, folder, track):
        """Test playing a specific folder/track. Use from debug console: test_play_track(1, 1)"""
        print(f"\n=== Testing DFPlayer Play Command ===")
        print(f"Requested: folder={folder}, track={track}")
        print(f"Expected SD path: {folder:02d}/{track:03d}.mp3")
        
        # Validate
        if folder < 1 or folder > 99:
            print(f"ERROR: Folder must be 1-99, got {folder}")
            return False
        if track < 1 or track > 999:
            print(f"ERROR: Track must be 1-999, got {track}")
            return False
        
        # Stop current playback
        print("Stopping current playback...")
        self._df_stop()
        time.sleep_ms(200)
        
        # Send play command
        print(f"Sending play command: 0x0F (folder={folder}, track={track})")
        self._df_play_folder_track(folder, track)
        
        # Wait and check BUSY pin
        print("Waiting 1 second for BUSY pin response...")
        time.sleep_ms(1000)
        busy_state = self.pin_busy.value()
        print(f"BUSY pin state: {busy_state} (0=playing, 1=idle)")
        
        if busy_state == 0:
            print("✓ SUCCESS: BUSY pin is LOW - DFPlayer is playing!")
            return True
        else:
            print("✗ FAILED: BUSY pin is HIGH - DFPlayer is not playing")
            print("Possible issues:")
            print("  1. SD card not inserted or not readable")
            print(f"  2. File {folder:02d}/{track:03d}.mp3 does not exist on SD card")
            print("  3. DFPlayer not receiving UART commands (check wiring)")
            print("  4. DFPlayer power issue")
            return False
    
    def diagnose_dfplayer(self):
        """Comprehensive diagnostic function to test DFPlayer hardware and communication."""
        results = {}
        
        # Test 1: UART initialization
        try:
            uart_ok = self.uart is not None
            results['uart_initialized'] = uart_ok
            print(f"✓ UART initialized: {uart_ok}")
        except Exception as e:
            results['uart_initialized'] = False
            results['uart_error'] = str(e)
            print(f"✗ UART error: {e}")
        
        # Test 2: BUSY pin state
        try:
            busy_state = self.pin_busy.value()
            results['busy_pin'] = busy_state
            print(f"✓ BUSY pin: {busy_state} (0=playing, 1=idle)")
        except Exception as e:
            results['busy_pin'] = None
            results['busy_error'] = str(e)
            print(f"✗ BUSY pin error: {e}")
        
        # Test 3: Send reset command and check UART write
        try:
            print("Sending reset command...")
            busy_before = self.pin_busy.value()
            self._df_reset()
            busy_after = self.pin_busy.value()
            results['reset_sent'] = True
            results['busy_before_reset'] = busy_before
            results['busy_after_reset'] = busy_after
            results['busy_changed'] = busy_before != busy_after
            print(f"✓ Reset sent - BUSY: {busy_before} → {busy_after} (changed: {busy_before != busy_after})")
        except Exception as e:
            results['reset_sent'] = False
            results['reset_error'] = str(e)
            print(f"✗ Reset error: {e}")
        
        # Test 4: Send volume command
        try:
            print("Sending volume command...")
            self._df_set_vol(DFPLAYER_VOL)
            results['volume_sent'] = True
            print("✓ Volume command sent")
        except Exception as e:
            results['volume_sent'] = False
            results['volume_error'] = str(e)
            print(f"✗ Volume error: {e}")
        
        # Test 5: Wait and check BUSY pin again
        time.sleep_ms(1000)
        try:
            busy_final = self.pin_busy.value()
            results['busy_final'] = busy_final
            print(f"✓ Final BUSY pin: {busy_final}")
        except Exception as e:
            results['busy_final'] = None
            results['busy_final_error'] = str(e)
            print(f"✗ Final BUSY error: {e}")
        
        # Test 6: Try to read from UART (DFPlayer might send status)
        try:
            uart_available = self.uart.any()
            results['uart_available'] = uart_available
            if uart_available > 0:
                uart_data = self.uart.read(uart_available)
                results['uart_data'] = [hex(b) for b in uart_data] if uart_data else []
                print(f"✓ UART has {uart_available} bytes available: {results['uart_data']}")
            else:
                print(f"✓ UART has no data waiting (DFPlayer not responding)")
        except Exception as e:
            results['uart_read_error'] = str(e)
            print(f"✗ UART read error: {e}")
        
        # Test 7: Try to play a track to see if DFPlayer responds
        try:
            print("Attempting to play folder 1, track 1...")
            self._df_send(0x0F, 0x01, 0x01)
            time.sleep_ms(500)
            busy_after_play = self.pin_busy.value()
            results['play_attempted'] = True
            results['busy_after_play'] = busy_after_play
            results['busy_changed_after_play'] = busy_final != busy_after_play
            print(f"✓ Play command sent - BUSY: {busy_final} → {busy_after_play} (changed: {busy_final != busy_after_play})")
        except Exception as e:
            results['play_attempted'] = False
            results['play_error'] = str(e)
            print(f"✗ Play error: {e}")
        
        # Test 8: Two-way UART queries (status, current track, file count, last error)
        try:
            print("Querying status (0x42)...")
            st = self.query_status()
            results['query_status'] = st
            print("✓ query_status:", "playing" if st == 1 else "stopped" if st == 0 else "timeout")
            print("Querying current track (0x4C)...")
            ct = self.query_current_track()
            results['query_current_track'] = ct
            print("✓ query_current_track:", ct if ct is not None else "timeout")
            print("Querying TF file count (0x48)...")
            fc = self.query_file_count()
            results['query_file_count'] = fc
            print("✓ query_file_count:", fc if fc is not None else "timeout")
            err = self.get_last_error_code()
            results['last_error_code'] = err
            if err is not None:
                print("✓ Last DF error code:", err)
        except Exception as e:
            results['query_error'] = str(e)
            print(f"✗ Query error: {e}")
        
        print("\n=== Diagnostic Summary ===")
        print(f"UART initialized: {results.get('uart_initialized', False)}")
        print(f"Reset sent: {results.get('reset_sent', False)}")
        print(f"Volume sent: {results.get('volume_sent', False)}")
        print(f"BUSY pin changed after reset: {results.get('busy_changed', False)}")
        print(f"BUSY pin changed after play: {results.get('busy_changed_after_play', False)}")
        print(f"UART data available: {results.get('uart_available', 0)} bytes")
        
        # Determine likely issue
        if results.get('uart_initialized') and results.get('reset_sent') and not results.get('busy_changed'):
            print("\n⚠️  DIAGNOSIS: Commands are being sent but DFPlayer is NOT responding")
            print("   This indicates one of the following:")
            print("   1. WIRING ISSUE:")
            print("      - Verify: Pico GP0 (TX) → DFPlayer RX")
            print("      - Verify: Pico GP1 (RX) → DFPlayer TX")
            print("      - Check for loose connections")
            print("   2. POWER ISSUE:")
            print("      - DFPlayer needs 3.3V or 5V (check module specs)")
            print("      - Verify VCC and GND connections")
            print("      - Check if DFPlayer LED lights up at all (even briefly)")
            print("   3. SD CARD MISSING:")
            print("      - Some DFPlayer modules require SD card to initialize")
            print("      - Insert formatted SD card (FAT32)")
            print("   4. DEFECTIVE DFPLAYER:")
            print("      - If wiring and power are correct, module may be defective")
            print("      - Try a different DFPlayer module if available")
        
        return results
    
    def start_with_am(self, folder, track):
        """Start playback with AM static sound overlay and volume fade-in.
        
        If AMradioSound.wav is loaded on Pico flash: true overlay via PWM on
        GPIO 3 playing simultaneously with DFPlayer music fade-in.
        
        If not loaded: sequential fallback via DFPlayer SD card (folder 99).
        """
        return self._play_am_and_fade(folder, track)
    
    def check_busy_edge(self):
        """Check for BUSY rising edge (track finished)."""
        now = time.ticks_ms()
        if time.ticks_diff(now, self.ignore_busy_until) < 0:
            return False
        return not self.is_playing()
