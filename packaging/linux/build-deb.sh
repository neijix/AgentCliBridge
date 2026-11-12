#!/bin/bash
# Build agentclibridge-<version>-linux-all.deb from the release snapshot archive (Linux, needs dpkg-deb).
#
#   packaging/linux/build-deb.sh [--snapshot FILE] [--out DIR] [--tag vX.Y.Z] [--repo OWNER/REPO]
#
# --snapshot  the agentclibridge-<version>-any-all-snapshot.tar.gz of `python -m bridge_installer.release snapshot`;
#             without it that command builds one (from --tag, else HEAD) in a temporary folder.
# --out       where the .deb goes (default: dist). Its path is printed.
#
# The package holds only:
#   /opt/agentclibridge/setup.sh        the bootstrap twin (setup.ps1 is Windows-only, so it is left out)
#   /opt/agentclibridge/app/...         the snapshot, its manifest included
#   /usr/bin/agentclibridge-setup       runs /opt/agentclibridge/setup.sh "$@"
# No maintainer scripts: installing it writes nothing in any home folder. Each user then runs
# `agentclibridge-setup` to install into a folder of their own.
#
# The version is the snapshot manifest's. A SemVer pre-release suffix (1.0.0-rc.1) becomes
# 1.0.0~rc.1 in the control file, so it sorts before 1.0.0; the file name keeps the manifest's text.
# Same snapshot and same SOURCE_DATE_EPOCH (default: the commit's time, else 1980-01-01) give the same
# bytes: sorted contents, fixed times and modes, root ownership through --root-owner-group.
set -euo pipefail

die() {
  echo "ERROR: $*" >&2
  exit 1
}

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
MANIFEST_NAME="agentclibridge-snapshot.json"   # bridge_installer MANIFEST_NAME
OPT_DIR="opt/agentclibridge"

snapshot="" out="dist" tag="" repo=""
while [ $# -gt 0 ]; do
  case "$1" in
    --snapshot) [ $# -ge 2 ] || die "--snapshot needs a file"; snapshot="$2"; shift 2 ;;
    --out) [ $# -ge 2 ] || die "--out needs a folder"; out="$2"; shift 2 ;;
    --tag) [ $# -ge 2 ] || die "--tag needs a value"; tag="$2"; shift 2 ;;
    --repo) [ $# -ge 2 ] || die "--repo needs OWNER/REPO"; repo="$2"; shift 2 ;;
    -h | --help) sed -n '2,/^set -euo/p' "${BASH_SOURCE[0]}" | sed '$d;s/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

command -v dpkg-deb >/dev/null 2>&1 || die "dpkg-deb is not installed (Debian, Ubuntu or a dpkg package)"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
umask 022

if [ -z "$snapshot" ]; then
  args=(snapshot --out "$work")
  [ -z "$tag" ] || args+=(--tag "$tag")
  [ -z "$repo" ] || args+=(--repo "$repo")
  built="$(cd "$REPO_ROOT" && PYTHONPATH="$REPO_ROOT" "${PYTHON:-python3}" -m bridge_installer.release "${args[@]}")" ||
    die "could not build the snapshot archive"
  snapshot="$built"
fi
[ -f "$snapshot" ] || die "$snapshot is not a file"
snapshot="$(cd "$(dirname "$snapshot")" && pwd)/$(basename "$snapshot")"
out="$(mkdir -p "$out" && cd "$out" && pwd)"

# Nothing outside the snapshot's own folder: no absolute path, no "..".
# The listing is read whole first: `tar | grep -q` would let tar die of SIGPIPE on an early match,
# and under pipefail the failed pipeline would wave the archive through.
listing="$(tar -tzf "$snapshot")" || die "cannot list $snapshot"
if grep -E '(^/|(^|/)\.\.(/|$))' <<<"$listing" >/dev/null; then
  die "$snapshot holds an absolute or parent-relative path"
fi
manifest="$(tar -xzOf "$snapshot" "$MANIFEST_NAME" 2>/dev/null)" ||
  die "$snapshot holds no $MANIFEST_NAME: it is not an AgentCliBridge snapshot"
version="$(printf '%s\n' "$manifest" | sed -n 's/^[[:space:]]*"version":[[:space:]]*"\([^"]*\)".*/\1/p' | head -n 1)"
printf '%s' "$version" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$' ||
  die "the manifest's version (${version:-none}) is not a SemVer version"
commit="$(printf '%s\n' "$manifest" | sed -n 's/^[[:space:]]*"commit":[[:space:]]*"\([^"]*\)".*/\1/p' | head -n 1)"
deb_version="${version/-/\~}"

if [ -z "${SOURCE_DATE_EPOCH:-}" ]; then
  SOURCE_DATE_EPOCH=""
  if printf '%s' "$commit" | grep -qE '^[0-9a-f]{40}$'; then
    SOURCE_DATE_EPOCH="$(git -C "$REPO_ROOT" show -s --format=%ct "$commit" 2>/dev/null || true)"
  fi
  [ -n "$SOURCE_DATE_EPOCH" ] || SOURCE_DATE_EPOCH=315532800
fi
printf '%s' "$SOURCE_DATE_EPOCH" | grep -qE '^[0-9]+$' || die "SOURCE_DATE_EPOCH must be a number of seconds"
export SOURCE_DATE_EPOCH

stage="$work/stage"
mkdir -p "$stage/$OPT_DIR/app" "$stage/usr/bin" "$stage/DEBIAN"
tar -xzf "$snapshot" -C "$stage/$OPT_DIR/app" --no-same-owner --no-same-permissions
install -m 0755 "$REPO_ROOT/packaging/setup.sh" "$stage/$OPT_DIR/setup.sh"
install -m 0755 "$HERE/agentclibridge-setup" "$stage/usr/bin/agentclibridge-setup"
[ -f "$stage/$OPT_DIR/app/bridge_installer/__main__.py" ] || die "$snapshot holds no setup wizard"

# One mode per kind, whatever the archive or the umask said; one time for every file.
find "$stage" -type d -exec chmod 0755 {} +
find "$stage" -type f -perm /111 -exec chmod 0755 {} +
find "$stage" -type f ! -perm /111 -exec chmod 0644 {} +
find "$stage" -exec touch -h -d "@$SOURCE_DATE_EPOCH" {} +

size_kb="$(du -sk --exclude=DEBIAN "$stage" | cut -f1)"
cat >"$stage/DEBIAN/control" <<CONTROL
Package: agentclibridge
Version: $deb_version
Architecture: all
Maintainer: ${DEB_MAINTAINER:-AgentCliBridge packagers <noreply@agentclibridge.invalid>}
Section: utils
Priority: optional
Installed-Size: $size_kb
Depends: bash, curl | wget
Description: AgentCliBridge setup: the release snapshot and its installer
 Places the AgentCliBridge release snapshot and its setup wizard under
 /opt/agentclibridge, and the agentclibridge-setup command. Each user runs
 agentclibridge-setup to install the gateway into a folder of their own; the
 package writes nothing else.
CONTROL
chmod 0644 "$stage/DEBIAN/control"
touch -h -d "@$SOURCE_DATE_EPOCH" "$stage/DEBIAN" "$stage/DEBIAN/control"

target="$out/agentclibridge-${version}-linux-all.deb"
dpkg-deb --root-owner-group -Zxz -b "$stage" "$work/package.deb" >/dev/null
mv -f "$work/package.deb" "$target"
echo "$target"
