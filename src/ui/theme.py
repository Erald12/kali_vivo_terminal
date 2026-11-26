"""Kali-style dark theme and responsive metrics for Vivo Y27 (1080x2388, FHD+ tall)."""
import os

from kivy.metrics import dp, sp
from kivy.utils import get_color_from_hex

# ---------------------------------------------------------------------------
# Kali Linux dark palette
# ---------------------------------------------------------------------------
BG = get_color_from_hex("#0B0F14")          # window background
PANEL = get_color_from_hex("#111820")       # title bar, input row, output area
PANEL_ALT = get_color_from_hex("#16202B")   # quick-key buttons
BORDER = get_color_from_hex("#1F2D3A")

KALI_BLUE = get_color_from_hex("#367BF0")   # accent / brand
KALI_GREEN = get_color_from_hex("#8AE234")  # user / host in prompt
KALI_CYAN = get_color_from_hex("#34E2E2")   # key labels
KALI_RED = get_color_from_hex("#EF2929")    # errors, ^C
KALI_YELLOW = get_color_from_hex("#FCE94F") # warnings

TEXT = get_color_from_hex("#E6EDF3")
MUTED = get_color_from_hex("#7D8590")


def to_hex(color):
    """Convert a Kivy RGBA tuple to a 6-digit hex string for markup tags."""
    return "".join("%02x" % int(c * 255) for c in color[:3])


def markup(color, text):
    """Wrap text in a Kivy markup color tag. Text must already be escaped."""
    return "[color=%s]%s[/color]" % (to_hex(color), text)


# Prompt shown before each command: kali@vivo-y27:~$
PROMPT = (
    markup(KALI_GREEN, "kali@vivo-y27")
    + markup(TEXT, ":")
    + markup(KALI_BLUE, "~")
    + markup(TEXT, "$ ")
)

# ---------------------------------------------------------------------------
# Responsive metrics (dp/sp scale across densities; avoid hard-coded px)
# ---------------------------------------------------------------------------
# Clearance for the front camera notch / status bar on the Vivo Y27.
# Approximate; swap for a real inset query later if needed.
SAFE_TOP = dp(36)
# Clearance for the bottom gesture navigation bar.
SAFE_BOTTOM = dp(28)

PAD = dp(10)
SPACING = dp(6)
ROW_H = dp(46)      # title bar and input row
KEY_H = dp(40)      # quick-key row
BAR_W = dp(4)       # scrollbar width

FONT_TITLE = sp(14)
FONT_OUTPUT = sp(13)
FONT_INPUT = sp(15)
FONT_KEY = sp(11)

# ---------------------------------------------------------------------------
# Fonts
# ---------------------------------------------------------------------------
# Drop a monospace TTF into assets/fonts/. Falls back to Kivy's default font if missing.
# The app root is src/ (in the repo) and the packaged app root (on device). CI copies
# assets/ into src/assets/ before building, so the same path works in both places.
_APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MONO_PATH = os.path.join(_APP_ROOT, "assets", "fonts", "DejaVuSansMono.ttf")
FONT_MONO = _MONO_PATH if os.path.exists(_MONO_PATH) else "Roboto"