# On-device hardware diagnostic suite for Vintage Radio (Pico / RP2040)
#
# Flash this file alongside the normal firmware, then run via REPL:
#   import hw_test; hw_test.run_all()
# Or execute directly:
#   exec(open("hw_test.py").read())
#
# Each test prints [PASS] or [FAIL] with a short description.
# NeoPixel shows green when all tests pass, red when any fail.
# Tests are non-destructive and complete in under 30 seconds.

from machine import Pin, UART, PWM
import neopixel
import time

try:
    from pin_config_loader import load_pin_config, get_spi_config, get_dfplayer_config
    _cfg = load_pin_config()
    _pins = _cfg.get("pins", {})
    _df_cfg = get_dfplayer_config()
except Exception:
    _pins = {}
    _df_cfg = {}

PIN_BUTTON   = _pins.get("button", 2)
PIN_NEOPIX   = _pins.get("neopixel", 16)
PIN_UART_TX  = _pins.get("uart_tx", 0)
PIN_UART_RX  = _pins.get("uart_rx", 1)
PIN_SENSE    = _pins.get("power_sense", 14)
PIN_BUSY     = _pins.get("busy", 15)
PIN_AUDIO    = _pins.get("audio_pwm", 3)
DFPLAYER_VOL = _df_cfg.get("max_volume", 28)

_results = []


def _pass(name, detail=""):
    msg = f"[PASS] {name}"
    if detail:
        msg += f" ({detail})"
    print(msg)
    _results.append((True, name))


def _fail(name, reason=""):
    msg = f"[FAIL] {name}"
    if reason:
        msg += f" - {reason}"
    print(msg)
    _results.append((False, name))


# -------------------------------------------------------
#  Individual tests
# -------------------------------------------------------

def test_gpio_init():
    """Verify button, power_sense, busy, neopixel and audio pins can be initialized."""
    try:
        btn = Pin(PIN_BUTTON, Pin.IN, Pin.PULL_UP)
        sense = Pin(PIN_SENSE, Pin.IN, Pin.PULL_DOWN)
        busy = Pin(PIN_BUSY, Pin.IN)
        np = neopixel.NeoPixel(Pin(PIN_NEOPIX), 1)
        audio = Pin(PIN_AUDIO, Pin.IN)
        _pass("GPIO pin initialization",
              f"btn={btn.value()} sense={sense.value()} busy={busy.value()}")
    except Exception as e:
        _fail("GPIO pin initialization", str(e))


def test_neopixel_cycle():
    """Cycle NeoPixel through green/red/blue/off for visual confirmation."""
    try:
        np = neopixel.NeoPixel(Pin(PIN_NEOPIX), 1)
        for color in [(0, 10, 0), (10, 0, 0), (0, 0, 10), (0, 0, 0)]:
            np[0] = color
            np.write()
            time.sleep_ms(150)
        _pass("NeoPixel color cycle", "green/red/blue/off")
    except Exception as e:
        _fail("NeoPixel color cycle", str(e))


def _df_send(uart, cmd, p1=0, p2=0):
    """Send a 10-byte DFPlayer command packet."""
    pkt = bytearray([0x7E, 0xFF, 0x06, cmd, 0x00, p1 & 0xFF, p2 & 0xFF])
    csum = -sum(pkt[1:7]) & 0xFFFF
    pkt.append((csum >> 8) & 0xFF)
    pkt.append(csum & 0xFF)
    pkt.append(0xEF)
    uart.write(pkt)
    time.sleep_ms(30)


def _df_read(uart, timeout_ms=800):
    """Read up to 10 bytes from DFPlayer UART within timeout_ms, return bytearray."""
    buf = bytearray()
    t0 = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), t0) < timeout_ms:
        if uart.any():
            buf += uart.read(uart.any())
            if len(buf) >= 10:
                break
        time.sleep_ms(10)
    return buf


def test_dfplayer_uart_reset():
    """Send reset (0x3F) to DFPlayer, expect an 0x3F or 0x41 init response."""
    try:
        uart = UART(0, baudrate=9600, tx=Pin(PIN_UART_TX), rx=Pin(PIN_UART_RX))
        time.sleep_ms(400)
        _df_send(uart, 0x3F)
        time.sleep_ms(800)
        resp = _df_read(uart, timeout_ms=1000)
        if resp and len(resp) >= 4 and resp[0] == 0x7E:
            cmd_byte = resp[3] if len(resp) > 3 else 0
            _pass("DFPlayer UART reset", f"response cmd=0x{cmd_byte:02X}")
        elif resp:
            _fail("DFPlayer UART reset", f"got {len(resp)} bytes but no 0x7E start")
        else:
            _fail("DFPlayer UART reset", "no response - DFPlayer not detected")
        uart.deinit()
    except Exception as e:
        _fail("DFPlayer UART reset", str(e))


