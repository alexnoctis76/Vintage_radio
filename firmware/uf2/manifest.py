# MicroPython frozen-module manifest for Vintage Radio (basic mode).
# Used by: python scripts/build_firmware_release.py --docker-uf2
#
# Note: MicroPython still runs main.py from the on-device filesystem at boot.
# After flashing a frozen build, run install.ps1 once, or use --flash-dump on a
# golden device to bake filesystem + firmware into one shareable .uf2.

include("$(PORT_DIR)/boards/manifest.py")

freeze("$(MPY_DIR)/firmware/uf2/frozen")
