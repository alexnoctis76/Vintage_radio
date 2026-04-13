# VS1053B hardware driver for Vintage Radio
# Drop-in replacement for DFPlayer when deployed as components/dfplayer_hardware.py
#
# How to use in the app: Pin Configuration -> Custom Hardware Driver -> Browse to this file,
# then Install Firmware. The GUI deploys it as the active driver.
#
# Wiring (defaults): RP2040 SPI0 valid pins - GP6=SCK, GP7=MOSI, GP4=MISO
#   GP5=XCS, GP8=XDCS, GP15=SDCS (CARDCS), GP27=DREQ, GP28=XRST
# Override in pin_config.json "pins": { "vs1053_sck": 6, "vs1053_mosi": 7, "vs1053_miso": 4, ... }
# Audio: stream from Pico SD (e.g. /sd/01/001.mp3) to VS1053 over SPI
#
# pyright: reportMissingImports=false, reportAttributeAccessIssue=false, reportUnboundVariable=false
# (Runs on MicroPython; ustruct, machine, ujson, neopixel, sdcard, time.sleep_ms, os.mount are device-only.)

import time
import ustruct
from machine import Pin, SPI

try:
    import ujson as json
except ImportError:
    import json

from machine import PWM, Timer

from radio_core import HardwareInterface

# --- Timer-driven AM PWM (sample-rate updates, independent of VS1053 loop) ---
_am_irq_buf = None
_am_irq_pos = 0
_am_irq_len = 0
_am_irq_fade_start = 0
_am_irq_pwm = None
_am_irq_timer = None
_am_irq_done = False
_am_irq_stride = 4