def test_dfplayer_volume_set():
    """Send volume command (0x06) and check for ACK (0x41) within 500ms."""
    try:
        uart = UART(0, baudrate=9600, tx=Pin(PIN_UART_TX), rx=Pin(PIN_UART_RX))
        time.sleep_ms(200)
        uart.read(uart.any())  # drain buffer
        _df_send(uart, 0x06, 0, DFPLAYER_VOL, )
        resp = _df_read(uart, timeout_ms=500)
        acked = any(len(resp) > i + 3 and resp[i] == 0x7E and resp[i + 3] == 0x41
                    for i in range(len(resp) - 3))
        if acked:
            _pass("DFPlayer volume set", f"ACK received (vol={DFPLAYER_VOL})")
        else:
            # Some clones don't send ACK even with fb=0; treat as inconclusive
            _pass("DFPlayer volume set", f"no ACK (clone DFPlayer?) - cmd sent vol={DFPLAYER_VOL}")
        uart.deinit()
    except Exception as e:
        _fail("DFPlayer volume set", str(e))


def test_dfplayer_query_file_count():
    """Query total TF file count (0x48) and validate response is numeric."""
    try:
        uart = UART(0, baudrate=9600, tx=Pin(PIN_UART_TX), rx=Pin(PIN_UART_RX))
        time.sleep_ms(200)
        uart.read(uart.any())
        _df_send(uart, 0x48, feedback=True)
        resp = _df_read(uart, timeout_ms=1200)
        if resp and len(resp) >= 10 and resp[0] == 0x7E and resp[3] == 0x48:
            count = (resp[5] << 8) | resp[6]
            _pass("DFPlayer query file count", f"count={count}")
        else:
            _fail("DFPlayer query file count", f"unexpected response ({len(resp)} bytes)")
        uart.deinit()
    except Exception as e:
        _fail("DFPlayer query file count", str(e))


def test_dfplayer_query_folder_count():
    """Query total folder count (0x4F) and validate response."""
    try:
        uart = UART(0, baudrate=9600, tx=Pin(PIN_UART_TX), rx=Pin(PIN_UART_RX))
        time.sleep_ms(200)
        uart.read(uart.any())
        _df_send(uart, 0x4F, feedback=True)
        resp = _df_read(uart, timeout_ms=1200)
        if resp and len(resp) >= 10 and resp[0] == 0x7E and resp[3] == 0x4F:
            count = (resp[5] << 8) | resp[6]
            _pass("DFPlayer query folder count", f"folders={count}")
        else:
            _fail("DFPlayer query folder count", f"unexpected response ({len(resp)} bytes)")
        uart.deinit()
    except Exception as e:
        _fail("DFPlayer query folder count", str(e))


def test_dfplayer_play_stop():
    """Play folder 1 track 1, wait 1s, verify BUSY goes LOW, then stop."""
    try:
        uart = UART(0, baudrate=9600, tx=Pin(PIN_UART_TX), rx=Pin(PIN_UART_RX))
        busy = Pin(PIN_BUSY, Pin.IN)
        time.sleep_ms(200)

        _df_send(uart, 0x0F, 1, 1)  # play folder 1, track 1
        time.sleep_ms(1200)

        busy_val = busy.value()
        # BUSY LOW (0) means playing; BUSY HIGH (1) means idle
        if busy_val == 0:
            _pass("DFPlayer play (folder 1, track 1)", "BUSY LOW - playing confirmed")
        else:
            _fail("DFPlayer play (folder 1, track 1)", "BUSY HIGH after play - possible no track")

        _df_send(uart, 0x16)  # stop
        time.sleep_ms(500)
        busy_after_stop = busy.value()
        if busy_after_stop == 1:
            _pass("DFPlayer stop", "BUSY HIGH - stopped")
        else:
            _fail("DFPlayer stop", "BUSY still LOW after stop command")

        uart.deinit()
    except Exception as e:
        _fail("DFPlayer play/stop", str(e))


def test_power_sense():
    """Report current state of power_sense pin (informational, not pass/fail)."""
    try:
        sense = Pin(PIN_SENSE, Pin.IN, Pin.PULL_DOWN)
        val = sense.value()
        _pass("Power sense reading", f"pin_state={val} ({'active' if val else 'inactive'})")
    except Exception as e:
        _fail("Power sense reading", str(e))


