#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "permission verification must run as root" >&2
  exit 1
fi

python_bin=${SWUDK_TEST_PYTHON:?SWUDK_TEST_PYTHON is required}
repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
state_root=$(mktemp -d /tmp/swu-checkin-state-test.XXXXXX)
trap 'rm -rf -- "$state_root"' EXIT

chown swu-checkin:swu-checkin "$state_root"
chmod 0770 "$state_root"

PYTHONPATH="$repo_root/src" "$python_bin" - "$state_root/status.json" <<'PY'
import sys

from swu_checkin.check_in import _record_run_status
from swu_checkin.status import CheckinStatus

_record_run_status(sys.argv[1], CheckinStatus.SUCCESS)
PY

chown swu-checkin:swu-checkin "$state_root/status.json"

[[ $(stat -c %a "$state_root/status.json") == 640 ]]
[[ $(stat -c %U "$state_root/status.json") == swu-checkin ]]
[[ $(stat -c %G "$state_root/status.json") == swu-checkin ]]
echo "status_mode=0640 owner=swu-checkin group=swu-checkin"

systemd-run --unit=swu-state-group-read-test --wait --collect --pipe --quiet \
  --property=Type=oneshot \
  --property=User=root \
  --property=Group=swu-checkin \
  --property=CapabilityBoundingSet= \
  /usr/bin/test -r "$state_root/status.json"
echo "group_read=ok capabilities=empty"

if systemd-run --unit=swu-state-unrelated-read-test --wait --collect --pipe --quiet \
  --property=Type=oneshot \
  --property=User=nobody \
  --property=Group=nogroup \
  --property=CapabilityBoundingSet= \
  /usr/bin/test -r "$state_root/status.json"; then
  echo "unrelated user unexpectedly read status.json" >&2
  exit 1
fi
echo "unrelated_read=denied capabilities=empty"

systemd-run --unit=swu-state-marker-write-test --wait --collect --pipe --quiet \
  --property=Type=oneshot \
  --property=User=root \
  --property=Group=swu-checkin \
  --property=CapabilityBoundingSet= \
  --property=UMask=0077 \
  /usr/bin/touch "$state_root/notified-test"

[[ -f "$state_root/notified-test" ]]
echo "marker_write=ok capabilities=empty"
