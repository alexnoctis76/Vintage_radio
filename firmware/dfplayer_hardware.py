"""
DFPlayer Hardware Interface for MicroPython

This module implements the HardwareInterface from radio_core.py
for the actual DFPlayer Mini hardware on the Raspberry Pi Pico.

This allows the firmware to run the exact same logic as the GUI test mode.
"""

from machine import Pin, PWM, Timer, UART
import neopixel
import ustruct
import time

# Try to import json
try:
    import ujson as json
except ImportError:
    import json

# Import shared constants and interface from radio_core
from radio_core import HardwareInterface, FADE_IN_S, DF_BOOT_MS

# ===========================
#      PIN CONFIGURATION
# ===========================

PIN_AUDIO       = 3
PIN_BUTTON      = 2
PIN_NEOPIX      = 16
PIN_UART_TX     = 0
PIN_UART_RX     = 1
PIN_SENSE       = 14      # power sense from Rail 2
PIN_BUSY        = 15      # DFPlayer BUSY (0 = playing, 1 = idle)

# ===========================
#      CONSTANTS
# ===========================

DFPLAYER_VOL    = 28
VOLUME_SCALE    = 1.0
WAV_FILE        = "VintageRadio/AMradioSound.wav"
PWM_CARRIER     = 125_000
ALBUM_FILE      = "VintageRadio/album_state.txt"
METADATA_FILE   = "VintageRadio/radio_metadata.json"

