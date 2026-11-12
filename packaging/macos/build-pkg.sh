#!/bin/sh
# Builds dist/agentclibridge-<version>-macos-all.pkg, the macOS installer (run it on a Mac: pkgbuild and
# productbuild ship with Xcode's command line tools).
#
#   build-pkg.sh [--snapshot FILE] [--tag vX.Y.Z] [--repo OWNER/REPO] [--out DIR] [--stage-only] [--stage-dir DIR]
#
#   --snapshot FILE  use this agentclibridge-<version>-any-all-snapshot.tar.gz (default: build one, from --tag or HEAD,
#                    with `python -m bridge_installer.release snapshot`; PYTHON picks the interpreter)
#   --out DIR        where the .pkg goes (default: <repo>/dist)
#   --stage-only     stop after staging the scripts folder (no pkgbuild needed), print its path
#   --stage-dir DIR  stage there (default: a temporary folder; with --stage-only, <out>/pkg-stage)
#
# The package is payload-free: its scripts folder holds postinstall, VERSION and setup.tar.gz (the
# setup.sh / setup.ps1 twins and the snapshot as app/). It is unsigned unless AGENTCLIBRIDGE_PKG_SIGN_IDENTITY
# names a "Developer ID Installer" identity (AGENTCLIBRIDGE_PKG_SIGN_KEYCHAIN picks the keychain).
set -eu

die() {
  echo "ERROR: $*" >&2
  exit 1
}

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
IDENTIFIER="org.agentclibridge.setup"
COMPONENT="AgentCliBridge-setup.pkg"
MANIFEST_NAME="agentclibridge-snapshot.json"   # bridge_installer MANIFEST_NAME

snapshot=""
tag=""
repo=""
out="$ROOT/dist"
stage_only=""
stage_dir=""
while [ $# -gt 0 ]; do
  case "$1" in
    --snapshot) [ $# -ge 2 ] || die "--snapshot needs a file"; snapshot="$2"; shift 2 ;;
    --tag) [ $# -ge 2 ] || die "--tag needs a value"; tag="$2"; shift 2 ;;
    --repo) [ $# -ge 2 ] || die "--repo needs OWNER/REPO"; repo="$2"; shift 2 ;;
    --out) [ $# -ge 2 ] || die "--out needs a folder"; out="$2"; shift 2 ;;
    --stage-dir) [ $# -ge 2 ] || die "--stage-dir needs a folder"; stage_dir="$2"; shift 2 ;;
    --stage-only) stage_only=1; shift ;;
    -h | --help) sed -n '2,/^set -eu/p' "$0" | sed '$d;s/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown argument: $1 (see --help)" ;;
  esac
done

WORK="$(mktemp -d "${TMPDIR:-/tmp}/agentclibridge-pkg.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT HUP INT TERM

mkdir -p "$out"
out="$(cd "$out" && pwd)"

if [ -z "$snapshot" ]; then
  mkdir "$WORK/snapshot"
  set -- --out "$WORK/snapshot"
  [ -z "$tag" ] || set -- "$@" --tag "$tag"
  [ -z "$repo" ] || set -- "$@" --repo "$repo"
  snapshot="$(cd "$ROOT" && "${PYTHON:-python3}" -m bridge_installer.release snapshot "$@")" ||
    die "the snapshot build failed"
fi
[ -f "$snapshot" ] || die "no snapshot at $snapshot"
snapshot="$(cd "$(dirname "$snapshot")" && pwd)/$(basename "$snapshot")"

version="$(basename "$snapshot")"
case "$version" in
  agentclibridge-*-any-all-snapshot.tar.gz) ;;
  *) die "the snapshot must be named agentclibridge-<version>-any-all-snapshot.tar.gz, not $version" ;;
esac
version="${version#agentclibridge-}"
version="${version%-any-all-snapshot.tar.gz}"
case "$version" in
  "" | *[!0-9A-Za-z.+-]*) die "'$version' is not a version" ;;
esac

if [ -z "$stage_dir" ]; then
  if [ -n "$stage_only" ]; then stage_dir="$out/pkg-stage"; else stage_dir="$WORK/stage"; fi
fi
rm -rf "${stage_dir:?}/scripts" "${stage_dir:?}/distribution.xml"
mkdir -p "$stage_dir/scripts" "$WORK/tree/app"
stage_dir="$(cd "$stage_dir" && pwd)"

# The setup folder as the postinstall unpacks it: setup.sh, setup.ps1 and the snapshot as app/.
tar -xzf "$snapshot" -C "$WORK/tree/app" || die "cannot unpack $snapshot"
[ -f "$WORK/tree/app/$MANIFEST_NAME" ] || die "$snapshot holds no $MANIFEST_NAME: it is not a snapshot archive"
cp "$ROOT/packaging/setup.sh" "$ROOT/packaging/setup.ps1" "$WORK/tree/"
chmod 755 "$WORK/tree/setup.sh"
chmod 644 "$WORK/tree/setup.ps1"
# No AppleDouble members or extended attributes (a quarantine flag would come back on unpacking).
COPYFILE_DISABLE=1 tar -czf "$stage_dir/scripts/setup.tar.gz" -C "$WORK/tree" setup.sh setup.ps1 app ||
  die "cannot pack the setup folder"
cp "$HERE/postinstall" "$stage_dir/scripts/postinstall"
chmod 755 "$stage_dir/scripts/postinstall"
printf '%s' "$version" > "$stage_dir/scripts/VERSION"
sed "s/@VERSION@/$version/g" "$HERE/distribution.xml" > "$stage_dir/distribution.xml"

if [ -n "$stage_only" ]; then
  echo "$stage_dir"
  exit 0
fi

command -v pkgbuild >/dev/null 2>&1 || die "pkgbuild not found: build the .pkg on a Mac with Xcode's command line tools"
command -v productbuild >/dev/null 2>&1 || die "productbuild not found: build the .pkg on a Mac with Xcode's command line tools"

# Signing is optional: an identity makes both packages signed, otherwise they stay unsigned.
signing=""
[ -z "${AGENTCLIBRIDGE_PKG_SIGN_IDENTITY:-}" ] || signing=1

mkdir "$WORK/components"
set -- --nopayload --scripts "$stage_dir/scripts" --identifier "$IDENTIFIER" --version "$version"
if [ -n "$signing" ]; then
  set -- "$@" --sign "$AGENTCLIBRIDGE_PKG_SIGN_IDENTITY"
  [ -z "${AGENTCLIBRIDGE_PKG_SIGN_KEYCHAIN:-}" ] || set -- "$@" --keychain "$AGENTCLIBRIDGE_PKG_SIGN_KEYCHAIN"
fi
pkgbuild "$@" "$WORK/components/$COMPONENT" || die "pkgbuild failed"

target="$out/agentclibridge-$version-macos-all.pkg"
rm -f "$target"
set -- --distribution "$stage_dir/distribution.xml" --package-path "$WORK/components"
if [ -n "$signing" ]; then
  set -- "$@" --sign "$AGENTCLIBRIDGE_PKG_SIGN_IDENTITY"
  [ -z "${AGENTCLIBRIDGE_PKG_SIGN_KEYCHAIN:-}" ] || set -- "$@" --keychain "$AGENTCLIBRIDGE_PKG_SIGN_KEYCHAIN"
fi
productbuild "$@" "$target" || die "productbuild failed"

if [ -n "$signing" ]; then echo "signed with $AGENTCLIBRIDGE_PKG_SIGN_IDENTITY" >&2; else echo "unsigned (AGENTCLIBRIDGE_PKG_SIGN_IDENTITY is not set)" >&2; fi
echo "$target"
