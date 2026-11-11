#!/bin/sh
set -eu
source_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
if [ "$(uname -s)" != Darwin ]; then
    printf '%s\n' 'This installer supports macOS. On Windows, run Install.cmd.' >&2
    exit 1
fi
macos_version=$(sw_vers -productVersion)
macos_major=${macos_version%%.*}
if [ "$macos_major" -lt 13 ]; then
    printf '%s\n' 'AI Song Detection requires macOS 13 or later.' >&2
    exit 1
fi
case "$(uname -m)" in
    arm64|aarch64)
        target=aarch64-apple-darwin
        expected=743f85035a1996ecb350659e01cd9faea9709829be09b1b4b03c73eaf3c9cd73 ;;
    x86_64)
        target=x86_64-apple-darwin
        expected=b0f52b0e3945b4107d89024ea38e625683011fbfc05a0d98f9fa2d6dcee28c66 ;;
    *) printf '%s\n' 'Unsupported Mac architecture.' >&2; exit 1 ;;
esac
install_root=${AI_SONG_DETECTION_INSTALL_DIR:-"$HOME/Library/Application Support/AI Song Detection"}
version=0.13.5
bootstrap="$install_root/bootstrap/uv-$version-$target"
uv="$bootstrap/uv"
mkdir -p "$install_root/downloads" "$install_root/bootstrap"
if [ ! -x "$uv" ]; then
    printf '%s\n' 'Preparing the private installer. No system Python or Homebrew is required.'
    archive="$install_root/downloads/uv-$version-$target.tar.gz"
    if [ ! -f "$archive" ] || [ "$(shasum -a 256 "$archive" | cut -d ' ' -f 1)" != "$expected" ]; then
        curl --fail --location --retry 3 --connect-timeout 20 --max-time 300 \
            --proto '=https' --tlsv1.2 \
            "https://github.com/astral-sh/uv/releases/download/$version/uv-$target.tar.gz" \
            --output "$archive.part"
        actual=$(shasum -a 256 "$archive.part" | cut -d ' ' -f 1)
        if [ "$actual" != "$expected" ]; then
            rm -f "$archive.part"
            printf '%s\n' 'Installer checksum verification failed. Nothing was executed.' >&2
            exit 1
        fi
        mv -f "$archive.part" "$archive"
    fi
    stage=$(mktemp -d "$install_root/bootstrap/uv-stage.XXXXXX")
    trap 'rm -rf "$stage"' EXIT HUP INT TERM
    tar -xzf "$archive" -C "$stage"
    mkdir -p "$bootstrap"
    cp "$stage/uv-$target/uv" "$uv"
    chmod 700 "$uv"
    rm -rf "$stage"
    trap - EXIT HUP INT TERM
fi
export UV_PYTHON_INSTALL_DIR="$install_root/runtime/python"
export UV_CACHE_DIR="$install_root/cache/uv"
export UV_PYTHON_PREFERENCE=only-managed
export UV_NO_MODIFY_PATH=1
export UV_PYTHON_INSTALL_BIN=0
printf '%s\n' 'Preparing private Python 3.12...'
"$uv" python install 3.12
exec "$uv" run --no-project --no-config --python 3.12 python \
    "$source_dir/src/ai_song_detection/installer.py" --source "$source_dir" --uv "$uv" "$@"
