#!/bin/sh
set -u
source_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
/bin/sh "$source_dir/install/macos.sh" "$@"
result=$?
if [ "$result" -ne 0 ] && [ -t 0 ]; then
    printf '\nInstallation failed. Read the error above. Press Enter to close. '
    read -r answer
fi
exit "$result"
