"""
Predefined board profiles for Vintage Radio.

Each profile describes a microcontroller board's GPIO capabilities,
default pin assignments for the DFPlayer + radio hardware, and
any restrictions (pins to avoid, available buses, etc.).

To add a new board, append an entry to BOARD_PROFILES.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple


@dataclass
class BoardProfile:
    id: str
    name: str
    mcu: str
    platform: str  # "micropython" or "cpython"
    gpio_range: Tuple[int, int]  # inclusive (min, max)
    restricted_pins: Dict[int, str] = field(default_factory=dict)
    uart_buses: List[Dict[str, Any]] = field(default_factory=list)
    spi_buses: List[Dict[str, Any]] = field(default_factory=list)
    default_pin_config: Dict[str, Any] = field(default_factory=dict)
    supports_neopixel: bool = True
    supports_sd_spi: bool = True
    supports_pwm_audio: bool = True
    notes: str = ""

    def default_config_json(self) -> str:
        return json.dumps(self.default_pin_config, indent=2)

    def valid_gpio_pins(self) -> List[int]:
        lo, hi = self.gpio_range
        return [p for p in range(lo, hi + 1) if p not in self.restricted_pins]


# ---------------------------------------------------------------------------
#  Raspberry Pi Pico (RP2040)
# ---------------------------------------------------------------------------
_PICO_DEFAULT_CONFIG = {
    "board": "raspberry_pi_pico",
    "audio_module": "dfplayer",
    "pins": {
        "uart_tx": 0,
        "uart_rx": 1,
        "button": 2,
        "audio_pwm": 3,
        "power_sense": 14,
        "busy": 15,
        "neopixel": 16,
    },
    "spi": {"bus": 1, "sck": 10, "mosi": 11, "miso": 12, "cs": 13},
    "spi_alt": {"bus": 0, "sck": 18, "mosi": 19, "miso": 16, "cs": 17},
    "dfplayer": {"max_volume": 28, "uart_baud": 9600},
}

PICO = BoardProfile(
    id="raspberry_pi_pico",
    name="Raspberry Pi Pico",
    mcu="RP2040",
    platform="micropython",
    gpio_range=(0, 28),
    restricted_pins={
        23: "SMPS PS pin (internal)",
        24: "VBUS sense (internal)",
        25: "On-board LED",
    },
    uart_buses=[
        {"bus": 0, "default_tx": 0, "default_rx": 1},
        {"bus": 1, "default_tx": 4, "default_rx": 5},
    ],
    spi_buses=[
        {"bus": 0, "default_sck": 18, "default_mosi": 19, "default_miso": 16, "default_cs": 17},
        {"bus": 1, "default_sck": 10, "default_mosi": 11, "default_miso": 12, "default_cs": 13},
    ],
    default_pin_config=_PICO_DEFAULT_CONFIG,
    notes="Standard Pico with RP2040. 26 user GPIO (GP0-GP28, minus internal pins).",
)

# ---------------------------------------------------------------------------
#  Raspberry Pi Pico W (RP2040 + CYW43)
# ---------------------------------------------------------------------------
_PICO_W_DEFAULT_CONFIG = copy.deepcopy(_PICO_DEFAULT_CONFIG)
_PICO_W_DEFAULT_CONFIG["board"] = "raspberry_pi_pico_w"

PICO_W = BoardProfile(
    id="raspberry_pi_pico_w",
    name="Raspberry Pi Pico W",
    mcu="RP2040",
    platform="micropython",
    gpio_range=(0, 28),
    restricted_pins={
        23: "WL_ON (wireless power)",
        24: "WL_D (wireless SPI data)",
        25: "WL_CS (wireless SPI CS)",
        29: "WL_CLK (wireless SPI clock)",
    },
    uart_buses=[
        {"bus": 0, "default_tx": 0, "default_rx": 1},
        {"bus": 1, "default_tx": 4, "default_rx": 5},
    ],
    spi_buses=[
        {"bus": 0, "default_sck": 18, "default_mosi": 19, "default_miso": 16, "default_cs": 17},
        {"bus": 1, "default_sck": 10, "default_mosi": 11, "default_miso": 12, "default_cs": 13},
    ],
    default_pin_config=_PICO_W_DEFAULT_CONFIG,
    notes="Pico W with wireless. GP25 is not the on-board LED (it's on the CYW43).",
)

# ---------------------------------------------------------------------------
#  Raspberry Pi Pico 2 (RP2350)
# ---------------------------------------------------------------------------
_PICO2_DEFAULT_CONFIG = copy.deepcopy(_PICO_DEFAULT_CONFIG)
_PICO2_DEFAULT_CONFIG["board"] = "raspberry_pi_pico_2"

PICO_2 = BoardProfile(
    id="raspberry_pi_pico_2",
    name="Raspberry Pi Pico 2",
    mcu="RP2350",
    platform="micropython",
    gpio_range=(0, 29),
    restricted_pins={
        25: "On-board LED",
    },
    uart_buses=[
        {"bus": 0, "default_tx": 0, "default_rx": 1},
        {"bus": 1, "default_tx": 4, "default_rx": 5},
    ],
    spi_buses=[
        {"bus": 0, "default_sck": 18, "default_mosi": 19, "default_miso": 16, "default_cs": 17},
        {"bus": 1, "default_sck": 10, "default_mosi": 11, "default_miso": 12, "default_cs": 13},
    ],
    default_pin_config=_PICO2_DEFAULT_CONFIG,
    notes="Pico 2 with RP2350. Same GPIO layout as Pico, with extra capabilities.",
)

# ---------------------------------------------------------------------------
#  ESP32 (generic)
# ---------------------------------------------------------------------------
_ESP32_DEFAULT_CONFIG = {
    "board": "esp32",
    "audio_module": "dfplayer",
    "pins": {
        "uart_tx": 17,
        "uart_rx": 16,
        "button": 4,
        "audio_pwm": 25,
        "power_sense": 34,
        "busy": 35,
        "neopixel": 27,
    },
    "spi": {"bus": 1, "sck": 14, "mosi": 13, "miso": 12, "cs": 15},
    "dfplayer": {"max_volume": 28, "uart_baud": 9600},
}

ESP32 = BoardProfile(
    id="esp32",
    name="ESP32 (Generic)",
    mcu="ESP32",
    platform="micropython",
    gpio_range=(0, 39),
    restricted_pins={
        0: "Strapping pin (boot mode)",
        2: "Strapping pin (boot mode)",
        5: "Strapping pin (SDIO)",
        6: "Flash SPI CLK",
        7: "Flash SPI D0",
        8: "Flash SPI D1",
        9: "Flash SPI D2",
        10: "Flash SPI D3",
        11: "Flash SPI CMD",
        12: "Strapping pin (JTAG/boot)",
        15: "Strapping pin (JTAG/SDIO)",
    },
    uart_buses=[
        {"bus": 1, "default_tx": 17, "default_rx": 16},
        {"bus": 2, "default_tx": 17, "default_rx": 16},
    ],
    spi_buses=[
        {"bus": 1, "default_sck": 14, "default_mosi": 13, "default_miso": 12, "default_cs": 15},
    ],
    default_pin_config=_ESP32_DEFAULT_CONFIG,
    supports_sd_spi=True,
    notes="Generic ESP32. Avoid GPIO 6-11 (flash). GPIO 34-39 are input-only.",
)

# ---------------------------------------------------------------------------
#  ESP32-S3
# ---------------------------------------------------------------------------
_ESP32S3_DEFAULT_CONFIG = {
    "board": "esp32_s3",
    "audio_module": "dfplayer",
    "pins": {
        "uart_tx": 17,
        "uart_rx": 18,
        "button": 4,
        "audio_pwm": 5,
        "power_sense": 6,
        "busy": 7,
        "neopixel": 48,
    },
    "spi": {"bus": 1, "sck": 12, "mosi": 11, "miso": 13, "cs": 10},
    "dfplayer": {"max_volume": 28, "uart_baud": 9600},
}

ESP32_S3 = BoardProfile(
    id="esp32_s3",
    name="ESP32-S3",
    mcu="ESP32-S3",
    platform="micropython",
    gpio_range=(0, 48),
    restricted_pins={
        26: "Flash/PSRAM (SPICS1)",
        27: "Flash/PSRAM (SPIHD)",
        28: "Flash/PSRAM (SPIWP)",
        29: "Flash/PSRAM (SPICS0)",
        30: "Flash/PSRAM (SPICLK)",
        31: "Flash/PSRAM (SPIQ)",
        32: "Flash/PSRAM (SPID)",
    },
    uart_buses=[
        {"bus": 1, "default_tx": 17, "default_rx": 18},
    ],
    spi_buses=[
        {"bus": 1, "default_sck": 12, "default_mosi": 11, "default_miso": 13, "default_cs": 10},
    ],
    default_pin_config=_ESP32S3_DEFAULT_CONFIG,
    notes="ESP32-S3 with USB-OTG. GPIO 48 is the built-in NeoPixel on many dev boards.",
)

# ---------------------------------------------------------------------------
#  Raspberry Pi (Linux / CPython)
# ---------------------------------------------------------------------------
_PI_LINUX_DEFAULT_CONFIG = {
    "board": "raspberry_pi_linux",
    "audio_module": "vlc",
    "pins": {
        "button": 2,
        "power_sense": 14,
        "busy": 15,
    },
}

PI_LINUX = BoardProfile(
    id="raspberry_pi_linux",
    name="Raspberry Pi (Linux)",
    mcu="BCM",
    platform="cpython",
    gpio_range=(2, 27),
    restricted_pins={
        0: "I2C0 SDA (EEPROM)",
        1: "I2C0 SCL (EEPROM)",
    },
    uart_buses=[],
    spi_buses=[],
    default_pin_config=_PI_LINUX_DEFAULT_CONFIG,
    supports_neopixel=False,
    supports_sd_spi=False,
    supports_pwm_audio=False,
    notes="Raspberry Pi running Linux. Audio via VLC, GPIO via RPi.GPIO (BCM numbering).",
)


# ---------------------------------------------------------------------------
#  Registry
# ---------------------------------------------------------------------------

BOARD_PROFILES: List[BoardProfile] = [
    PICO,
    PICO_W,
    PICO_2,
    ESP32,
    ESP32_S3,
    PI_LINUX,
]

BOARD_PROFILES_BY_ID: Dict[str, BoardProfile] = {bp.id: bp for bp in BOARD_PROFILES}


def get_board_profile(board_id: str) -> Optional[BoardProfile]:
    return BOARD_PROFILES_BY_ID.get(board_id)


def get_default_board_profile() -> BoardProfile:
    return PICO


PIN_FUNCTION_LABELS = {
    "uart_tx": "UART TX (to DFPlayer RX)",
    "uart_rx": "UART RX (from DFPlayer TX)",
    "button": "Button",
    "audio_pwm": "Audio PWM (AM overlay)",
    "power_sense": "Power Sense",
    "busy": "DFPlayer BUSY",
    "neopixel": "NeoPixel LED",
    "volume_adc": "Volume Pot (ADC)",
}

SPI_FUNCTION_LABELS = {
    "sck": "SPI SCK (clock)",
    "mosi": "SPI MOSI (data out)",
    "miso": "SPI MISO (data in)",
    "cs": "SPI CS (chip select)",
    "bus": "SPI Bus Number",
}
