#!/usr/bin/env bash
# Install a pinned Bambu Studio release for headless CLI slicing on an Ubuntu
# x86_64 runner (tested on Ubuntu 26.04 with the ubu24 AppImage). Idempotent.
#
#   bash install_bambu_studio.sh            # -> /tmp/bambu/app/bin/bambu-studio
#
# Override with BAMBU_TAG / BAMBU_ASSET / BAMBU_SHA256 / BAMBU_ROOT. The digest is
# the one GitHub publishes for the release asset; the download is refused if it
# does not match. No display, FUSE or GitHub token is needed.
set -euo pipefail

TAG="${BAMBU_TAG:-v02.09.01.70}"
ASSET="${BAMBU_ASSET:-BambuStudio_ubu24-v02.09.01.70-20261103183404.AppImage}"
SHA256="${BAMBU_SHA256:-668dabb1be53c758189ed6bc89935285dea5e0af46216546b1bafd6882e9aff0}"
ROOT="${BAMBU_ROOT:-/tmp/bambu}"
APP="$ROOT/app"
STAMP="$APP/.installed-$TAG"

# Shared libraries the AppImage expects from the host (found with ldd).
APT_PKGS=(libgstreamer-plugins-base1.0-0 libwebkit2gtk-4.1-0 libjavascriptcoregtk-4.1-0 libwayland-server0)

missing=()
for p in "${APT_PKGS[@]}"; do dpkg-query -W -f='${Status}' "$p" 2>/dev/null | grep -q "install ok installed" || missing+=("$p"); done
if ((${#missing[@]})); then
  echo "apt: installing ${missing[*]}"
  sudo apt-get update -qq
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends "${missing[@]}" >/dev/null
fi

if [[ ! -f "$STAMP" ]]; then
  mkdir -p "$ROOT"
  dl="$(mktemp -d "$ROOT/dl.XXXXXX")"     # fresh, empty directory for the untrusted download
  x="$(mktemp -d "$ROOT/extract.XXXXXX")"
  echo "downloading $ASSET ($TAG)"
  curl -fsSL --retry 3 -o "$dl/$ASSET" "https://github.com/bambulab/BambuStudio/releases/download/$TAG/$ASSET"
  echo "$SHA256  $dl/$ASSET" | sha256sum -c --quiet -
  chmod +x "$dl/$ASSET"
  (cd "$x" && "$dl/$ASSET" --appimage-extract >/dev/null)   # no FUSE needed
  rm -rf "$APP"
  mv "$x/squashfs-root" "$APP"
  rm -rf "$dl" "$x"
  # The CLI reads printer_model_id (written to slice_info.config, "O1D" for the
  # H2D) from profiles/BBL/machine_full/<printer_model>.json, a directory the
  # AppImage does not ship. Without it the sliced 3MF has an empty model id.
  mkdir -p "$APP/resources/profiles/BBL/machine_full"
  cp "$APP/resources/profiles/BBL/machine/Bambu Lab H2D.json" "$APP/resources/profiles/BBL/machine_full/"
  touch "$STAMP"
fi

if LD_LIBRARY_PATH="$APP/bin" ldd "$APP/bin/bambu-studio" | grep "not found"; then
  echo "ERROR: unresolved shared libraries (above); install the providing packages" >&2
  exit 1
fi
# Run from $ROOT: the CLI writes a result.json into its working directory.
help="$(cd "$ROOT" && LD_LIBRARY_PATH="$APP/bin" LC_ALL=C "$APP/bin/bambu-studio" --help)"
echo "${help%%$'\n'*}"
echo "Bambu Studio ready at $APP"