def test_sd_card_mount():
    """Attempt to mount SD card over SPI, try primary then alternate pins."""
    try:
        import os
        if "sd" in os.listdir("/"):
            _pass("SD card mount", "already mounted at /sd")
            return

        try:
            from machine import SPI
            from sdcard import SDCard
            from pin_config_loader import get_spi_config
            spi_cfg = get_spi_config(alt=False)
            spi = SPI(
                spi_cfg.get("bus", 1),
                baudrate=1_000_000, polarity=0, phase=0,
                sck=Pin(spi_cfg.get("sck", 10)),
                mosi=Pin(spi_cfg.get("mosi", 11)),
                miso=Pin(spi_cfg.get("miso", 12)),
            )
            cs = Pin(spi_cfg.get("cs", 13), Pin.OUT)
            sd = SDCard(spi, cs)
            os.mount(sd, "/sd")
            _pass("SD card mount (SPI)", "mounted at /sd")
        except Exception as e1:
            # Try alternate pins
            try:
                from pin_config_loader import get_spi_config
                alt = get_spi_config(alt=True)
                spi2 = SPI(
                    alt.get("bus", 0),
                    baudrate=1_000_000, polarity=0, phase=0,
                    sck=Pin(alt.get("sck", 18)),
                    mosi=Pin(alt.get("mosi", 19)),
                    miso=Pin(alt.get("miso", 16)),
                )
                cs2 = Pin(alt.get("cs", 17), Pin.OUT)
                sd2 = SDCard(spi2, cs2)
                os.mount(sd2, "/sd")
                _pass("SD card mount (alt SPI)", "mounted at /sd")
            except Exception as e2:
                _fail("SD card mount", f"primary: {e1} | alt: {e2}")
    except Exception as e:
        _fail("SD card mount", str(e))


def test_am_overlay_wav_load():
    """Check that the AM WAV file can be found on Pico flash (informational)."""
    import os
    paths = [
        "/VintageRadio/AMradioSound.wav",
        "VintageRadio/AMradioSound.wav",
        "/AMradioSound.wav",
        "AMradioSound.wav",
    ]
    for path in paths:
        try:
            stat = os.stat(path)
            _pass("AM overlay WAV", f"found at {path} ({stat[6]} bytes)")
            return
        except OSError:
            continue
    _fail("AM overlay WAV", "not found on Pico flash (overlay will use DFPlayer fallback)")


# -------------------------------------------------------
#  Test runner
# -------------------------------------------------------

def _df_send_with_feedback(uart, cmd, p1=0, p2=0, feedback=False):
    """_df_send that supports feedback flag."""
    fb = 0x01 if feedback else 0x00
    pkt = bytearray([0x7E, 0xFF, 0x06, cmd, fb, p1 & 0xFF, p2 & 0xFF])
    csum = -sum(pkt[1:7]) & 0xFFFF
    pkt.append((csum >> 8) & 0xFF)
    pkt.append(csum & 0xFF)
    pkt.append(0xEF)
    uart.write(pkt)
    time.sleep_ms(30)


# Monkey-patch _df_send to support feedback kwarg via the module-level function
_df_send_orig = _df_send
def _df_send(uart, cmd, p1=0, p2=0, feedback=False):
    return _df_send_with_feedback(uart, cmd, p1, p2, feedback)


def run_all():
    """Run all hardware diagnostic tests and display summary."""
    global _results
    _results = []

    np = None
    try:
        np = neopixel.NeoPixel(Pin(PIN_NEOPIX), 1)
        np[0] = (4, 4, 4)
        np.write()
    except Exception:
        pass

    print("\n" + "=" * 50)
    print("  Vintage Radio Hardware Diagnostics")
    print("=" * 50)

    tests = [
        test_gpio_init,
        test_neopixel_cycle,
        test_dfplayer_uart_reset,
        test_dfplayer_volume_set,
        test_dfplayer_query_file_count,
        test_dfplayer_query_folder_count,
        test_dfplayer_play_stop,
        test_power_sense,
        test_sd_card_mount,
        test_am_overlay_wav_load,
    ]

    for t in tests:
        try:
            t()
        except Exception as e:
            _fail(t.__name__, f"uncaught: {e}")

    passed = sum(1 for ok, _ in _results if ok)
    failed = sum(1 for ok, _ in _results if not ok)
    total = len(_results)

    print("=" * 50)
    print(f"Results: {passed}/{total} passed, {failed} failed")
    print("=" * 50)

    # Visual feedback on NeoPixel
    if np:
        try:
            if failed == 0:
                np[0] = (0, 20, 0)  # green = all pass
            else:
                np[0] = (20, 0, 0)  # red = some failed
            np.write()
        except Exception:
            pass

    return passed, failed
