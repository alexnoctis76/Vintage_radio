"""Pure-Python DFPlayer Mini UART packet helpers (host + MicroPython)."""

DF_ERROR_MSGS = {
    0x01: "Module busy",
    0x02: "Sleep mode",
    0x03: "Serial receiving error",
    0x04: "Checksum error",
    0x05: "File index out of bound",
    0x06: "File not found",
    0x07: "Insert TF card",
}


def build_dfplayer_packet(cmd, p1=0, p2=0, feedback=False):
    """Build a 10-byte DFPlayer command or response packet."""
    fb = 0x01 if feedback else 0x00
    body = bytes([0xFF, 0x06, cmd, fb, p1 & 0xFF, p2 & 0xFF])
    csum = (-sum(body)) & 0xFFFF
    return bytes([0x7E]) + body + bytes([(csum >> 8) & 0xFF, csum & 0xFF, 0xEF])


def packet_body_checksum(body_bytes):
    """Checksum for DFPlayer packet body bytes (indices 1–6 inclusive)."""
    return (-sum(body_bytes)) & 0xFFFF