def _am_pwm_irq_callback(t):
    """Batched samples per tick (stride 2-4) so IRQ rate is ~2kHz, not 8kHz — VS1053 can keep up."""
    global _am_irq_pos, _am_irq_done
    p = _am_irq_pos
    n = _am_irq_len
    pwm = _am_irq_pwm
    if pwm is None:
        return
    if p >= n:
        try:
            t.deinit()
        except Exception:
            pass
        pwm.duty_u16(0)
        _am_irq_done = True
        return
    buf = _am_irq_buf
    st = _am_irq_stride
    end = p + st
    if end > n:
        end = n
    acc = 0
    c = end - p
    i = p
    while i < end:
        acc += buf[i]
        i += 1
    s = acc // c
    pmid = p + c // 2
    fs = _am_irq_fade_start
    if pmid < fs:
        v = 1000
    else:
        rng = n - fs
        v = (1000 * (n - pmid) // rng) if rng > 0 else 0
    d = s - 128
    g = AM_PWM_GAIN
    out = d * v * g // 100000 + 128
    if out < 0:
        out = 0
    elif out > 255:
        out = 255
    pwm.duty_u16(out << 8)
    _am_irq_pos = end


def _am_pwm_timer_start(samples, sample_rate_hz, fade_style):
    """fade_style: 0=full level to end, 1=fade last 40%% (standalone), 2=50%% crossfade tail."""
    global _am_irq_buf, _am_irq_pos, _am_irq_len, _am_irq_fade_start
    global _am_irq_pwm, _am_irq_timer, _am_irq_done, _am_irq_stride
    _am_pwm_timer_stop()
    n = len(samples)
    _am_irq_buf = samples
    _am_irq_pos = 0
    _am_irq_len = n
    if fade_style == 2:
        _am_irq_fade_start = n // 2
    elif fade_style == 1:
        _am_irq_fade_start = n * 3 // 5
    else:
        _am_irq_fade_start = n
    _am_irq_done = False
    _am_irq_stride = 4
    irq_hz = sample_rate_hz // _am_irq_stride
    if irq_hz < 900:
        _am_irq_stride = 2
        irq_hz = sample_rate_hz // 2
    if irq_hz < 500:
        _am_irq_stride = 1
        irq_hz = sample_rate_hz
    _am_irq_pwm = PWM(Pin(PIN_AUDIO), freq=62500)
    _am_irq_pwm.duty_u16(32768)
    _am_irq_timer = None
    last_err = None
    for factory in (lambda: Timer(1), lambda: Timer(0), lambda: Timer()):
        try:
            _am_irq_timer = factory()
            _am_irq_timer.init(
                freq=irq_hz, mode=Timer.PERIODIC, callback=_am_pwm_irq_callback
            )
            break
        except Exception as e:
            last_err = e
            _am_irq_timer = None
    if _am_irq_timer is None:
        try:
            _am_irq_pwm.deinit()
        except Exception:
            pass
        _am_irq_pwm = None
        print("VS1053: AM Timer failed:", last_err)
        raise last_err


def _am_pwm_timer_stop():
    global _am_irq_timer, _am_irq_pwm, _am_irq_done
    if _am_irq_timer is not None:
        try:
            _am_irq_timer.deinit()
        except Exception:
            pass
        _am_irq_timer = None
    if _am_irq_pwm is not None:
        try:
            _am_irq_pwm.duty_u16(0)
            _am_irq_pwm.deinit()
        except Exception:
            pass
        _am_irq_pwm = None
    try:
        Pin(PIN_AUDIO, Pin.OUT).value(0)
    except Exception:
        pass
    _am_irq_done = True

try:
    from sdcard import SDCard
    _SD_AVAILABLE = True
except ImportError:
    _SD_AVAILABLE = False

# Pin config: same paths as DFPlayer (works when run as components/dfplayer_hardware.py on device)
try:
    from pin_config_loader import load_pin_config, get_pin, get_spi_config
except ImportError:
    load_pin_config = lambda: {}
    get_pin = lambda name, default: default
    get_spi_config = lambda alt: {} if alt else {}

import os

_pins = load_pin_config().get("pins", {})

# VS1053 pins (defaults: valid RP2040 SPI0 set 6,7,4; override in pin_config.json)
PIN_VS1053_SCK = _pins.get("vs1053_sck", 6)
PIN_VS1053_MOSI = _pins.get("vs1053_mosi", 7)
PIN_VS1053_MISO = _pins.get("vs1053_miso", 4)
PIN_VS1053_XCS = _pins.get("vs1053_xcs", 5)
PIN_VS1053_XDCS = _pins.get("vs1053_xdcs", 8)
PIN_VS1053_DREQ = _pins.get("vs1053_dreq", 27)
PIN_VS1053_XRST = _pins.get("vs1053_xrst", 28)
PIN_VS1053_SDCS = _pins.get("vs1053_sdcs", 15)

PIN_BUTTON = _pins.get("button", 2)
PIN_SENSE = _pins.get("power_sense", 26)
# Default 16 = onboard RGB on Pico/Waveshare RP2040-Zero; use pin_config to override (e.g. 25)
PIN_NEOPIX = _pins.get("neopixel", 16)
PIN_AUDIO = _pins.get("audio_pwm", 3)
# Volume potentiometer ADC pin (-1 = disabled by default).
# GP29 on RP2040 reads VSYS, NOT a pot, so it must be disabled unless a pot is actually wired to an ADC pin.
PIN_VOL_ADC = _pins.get("volume_adc", -1)
# True = AM on GP3 + MP3 together (~2kHz IRQ, batched samples). False = codec-only AM then music.
AM_PWM_SIMULTANEOUS_WITH_MUSIC = bool(_pins.get("am_pwm_simultaneous", True))

# VS1053 SCI registers
SCI_MODE = 0x0
SCI_STATUS = 0x1
SCI_CLOCKF = 0x3
SCI_DECODE_TIME = 0x4
SCI_VOL = 0xB
SM_RESET = 0x0004
SM_CANCEL = 0x0008
SM_SDINEW = 0x0800

ALBUM_FILE = "VintageRadio/album_state.txt"
METADATA_PATHS = [
    "/sd/radio_metadata.json",
    "/sd/VintageRadio/radio_metadata.json",
    "VintageRadio/radio_metadata.json",
    "radio_metadata.json",
]
# Software gain for AM PWM output (GP3). 100=unity, 180=1.8x louder. Tune if AM is too quiet.
AM_PWM_GAIN = 180
AM_SOUND_PATHS = [
    "/sd/VintageRadio/AMradioSound.mp3",
    "/sd/VintageRadio/AMradioSound.wav",
    "/sd/AMradioSound.mp3",
    "/sd/AMradioSound.wav",
    "VintageRadio/AMradioSound.mp3",
    "VintageRadio/AMradioSound.wav",
    "AMradioSound.mp3",
    "AMradioSound.wav",
]



def _wait_dreq(pin_dreq, timeout_ms=500):
    t0 = time.ticks_ms()
    while pin_dreq.value() == 0:
        if time.ticks_diff(time.ticks_ms(), t0) > timeout_ms:
            return False
        time.sleep_ms(1)
    return True


def load_wav_u8(path):
    """Load WAV and return (samples_bytes, sample_rate)."""
    with open(path, "rb") as f:
        if f.read(4) != b"RIFF":
            raise ValueError("Not RIFF")
        f.read(4)
        if f.read(4) != b"WAVE":
            raise ValueError("Not WAVE")
        sr = 8000
        while True:
            cid = f.read(4)
            if not cid:
                raise ValueError("No data chunk")
            clen = ustruct.unpack("<I", f.read(4))[0]
            if cid == b"fmt ":
                fmt = f.read(clen)
                sr = ustruct.unpack("<I", fmt[4:8])[0]
            elif cid == b"data":
                data = f.read(clen)
                break
            else:
                f.seek(clen, 1)
    return data, sr


class VS1053Hardware(HardwareInterface):
    """Hardware implementation using VS1053B over SPI. Streams audio from Pico SD/flash."""

    def __init__(self):
        self._xcs = Pin(PIN_VS1053_XCS, Pin.OUT, value=1)
        self._xdcs = Pin(PIN_VS1053_XDCS, Pin.OUT, value=1)
        self._dreq = Pin(PIN_VS1053_DREQ, Pin.IN)
        self._xrst = Pin(PIN_VS1053_XRST, Pin.OUT, value=0)

        # 2MHz: reliable over shared bus with Adafruit breakout level shifters + breadboard wiring.
        # Still 5x faster than needed for 320kbps MP3 (40KB/s vs 250KB/s).
        self._spi_hz = 2_000_000
        self.spi = SPI(0, baudrate=self._spi_hz, sck=Pin(PIN_VS1053_SCK), mosi=Pin(PIN_VS1053_MOSI), miso=Pin(PIN_VS1053_MISO))

        # NeoPixel (main.py expects self.np)
        self._onboard_np = None  # Optional: GP16 onboard LED on Pico/RP2040-Zero when config uses another pin
        try:
            import neopixel
            self.np = neopixel.NeoPixel(Pin(PIN_NEOPIX), 1)
            self.np[0] = (4, 4, 4)
            self.np.write()
            if PIN_NEOPIX != 16:
                try:
                    self._onboard_np = neopixel.NeoPixel(Pin(16), 1)
                except Exception:
                    pass
        except Exception:
            self.np = None

        self.button = Pin(PIN_BUTTON, Pin.IN, Pin.PULL_UP)
        self.power_sense = Pin(PIN_SENSE, Pin.IN, Pin.PULL_DOWN)
        Pin(PIN_AUDIO, Pin.IN)

        # Full digital volume: let the analog pot in the audio path handle attenuation.
        self._volume = 100
        self._vol_adc = None
        self._vol_adc_last_ms = 0
        self._vol_smoothed = 65535  # start at max
        if PIN_VOL_ADC >= 0:
            try:
                from machine import ADC
                self._vol_adc = ADC(Pin(PIN_VOL_ADC))
                print("VS1053: Volume ADC on GP{}".format(PIN_VOL_ADC))
            except Exception as e:
                print("VS1053: Volume ADC init failed:", e)
        self._playing = False
        self._stream_file = None
        self._stream_buf = bytearray(4096)
        self._stream_buf_pos = 0
        self._stream_buf_len = 0
        self._zero32 = bytearray(32)
        self._albums = []
        self._playlists = []
        self._all_tracks = []
        self._known_tracks = {}
        self._am_folder = 99
        self._am_track = 1
        self._delay_playback = False
        self._am_overlay_active = False
        self.wav_data = None
        self._decode_time_sec = 0
        self.ignore_busy_until = 0
        self._end_fill_remaining = 0
        self._path_cache = None

        # Release VS1053 from hardware reset before SD init so it doesn't float MISO on the shared SPI bus
        self._xrst.value(0)
        time.sleep_ms(10)
        self._xrst.value(1)
        time.sleep_ms(100)
        # Deselect VS1053 SCI/SDI so only SDCS talks during SD init
        self._xcs.value(1)
        self._xdcs.value(1)

        self._try_mount_sd()
        self._vs1053_reset()
        self.set_volume(self._volume)
        self._load_am_wav()
        self._load_metadata()
        # Ready = green (so onboard LED matches playback state)
        try:
            if self.np is not None:
                self.np[0] = (0, 10, 0)
                self.np.write()
            if self._onboard_np is not None:
                self._onboard_np[0] = (0, 10, 0)
                self._onboard_np.write()
        except Exception:
            pass

    def _try_mount_sd(self):
        """Mount the onboard SD card on the VS1053 breakout (shares SPI bus, separate CARDCS pin)."""
        if not _SD_AVAILABLE:
            print("VS1053: sdcard module not found (copy sdcard.py to Pico for SD support)")
            return
        if "sd" in os.listdir("/"):
            print("VS1053: SD already mounted at /sd")
            return
        self._xcs.value(1)
        self._xdcs.value(1)
        cs = Pin(PIN_VS1053_SDCS, Pin.OUT, value=1)
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                # Fresh SPI at 400kHz with explicit mode 0 for SD init
                self.spi.init(baudrate=400_000, polarity=0, phase=0)
                time.sleep_ms(50)
                sd = SDCard(self.spi, cs)
                os.mount(sd, "/sd")
                self.spi.init(baudrate=self._spi_hz)
                print("VS1053: SD mounted at /sd (onboard, SDCS=GP{}, attempt {})".format(PIN_VS1053_SDCS, attempt))
                return
            except Exception as e:
                self.spi.init(baudrate=self._spi_hz)
                print("VS1053: SD attempt {}/{} failed: {}".format(attempt, max_attempts, e))
                if attempt < max_attempts:
                    time.sleep_ms(200)
        print("VS1053: SD mount failed after {} attempts".format(max_attempts))

    def _recover_sd(self):
        """Attempt to remount SD after a read error so subsequent tracks can still play."""
        print("VS1053: attempting SD recovery...")
        # Fully deselect all devices
        self._xcs.value(1)
        self._xdcs.value(1)
        # Hardware-reset VS1053 to release any SPI bus contention
        self._xrst.value(0)
        time.sleep_ms(10)
        self._xrst.value(1)
        time.sleep_ms(100)
        self._xcs.value(1)
        self._xdcs.value(1)
        try:
            os.umount("/sd")
        except Exception:
            pass
        # Re-init SPI cleanly at low speed for SD card init
        self.spi.init(baudrate=400_000, polarity=0, phase=0)
        time.sleep_ms(100)
        cs = Pin(PIN_VS1053_SDCS, Pin.OUT, value=1)
        for attempt in range(1, 4):
            try:
                self.spi.init(baudrate=400_000, polarity=0, phase=0)
                time.sleep_ms(50)
                sd = SDCard(self.spi, cs)
                os.mount(sd, "/sd")
                self.spi.init(baudrate=self._spi_hz)
                print("VS1053: SD recovered (attempt {})".format(attempt))
                self._vs1053_reset()
                self._xcs.value(1)
                self._xdcs.value(1)
                self.spi.init(baudrate=self._spi_hz, polarity=0, phase=0)
                self.set_volume(self._volume)
                return
            except Exception as e:
                self.spi.init(baudrate=self._spi_hz)
                if attempt < 3:
                    time.sleep_ms(200)
                else:
                    print("VS1053: SD recovery failed after 3 attempts:", e)

    def _vs1053_reset(self):
        self._write_sci(SCI_MODE, SM_RESET)
        time.sleep_ms(1)
        if not _wait_dreq(self._dreq, 500):
            print("VS1053: DREQ timeout after reset")
        self._write_sci(SCI_MODE, SM_SDINEW)
        # 0x8800 = 2x multiplier for 12.288 MHz (conservative); 0x9800 = 4x. Use 0x9800 for higher bitrates.
        self._write_sci(SCI_CLOCKF, 0x9800)
        self._write_sci(SCI_VOL, 0x0000)
        time.sleep_ms(3)

    def _write_sci(self, addr, val):
        self._xcs.value(0)
        self.spi.write(bytearray([0x02, addr & 0xFF, (val >> 8) & 0xFF, val & 0xFF]))
        self._xcs.value(1)

    def _read_sci(self, addr):
        self._xcs.value(0)
        out = bytearray([0x03, addr & 0xFF, 0x00, 0x00])
        buf = bytearray(4)
        self.spi.write_readinto(out, buf)
        self._xcs.value(1)
        return (buf[2] << 8) | buf[3]

    def _load_am_wav(self):
        """Load AM sound. Prefers WAV (loads raw PCM into RAM for PIO overlay).
        Falls back to any format for codec-only sequential playback."""
        self._am_wav_path = None
        self._am_samples = None
        self._am_sample_rate = 8000
        wav_paths = [p for p in AM_SOUND_PATHS if p.endswith(".wav")]
        other_paths = [p for p in AM_SOUND_PATHS if not p.endswith(".wav")]
        for path in wav_paths:
            try:
                samples, sr = load_wav_u8(path)
                self._am_samples = samples
                self._am_sample_rate = sr
                self._am_wav_path = path
                self.wav_data = True
                print("VS1053: AM WAV loaded ({} samples, {}Hz)".format(len(samples), sr))
                break
            except Exception as e:
                print("VS1053: WAV load failed for {}: {}".format(path, e))
                continue
        if self._am_samples is not None:
            print("VS1053: PWM overlay ready on GP{} ({} samples, {}Hz)".format(
                PIN_AUDIO, len(self._am_samples), self._am_sample_rate))
            return
        for path in other_paths + wav_paths:
            try:
                f = open(path, "rb")
                f.close()
                self._am_wav_path = path
                self.wav_data = True
                print("VS1053: AM sound found at {} (codec-only, no PIO)".format(path))
                return
            except OSError:
                continue
        self.wav_data = None
        print("VS1053: AM sound not found")

    def _start_stream(self, path, start_ms=0):
        """Open file and prepare for non-blocking streaming. Returns True if ready."""
        if path.startswith("/sd"):
            self._xcs.value(1)
            self._xdcs.value(1)
            self.spi.init(baudrate=self._spi_hz, polarity=0, phase=0)
        try:
            f = open(path, "rb")
        except OSError as e:
            print("VS1053: cannot open", path, e)
            return False
        self._stream_file = f
        header = f.read(4)
        f.seek(0)
        is_mp3 = header[:3] == b"ID3" or header[:2] == b"\xff\xfb"
        if is_mp3 and start_ms > 0:
            skip = min(int(16 * start_ms / 1000), 64 * 1024)
            f.seek(skip)
        self._playing = True
        self._end_fill_remaining = 0
        self._stream_bytes_sent = 0
        self._stream_buf_pos = 0
        self._stream_buf_len = 0
        self.set_volume(self._volume)
        return True

    def tick_stream(self):
        """Feed VS1053 from a 4KB RAM buffer. SD card is read in bulk to minimize SPI bus transitions."""
        if self._end_fill_remaining > 0:
            for _ in range(64):
                if self._end_fill_remaining <= 0:
                    break
                if self._dreq.value() == 0:
                    break
                self._xdcs.value(0)
                self.spi.write(self._zero32)
                self._xdcs.value(1)
                self._end_fill_remaining -= 32
            if self._end_fill_remaining <= 0:
                self._playing = False
            return
        if self._stream_file is None:
            return

        # --- Phase 1: Refill buffer from SD if exhausted (one bulk read) ---
        if self._stream_buf_pos >= self._stream_buf_len:
            self._xcs.value(1)
            self._xdcs.value(1)
            # Ensure SPI is in clean mode 0 state before SD access
            self.spi.init(baudrate=self._spi_hz, polarity=0, phase=0)
            try:
                n = self._stream_file.readinto(self._stream_buf)
            except OSError as e:
                print("VS1053: SD read error:", e)
                try:
                    self._stream_file.close()
                except Exception:
                    pass
                self._stream_file = None
                self._playing = False
                self._recover_sd()
                return
            if not n:
                try:
                    self._stream_file.close()
                    print("VS1053: stream ended (EOF), {} bytes sent, buf_pos={} buf_len={}".format(
                        self._stream_bytes_sent, self._stream_buf_pos, self._stream_buf_len))
                except Exception:
                    pass
                self._stream_file = None
                self._end_fill_remaining = 2048
                self._stream_bytes_sent = 0
                return
            self._stream_buf_len = n
            self._stream_buf_pos = 0

        # --- Phase 2: Feed VS1053 from RAM buffer (no SD access) ---
        buf = self._stream_buf
        pos = self._stream_buf_pos
        blen = self._stream_buf_len
        for _ in range(128):
            if pos >= blen:
                break
            if self._dreq.value() == 0:
                break
            end = pos + 32
            self._xdcs.value(0)
            if end <= blen:
                self.spi.write(memoryview(buf)[pos:end])
            else:
                tail = bytearray(buf[pos:blen]) + bytearray(32 - (blen - pos))
                self.spi.write(tail)
                end = blen
            self._xdcs.value(1)
            self._stream_bytes_sent += (end - pos)
            pos = end
        self._stream_buf_pos = pos

    def _path_for_track(self, folder, track):
        t0 = time.ticks_ms()
        bases = [
            "/sd/{:02d}/{:03d}",
            "/sd/VintageRadio/{:02d}/{:03d}",
            "{:02d}/{:03d}",
            "VintageRadio/{:02d}/{:03d}",
        ]
        exts = (".mp3", ".wav")
        if self._path_cache is not None:
            try:
                path = self._path_cache.format(folder, track)
                print("_path_for_track({},{}) -> {} (cached, {}ms)".format(folder, track, path, time.ticks_diff(time.ticks_ms(), t0)))
                return path
            except (ValueError, TypeError):
                self._path_cache = None
        for base in bases:
            for ext in exts:
                path = (base + ext).format(folder, track)
                try:
                    open(path, "rb").close()
                    self._path_cache = base + ext
                    print("_path_for_track({},{}) -> {} (found, {}ms)".format(folder, track, path, time.ticks_diff(time.ticks_ms(), t0)))
                    return path
                except OSError:
                    continue
        print("_path_for_track({},{}) -> NOT FOUND ({}ms)".format(folder, track, time.ticks_diff(time.ticks_ms(), t0)))
        return None

    def play_track(self, folder, track, start_ms=0, folder_wrap=False):
        t0 = time.ticks_ms()
        if self._delay_playback:
            print("play_track({},{}) -> delay_playback=True".format(folder, track))
            return True
        self.stop()
        path = self._path_for_track(folder, track)
        if not path:
            print("VS1053: file not found, attempting SD recovery")
            self._recover_sd()
            self._path_cache = None
            path = self._path_for_track(folder, track)
        if not path:
            print("VS1053: file not found for folder={} track={}".format(folder, track))
            return False
        print("VS1053: playing {} (stop+lookup={}ms)".format(path, time.ticks_diff(time.ticks_ms(), t0)))
        ok = self._start_stream(path, start_ms)
        if not ok:
            print("VS1053: stream failed, recovering SD and retrying")
            self._recover_sd()
            self._path_cache = None
            path = self._path_for_track(folder, track)
            if path:
                ok = self._start_stream(path, start_ms)
        if ok:
            self._note_track_learned(folder, track)
        return ok

    def stop(self):
        _am_pwm_timer_stop()
        had_file = self._stream_file is not None
        self._playing = False
        self._end_fill_remaining = 0
        self._stream_buf_pos = 0
        self._stream_buf_len = 0
        if self._stream_file is not None:
            try:
                self._stream_file.close()
            except Exception:
                pass
            self._stream_file = None
        t0 = time.ticks_ms()
        self._write_sci(SCI_MODE, SM_SDINEW | SM_CANCEL)
        waited = 0
        for _ in range(50):
            if self._dreq.value():
                break
            time.sleep_ms(1)
            waited += 1
        self._write_sci(SCI_MODE, SM_SDINEW)
        if had_file:
            print("stop(): cancel_wait={}ms total={}ms".format(waited, time.ticks_diff(time.ticks_ms(), t0)))

    def set_volume(self, level):
        self._volume = max(0, min(100, level))
        self._apply_volume()

    def _apply_volume(self):
        """Write current volume to VS1053 SCI_VOL. Linear mapping: 0=-127dB, 100=0dB.
        The analog pot in the audio path handles the perceptual (log) taper."""
        v = int(0xFE * (100 - self._volume) / 100) & 0xFF
        self._write_sci(SCI_VOL, (v << 8) | v)

    def poll_volume_adc(self):
        """Read volume pot ADC and update VS1053 volume. Only active when PIN_VOL_ADC != -1."""
        if self._vol_adc is None:
            return
        now = time.ticks_ms()
        if time.ticks_diff(now, self._vol_adc_last_ms) < 50:
            return
        self._vol_adc_last_ms = now
        raw = self._vol_adc.read_u16()
        self._vol_smoothed = (self._vol_smoothed * 3 + raw) >> 2
        if self._vol_smoothed < 1300:
            new_vol = 0
        else:
            new_vol = min(int((self._vol_smoothed / 65535.0) * 100), 100)
        if abs(new_vol - self._volume) >= 2:
            self._volume = new_vol
            self._apply_volume()

    def is_playing(self):
        if self._stream_file is not None or self._end_fill_remaining > 0:
            return True
        try:
            t = self._read_sci(SCI_DECODE_TIME)
            if t != self._decode_time_sec:
                self._decode_time_sec = t
                return True
        except Exception:
            pass
        return self._playing

    def get_playback_position_ms(self):
        try:
            sec = self._read_sci(SCI_DECODE_TIME)
            return sec * 1000
        except Exception:
            return 0

    def _play_am_stream(self):
        """Play AM sound to completion through _start_stream/tick_stream pipeline.
        Fades volume out over the last ~25% of the file for a smooth transition.
        Does NOT call stop() — caller is responsible for codec reset/cleanup."""
        if self._am_wav_path is None:
            print("AM: no path, skipping")
            return
        try:
            file_size = os.stat(self._am_wav_path)[6]
        except OSError:
            file_size = 0
        print("AM: reset codec")
        self._vs1053_reset()
        print("AM: _start_stream({}, {} bytes)".format(self._am_wav_path, file_size))
        if not self._start_stream(self._am_wav_path, 0):
            print("AM: _start_stream FAILED")
            return
        target = self._volume
        fade_start = file_size * 3 // 4
        t0 = time.ticks_ms()
        last_vol = t0
        print("AM: streaming full file, vol={}, fade_start_byte={}".format(target, fade_start))
        while self._stream_file is not None:
            self.tick_stream()
            if file_size > 0 and time.ticks_diff(time.ticks_ms(), last_vol) >= 50:
                last_vol = time.ticks_ms()
                sent = self._stream_bytes_sent
                if sent >= fade_start:
                    remaining = file_size - sent
                    fade_range = file_size - fade_start
                    vol = max(0, target * remaining // fade_range) if fade_range > 0 else 0
                    v = (0xFE * (100 - vol) // 100) & 0xFF
                    self._write_sci(SCI_VOL, (v << 8) | v)
        elapsed = time.ticks_diff(time.ticks_ms(), t0)
        print("AM: stream done, {}ms".format(elapsed))
        self._playing = False
        self._end_fill_remaining = 0
        self._stream_buf_pos = 0
        self._stream_buf_len = 0

    def play_am_overlay(self):
        """Play AM sound (standalone, blocking). PWM if samples loaded, else codec."""
        if self._am_samples is not None:
            print("AM: PWM overlay (standalone)")
            self._play_am_pwm(fade=False)
            return
        if self._am_wav_path is None:
            return
        print("AM: codec overlay (full file)")
        self._play_am_stream()
        self.stop()
        self._vs1053_reset()
        self._xcs.value(1)
        self._xdcs.value(1)
        self.spi.init(baudrate=self._spi_hz, polarity=0, phase=0)
        self.set_volume(self._volume)

    def _sd_alive(self):
        """Quick check if SD card is accessible. Returns True if healthy."""
        try:
            os.listdir("/sd")
            return True
        except OSError:
            return False

    def start_with_am(self, folder, track):
        """Start music with AM radio crossfade.
        PWM path: true simultaneous playback (AM on GP3 + music on VS1053).
        Codec path (fallback): sequential with pre-opened file for minimal gap."""
        self._delay_playback = False
        if self._am_wav_path is None and self._am_samples is None:
            return self.play_track(folder, track, 0)

        self.stop()
        t_total = time.ticks_ms()
        if not self._sd_alive():
            print("start_with_am: SD dead, recovering before path lookup")
            self._recover_sd()
            self._path_cache = None
        path = self._path_for_track(folder, track)
        if not path:
            print("VS1053: file not found for folder={} track={}".format(folder, track))
            return False

        target_vol = self._volume

        if self._am_samples is not None and AM_PWM_SIMULTANEOUS_WITH_MUSIC:
            return self._start_with_am_pwm(path, target_vol, t_total, folder, track)
        return self._start_with_am_codec(path, target_vol, t_total, folder, track)

    def _play_am_pwm(self, fade=True):
        """AM on GP3 via Timer IRQ (batched, ~2kHz)."""
        samples = self._am_samples
        sr = self._am_sample_rate
        _am_pwm_timer_start(samples, sr, 1 if fade else 0)
        while not _am_irq_done:
            time.sleep_ms(2)
        _am_pwm_timer_stop()

    def _start_with_am_pwm(self, path, target_vol, t_total, folder, track):
        """AM on GP3 first half only; then MP3 from start + AM fade on GP3 (overlap, no skipped intro)."""
        self._vs1053_reset()
        self._xcs.value(1)
        self._xdcs.value(1)
        self.spi.init(baudrate=self._spi_hz, polarity=0, phase=0)

        samples = self._am_samples
        sr = self._am_sample_rate
        slen = len(samples)
        am_dur_ms = slen * 1000 // sr
        fsamp = max(1, slen // 2)
        rng = slen - fsamp

        _am_pwm_timer_start(samples, sr, 2)
        print(
            "start_with_am(PWM): AM phase1 {}ms then overlap+MP3 {}".format(
                fsamp * 1000 // sr, path
            )
        )

        while _am_irq_pos < fsamp and not _am_irq_done:
            time.sleep_ms(2)

        if _am_irq_done:
            _am_pwm_timer_stop()
            print("start_with_am(PWM): AM ended early, playing track")
            return self.play_track(folder, track, 0)

        if not self._start_stream(path, 0):
            _am_pwm_timer_stop()
            print("start_with_am(PWM): _start_stream FAILED, recovering SD")
            self._recover_sd()
            if not self._start_stream(path, 0):
                print("start_with_am(PWM): FAILED after recovery for", path)
                return False
        self._note_track_learned(folder, track)
        self._write_sci(SCI_VOL, 0xFEFE)
        for _ in range(280):
            self.tick_stream()

        reg_target = (0xFE * (100 - target_vol) // 100) & 0xFF
        fade_range_reg = 0xFE - reg_target
        last_sci = time.ticks_ms()

        while not _am_irq_done:
            for _ in range(36):
                self.tick_stream()
            p = _am_irq_pos
            if rng > 0 and p >= fsamp:
                fade_sp = p - fsamp
                if fade_sp > rng:
                    fade_sp = rng
                remaining = rng - fade_sp
                reg = reg_target + fade_range_reg * remaining * remaining // (rng * rng)
                reg = min(0xFE, reg)
                now = time.ticks_ms()
                if time.ticks_diff(now, last_sci) >= 35:
                    last_sci = now
                    self._write_sci(SCI_VOL, (reg << 8) | reg)

        _am_pwm_timer_stop()
        self.set_volume(target_vol)
        for _ in range(500):
            self.tick_stream()
        dt = 0
        try:
            dt = self._read_sci(SCI_DECODE_TIME)
        except Exception:
            pass
        wall_after = time.ticks_diff(time.ticks_ms(), t_total)
        if wall_after > am_dur_ms * 7 // 10 and dt < 4:
            print("start_with_am(PWM): decode stalled, restarting track")
            try:
                self._stream_file.close()
            except Exception:
                pass
            self._stream_file = None
            self.stop()
            self._vs1053_reset()
            self._xcs.value(1)
            self._xdcs.value(1)
            self.spi.init(baudrate=self._spi_hz, polarity=0, phase=0)
            if self._start_stream(path, 0):
                self.set_volume(target_vol)
                for _ in range(400):
                    self.tick_stream()
        print("start_with_am(PWM): DONE, total={}ms decode_t={}".format(
            time.ticks_diff(time.ticks_ms(), t_total), dt))
        return True

    def _start_with_am_codec(self, path, target_vol, t_total, folder, track):
        """Sequential fallback: play AM through codec, then music with minimal gap."""
        try:
            music_file = open(path, "rb")
        except OSError as e:
            print("start_with_am(codec): cannot pre-open", path, e)
            return False
        print("start_with_am(codec): path={} vol={} (pre-opened)".format(path, target_vol))

        self._play_am_stream()

        t_reset = time.ticks_ms()
        self._vs1053_reset()
        self._xcs.value(1)
        self._xdcs.value(1)
        self.spi.init(baudrate=self._spi_hz, polarity=0, phase=0)

        music_file.read(4)
        music_file.seek(0)
        self._stream_file = music_file
        self._playing = True
        self._end_fill_remaining = 0
        self._stream_bytes_sent = 0
        self._stream_buf_pos = 0
        self._stream_buf_len = 0
        self._note_track_learned(folder, track)
        self._write_sci(SCI_VOL, 0xFEFE)
        for _ in range(180):
            self.tick_stream()
        print("start_with_am(codec): music primed, gap={}ms".format(time.ticks_diff(time.ticks_ms(), t_reset)))

        t0 = time.ticks_ms()
        last_vol = t0
        fade_ms = 800
        reg_target = (0xFE * (100 - target_vol) // 100) & 0xFF
        fade_range = 0xFE - reg_target
        while True:
            self.tick_stream()
            now = time.ticks_ms()
            elapsed = time.ticks_diff(now, t0)
            if elapsed >= fade_ms:
                break
            if time.ticks_diff(now, last_vol) >= 50:
                last_vol = now
                remaining = fade_ms - elapsed
                reg = reg_target + fade_range * remaining * remaining // (fade_ms * fade_ms)
                reg = min(0xFE, reg)
                self._write_sci(SCI_VOL, (reg << 8) | reg)

        self.set_volume(target_vol)
        print("start_with_am(codec): DONE, total={}ms".format(time.ticks_diff(time.ticks_ms(), t_total)))
        return True

    def reset_dfplayer(self):
        """Alias for main.py compatibility. Software reset only — hardware reset would break the shared SPI SD card."""
        self._vs1053_reset()
        self.set_volume(self._volume)

    def save_state(self, state_dict):
        album_idx = state_dict.get("album_index", 0) + 1
        track = state_dict.get("track", 1)
        known = state_dict.get("known_tracks", {})
        mode = state_dict.get("mode", "album")
        track_str = ",".join("%d:%d" % (a, c) for a, c in sorted(known.items()))
        payload = "{},{};tracks={};mode={}".format(album_idx, track, track_str, mode)
        for base in ["/sd/VintageRadio", "/sd", "VintageRadio", ""]:
            p = base + "/album_state.txt" if base else "album_state.txt"
            try:
                with open(p, "w") as f:
                    f.write(payload)
                return
            except OSError:
                continue
        print("VS1053: could not save state")

    def load_state(self):
        self._load_metadata()
        for base in ["/sd/VintageRadio", "/sd", "VintageRadio", ""]:
            p = base + "/album_state.txt" if base else "album_state.txt"
            try:
                with open(p, "r") as f:
                    raw = f.read().strip()
            except OSError:
                continue
            parts = raw.split(";")
            a_str, t_str = parts[0].split(",", 1)
            album_idx = int(a_str) - 1
            track = int(t_str)
            known_tracks = {}
            mode = "album"
            for i in range(1, len(parts)):
                if parts[i].startswith("tracks="):
                    for pair in parts[i][7:].split(","):
                        if ":" in pair:
                            a, c = pair.split(":", 1)
                            known_tracks[int(a)] = int(c)
                elif parts[i].startswith("mode="):
                    mode = parts[i][5:].strip().lower()
            return {"mode": mode, "album_index": album_idx, "track": track, "known_tracks": known_tracks}
        return {"mode": "album", "album_index": 0, "track": 1, "known_tracks": self._known_tracks}

    def log(self, message):
        print(message)

    def _load_metadata(self):
        if self._albums or self._playlists:
            return
        data = None
        for path in METADATA_PATHS:
            try:
                with open(path, "r") as f:
                    data = json.load(f)
                break
            except (OSError, ValueError):
                continue
        if data is None:
            return
        am = data.get("am_sound", {})
        self._am_folder = am.get("folder", 99)
        self._am_track = am.get("track", 1)
        raw_songs = data.get("songs", {})
        if isinstance(raw_songs, list):
            songs = {str(s.get("id", i)): s for i, s in enumerate(raw_songs)}
        else:
            songs = {str(k): v for k, v in raw_songs.items()}

        def add_track(t, folder_default, idx):
            sid = t.get("song_id", idx + 1)
            s = songs.get(str(sid), {})
            folder = t.get("folder", folder_default)
            track_num = t.get("track", t.get("sd_track", idx + 1))
            self._known_tracks[folder] = max(self._known_tracks.get(folder, 0), track_num)
            return {
                "id": sid, "title": s.get("title", t.get("title", "?")), "artist": s.get("artist", t.get("artist", "?")),
                "duration": s.get("duration", t.get("duration", 180)), "folder": folder, "track_number": track_num,
            }

        new_albums = data.get("albums")
        new_playlists = data.get("playlists")
        if new_albums is not None or new_playlists is not None:
            for col in (new_albums or []):
                tracks = [add_track(t, 1, i) for i, t in enumerate(col.get("tracks", []))]
                self._albums.append({"id": col.get("id", 0), "name": col.get("name", "?"), "tracks": tracks})
            for col in (new_playlists or []):
                tracks = [add_track(t, 1, i) for i, t in enumerate(col.get("tracks", []))]
                self._playlists.append({"id": col.get("id", 0), "name": col.get("name", "?"), "tracks": tracks})
        else:
            for fid_str, folder in data.get("folders", {}).items():
                try:
                    fid = int(fid_str)
                except ValueError:
                    continue
                name = folder.get("name", "Folder %s" % fid)
                tracks = [add_track(t, fid, i) for i, t in enumerate(folder.get("tracks", []))]
                entry = {"id": fid, "name": name, "tracks": tracks}
                (self._playlists if folder.get("type") == "playlist" else self._albums).append(entry)

        seen = set()
        for c in self._albums + self._playlists:
            for t in c["tracks"]:
                if t.get("id") not in seen:
                    seen.add(t.get("id"))
                    self._all_tracks.append(t)

    def get_albums(self):
        return self._albums

    def get_playlists(self):
        return self._playlists

    def get_all_tracks(self):
        return self._all_tracks

    def is_power_on(self):
        return self.power_sense.value() == 1

    def is_button_pressed(self):
        return self.button.value() == 0

    def set_delay_playback(self, delay):
        self._delay_playback = bool(delay)

    def _note_track_learned(self, folder, track):
        if track > self._known_tracks.get(folder, 0):
            self._known_tracks[folder] = track


# Drop-in: main.py imports DFPlayerHardware from components.dfplayer_hardware
DFPlayerHardware = VS1053Hardware