BUSY_CONFIRM_MS = 1800
POST_CMD_GUARD_MS = 120
ALBUM_PROBE_MS  = 650

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
    - PWM audio output for AM overlay
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
        
        self.pwm = None
        self.tim = None
        
        # Volume
        self._volume = 100
        self._df_volume = DFPLAYER_VOL
        
        # Ignore BUSY edges after manual skips
        self.ignore_busy_until = 0
        
        # Load WAV data for AM overlay
        self.wav_data = None
        self.wav_sr = 8000
        self.lut = None
        self._load_wav()
        
        # Cached metadata
        self._albums = []
        self._playlists = []
        self._all_tracks = []
        self._known_tracks = {}
        
        # Flag to prevent duplicate playback when AM overlay is playing
        self._am_overlay_active = False
    
    def _load_wav(self):
        """Load the AM radio WAV file."""
        try:
            print("Loading WAV:", WAV_FILE)
            self.wav_data, self.wav_sr = load_wav_u8(WAV_FILE)
            
            # Build lookup table
            self.lut = [0] * 256
            scale = int(256 * VOLUME_SCALE)
            for i in range(256):
                d = MID + (i - 128) * scale
                d = max(0, min(65535, d))
                self.lut[i] = d
            print("WAV loaded successfully")
        except Exception as e:
            print("WAV load error:", e)
            self.wav_data = None
    
    # ===========================
    #   DFPLAYER COMMANDS
    # ===========================
    
    def _df_send(self, cmd, p1=0, p2=0):
        """Send a command to DFPlayer."""
        pkt = bytearray([0x7E, 0xFF, 0x06, cmd, 0x00, p1 & 0xFF, p2 & 0xFF])
        csum = -sum(pkt[1:7]) & 0xFFFF
        pkt.append((csum >> 8) & 0xFF)
        pkt.append(csum & 0xFF)
        pkt.append(0xEF)
        self.uart.write(pkt)
        time.sleep_ms(30)
    
    def _df_reset(self):
        """Reset DFPlayer."""
        print("DF: RESET")
        self._df_send(0x3F, 0x00, 0x00)
        time.sleep_ms(800)
    
    def _df_set_vol(self, v):
        """Set DFPlayer volume (0-30)."""
        v = max(0, min(30, v))
        print("DF: set volume", v)
        self._df_send(0x06, 0x00, v)
    
    def _df_play_folder_track(self, folder, track):
        """Play a specific folder/track on DFPlayer."""
        print("DF: play folder", folder, "track", track)
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
    #   BUSY DETECTION
    # ===========================
    
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
            print("AM overlay active, skipping play_track (already started via start_with_am)")
            return True
        
        self._df_stop()
        time.sleep_ms(POST_CMD_GUARD_MS)
        self._df_play_folder_track(folder, track)
        
        # Wait for playback to start
        if self._wait_for_busy_low():
            print("BUSY went LOW -> playback started")
            self._note_track_learned(folder, track)
            self.ignore_busy_until = time.ticks_add(time.ticks_ms(), 2000)
            
            # If start_ms > 0, seek to that position
            if start_ms > 0:
                start_seconds = start_ms // 1000
                time.sleep_ms(100)  # Small delay to ensure playback has started
                self._df_set_time(start_seconds)
                print(f"DF: seeking to {start_seconds}s ({start_ms}ms)")
            
            return True
        
        print("No BUSY LOW -> not confirmed")
        return False
    
    def stop(self):
        """Stop playback."""
        self._df_stop()
    
    def set_volume(self, level):
        """Set volume (0-100)."""
        self._volume = max(0, min(100, level))
        # Map 0-100 to 0-30 for DFPlayer
        self._df_volume = int((self._volume / 100.0) * 30)
        self._df_set_vol(self._df_volume)
    
    def play_am_overlay(self):
        """Play AM radio sound with DFPlayer volume fade-in."""
        self._play_am_and_fade()
    
    def _play_am_and_fade(self, folder=None, track=None):
        """
        Play AM WAV while fading in DFPlayer volume.
        If folder/track provided, also starts that track.
        """
        if self.wav_data is None:
            self.log("No WAV data - skipping AM overlay")
            return False
        
        # Set flag to prevent duplicate playback from RadioCore's play_track()
        self._am_overlay_active = True
        
        if folder and track:
            self._df_stop()
            time.sleep_ms(POST_CMD_GUARD_MS)
            self._df_play_folder_track(folder, track)
        
        self.np[0] = (0, 10, 0)
        self.np.write()
        
        print("RP: starting AM WAV (synced)")
        
        p = Pin(PIN_AUDIO)
        self.pwm = PWM(p)
        self.pwm.freq(PWM_CARRIER)
        self.pwm.duty_u16(MID)
        
        state = {"idx": 0, "n": len(self.wav_data), "done": False}
        
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
                self.pwm.duty_u16(MID)
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
        
        fade_steps = 20
        fade_delay = int((FADE_IN_S * 1000) / fade_steps)
        if fade_delay < 40:
            fade_delay = 40
        
        confirmed = False
        confirm_deadline = time.ticks_add(time.ticks_ms(), BUSY_CONFIRM_MS)
        
        try:
            for step in range(fade_steps + 1):
                self._df_set_vol(int((step / fade_steps) * self._df_volume))
                
                t_start = time.ticks_ms()
                while time.ticks_diff(time.ticks_ms(), t_start) < fade_delay:
                    if (not confirmed) and (time.ticks_diff(time.ticks_ms(), confirm_deadline) <= 0):
                        if self.pin_busy.value() == 0:
                            confirmed = True
                            print("BUSY went LOW -> playback started (confirmed during AM)")
                    if state["done"]:
                        break
                    time.sleep_ms(10)
                
                if state["done"]:
                    break
            
            while not state["done"]:
                if (not confirmed) and (time.ticks_diff(time.ticks_ms(), confirm_deadline) <= 0):
                    if self.pin_busy.value() == 0:
                        confirmed = True
                        print("BUSY went LOW -> playback started (confirmed during AM)")
                time.sleep_ms(20)
        
        finally:
            try:
                self.tim.deinit()
            except:
                pass
            try:
                self.pwm.duty_u16(MID)
            except:
                pass
            self.np[0] = (0, 0, 0)
            self.np.write()
            print("RP: AM WAV done")
        
        # After AM overlay finishes, fade in the track volume if a track was started
        if folder and track and confirmed:
            # Track is already playing (started during AM overlay)
            # Now fade in the volume from 0 to target volume
            print("RP: Fading in track volume after AM overlay")
            track_fade_steps = 20
            track_fade_delay = int((FADE_IN_S * 1000) / track_fade_steps)
            if track_fade_delay < 40:
                track_fade_delay = 40
            
            for step in range(track_fade_steps + 1):
                fade_vol = int((step / track_fade_steps) * self._df_volume)
                self._df_set_vol(fade_vol)
                time.sleep_ms(track_fade_delay)
            
            print("RP: Track fade-in complete")
        
        # Clear flag after AM overlay finishes
        self._am_overlay_active = False
        
        return confirmed
    
    def save_state(self, state_dict):
        """Persist state to SD card."""
        try:
            # Format compatible with old album_state.txt
            album_idx = state_dict.get('album_index', 0) + 1  # 1-based for DFPlayer folders
            track = state_dict.get('track', 1)
            known = state_dict.get('known_tracks', {})
            
            track_str = ",".join("%d:%d" % (a, c) for a, c in sorted(known.items()))
            payload = f"{album_idx},{track};tracks={track_str}"
            
            with open(ALBUM_FILE, "w") as f:
                f.write(payload)
            print("Saved state:", payload)
        except Exception as e:
            print("State save error:", e)
    
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
            if len(parts) > 1 and parts[1].startswith("tracks="):
                track_part = parts[1][7:]
                if track_part:
                    for pair in track_part.split(","):
                        if not pair:
                            continue
                        a, c = pair.split(":")
                        known_tracks[int(a)] = int(c)
            
            state = {
                'mode': 'album',
                'album_index': album_idx,
                'track': track,
                'known_tracks': known_tracks,
            }
            print("Loaded state: album", album_idx, "track", track)
            
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
        try:
            with open(METADATA_FILE, "r") as f:
                data = json.load(f)
            
            folders = data.get("folders", {})
            self._albums = []
            self._playlists = []
            
            for folder_id_str, folder in folders.items():
                try:
                    folder_id = int(folder_id_str)
                except:
                    continue
                
                folder_type = folder.get("type", "album")
                name = folder.get("name", f"Folder {folder_id}")
                tracks_data = folder.get("tracks", [])
                
                tracks = []
                for idx, t in enumerate(tracks_data):
                    track = {
                        'id': t.get('song_id', idx + 1),
                        'title': t.get('title', f'Track {idx + 1}'),
                        'artist': t.get('artist', 'Unknown'),
                        'duration': t.get('duration', 180),
                        'folder': folder_id,
                        'track_number': t.get('track', idx + 1),
                    }
                    tracks.append(track)
                
                entry = {
                    'id': folder_id,
                    'name': name,
                    'tracks': tracks,
                }
                
                if folder_type == "playlist":
                    self._playlists.append(entry)
                else:
                    self._albums.append(entry)
                
                # Record known track count
                if tracks:
                    self._known_tracks[folder_id] = len(tracks)
            
            print("Loaded metadata:", len(self._albums), "albums,", len(self._playlists), "playlists")
            
        except Exception as e:
            print("No valid radio_metadata.json:", e)
    
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
        return self._albums
    
    def get_playlists(self):
        """Return list of playlists."""
        return self._playlists
    
    def get_all_tracks(self):
        """Return all tracks from all albums."""
        all_tracks = []
        for album in self._albums:
            all_tracks.extend(album.get('tracks', []))
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
    
    def start_with_am(self, folder, track):
        """Start playback with AM overlay and volume fade-in."""
        self._df_set_vol(0)
        return self._play_am_and_fade(folder, track)
    
    def check_busy_edge(self):
        """Check for BUSY rising edge (track finished)."""
        now = time.ticks_ms()
        if time.ticks_diff(now, self.ignore_busy_until) < 0:
            return False
        return not self.is_playing()

