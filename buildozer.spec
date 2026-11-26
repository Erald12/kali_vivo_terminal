# Buildozer configuration: Kali Vivo Terminal (Android debug APK).
#
# Packaging layout: Buildozer only packages files under source.dir (src/).
# assets/ lives at the project root, so the CI workflow copies it into
# src/assets/ before building. Locally, do the same (see README) or the
# monospace font will fall back to Roboto.

[app]

title = Kali Vivo Terminal
package.name = kalivivoterminal
package.domain = org.kalivivo
p4a.branch = v2024.01.21

# Entry point is src/main.py (Buildozer requires main.py at source.dir root).
source.dir = src
source.include_exts = py,kv,png,jpg,jpeg,webp,svg,ttf,otf,json,txt
source.exclude_dirs = tests,bin,__pycache__
source.exclude_patterns = *.pyc,*.pyo

version = 0.1.0

# Pinned for reproducible builds. Keep in sync with requirements.txt.
requirements = python3,kivy==2.3.1,filetype==1.2.0

# Vivo Y27: tall FHD+ screen, portrait only.
orientation = portrait
# Keep the status bar visible so the notch area is handled by the UI padding.
fullscreen = 0

# Terminal app: no runtime permissions needed (shell runs in the app sandbox).
android.permissions =

# SDK / NDK
android.api = 34
android.minapi = 24
android.ndk = 25b
android.ndk_api = 24
android.accept_sdk_license = True

# Vivo Y27 uses a 64-bit ARM SoC, so arm64-v8a alone covers the device.
# Add armeabi-v7a only if you need 32-bit support (it roughly doubles build time).
android.archs = arm64-v8a

android.allow_backup = False

[buildozer]

log_level = 2
warn_on_root = 1
