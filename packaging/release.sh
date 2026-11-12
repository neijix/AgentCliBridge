#!/bin/bash
# Build this OS's installer package, and upload it to a GitHub Release (what `make package` and
# `make release` run).
#
#   packaging/release.sh package [--tag vX.Y.Z] [--repo OWNER/REPO] [--out DIR] [--repo-dir DIR]
#   packaging/release.sh release [--tag vX.Y.Z] [--repo OWNER/REPO] [--out DIR] [--repo-dir DIR] [--clobber] [--no-sums]
#   packaging/release.sh sums [--tag vX.Y.Z] [--repo OWNER/REPO] [--repo-dir DIR]
#
# package   Builds the snapshot archive once (`python -m bridge_installer.release snapshot`), then the
#           current OS's package from those same bytes: Linux build-deb.sh, macOS build-pkg.sh, Windows
#           build-exe.ps1. Both land in --out (default: dist). Without --tag it builds HEAD.
# release   `package` for the tag (--tag, else the v* tag at HEAD; none is an error), then uploads with
#           gh to that tag's Release:
#             - the Release is created when missing (--verify-tag: the tag must already be pushed), as a
#               prerelease when the version has a "-" suffix (v0.0.0-test.1);
#             - a package already attached is refused, naming it, unless --clobber;
#             - the snapshot archive is uploaded only when the Release lacks it: byte-equal -> skipped,
#               different -> refused (--clobber does not replace it);
#             - SHA256SUMS is then rewritten from every other asset attached and read back, up to 3
#               tries, failing with the names it still lacks.
#           So each OS is released from a machine of that OS, in any order. --no-sums stops after the
#           upload: the release workflow's build jobs use it, so only its last job writes SHA256SUMS.
# sums      Only the SHA256SUMS step of `release`, for the tag's existing Release: nothing is built or
#           uploaded but SHA256SUMS.
#
# --repo defaults to $GITHUB_REPOSITORY, else the github.com `origin`; --repo-dir is the checkout to
# build from (default: this one). $PYTHON picks the interpreter (default python3, else python).
# $AGENTCLIBRIDGE_PACKAGE_OS (Linux, Darwin or Windows) replaces `uname -s`; tests use it.
set -euo pipefail

die() {
  echo "ERROR: $*" >&2
  exit 1
}

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/.." && pwd)"
SUMS_NAME="SHA256SUMS"   # bridge_installer/release.py SUMS_NAME
SUMS_TRIES=3

mode="${1:-}"
case "$mode" in
  package | release | sums) shift ;;
  -h | --help) sed -n '2,/^set -euo/p' "${BASH_SOURCE[0]}" | sed '$d;s/^# \{0,1\}//'; exit 0 ;;
  *) die "usage: release.sh package|release|sums [--tag vX.Y.Z] [--repo OWNER/REPO] [--out DIR] [--repo-dir DIR] [--clobber] [--no-sums]" ;;
esac

tag="" repo="" out="dist" src="$REPO_ROOT" clobber="" sums=1
while [ $# -gt 0 ]; do
  case "$1" in
    --tag) [ $# -ge 2 ] || die "--tag needs a value"; tag="$2"; shift 2 ;;
    --repo) [ $# -ge 2 ] || die "--repo needs OWNER/REPO"; repo="$2"; shift 2 ;;
    --out) [ $# -ge 2 ] || die "--out needs a folder"; out="$2"; shift 2 ;;
    --repo-dir) [ $# -ge 2 ] || die "--repo-dir needs a folder"; src="$2"; shift 2 ;;
    --clobber) [ "$mode" = release ] || die "--clobber belongs to release"; clobber=1; shift ;;
    --no-sums) [ "$mode" = release ] || die "--no-sums belongs to release"; sums=""; shift ;;
    -h | --help) sed -n '2,/^set -euo/p' "${BASH_SOURCE[0]}" | sed '$d;s/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

py="${PYTHON:-}"
if [ -z "$py" ]; then
  if command -v python3 >/dev/null 2>&1; then py=python3; else py=python; fi
fi
# A Windows path (C:\...\python.exe, as `uv python find` prints it under Git Bash) has no "/", so bash
# would look it up on PATH: C:/.../python.exe runs.
py="${py%$'\r'}"
py="${py//\\//}"
src="$(cd "$src" && pwd)" || die "--repo-dir is not a folder"
mkdir -p "$out"
out="$(cd "$out" && pwd)"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
log="$work/stderr.log"

# --- tag, repo, package kind ------------------------------------------------------------------------

if [ "$mode" != package ] && [ -z "$tag" ]; then
  tag="$(git -C "$src" describe --tags --exact-match --match 'v*' HEAD 2>/dev/null)" ||
    die "HEAD has no v* tag: pass --tag vX.Y.Z (or tag the commit first)"
fi

if [ -z "$repo" ]; then
  repo="${GITHUB_REPOSITORY:-}"
fi
if [ -z "$repo" ]; then
  url="$(git -C "$src" remote get-url origin 2>/dev/null || true)"
  repo="$(printf '%s\n' "$url" | sed -n 's#^.*github\.com[:/][:/]*\([^/][^/]*\)/\([^/][^/]*\)$#\1/\2#p' | sed 's#\.git$##;s#/$##')"
fi
[ -n "$repo" ] || die "cannot tell the GitHub repo: pass --repo OWNER/REPO (origin is not a github.com remote)"

# --- SHA256SUMS: rewritten from every asset on the Release, read back, up to SUMS_TRIES tries ----------

# Names of the assets on the Release, one per line (stdin: gh's JSON).
asset_names() {
  "$py" -I -c 'import json, sys
for asset in json.load(sys.stdin).get("assets") or []:
    print(asset["name"])' | tr -d '\r'
}

write_sums() {
  local try=1 attached line missing
  while :; do
    attached="$work/attached-$try"
    mkdir -p "$attached" "$work/sums-$try" "$work/back-$try"
    gh release download "$tag" --repo "$repo" --pattern '*' --dir "$attached" 2>"$log" || {
      cat "$log" >&2
      die "cannot download the assets of $tag to hash them"
    }
    rm -f "$attached/$SUMS_NAME"
    set -- "$attached"/*
    [ -f "$1" ] || die "$tag has no asset to list in $SUMS_NAME"
    (cd "$REPO_ROOT" && PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}" "$py" -m bridge_installer.release sums "$@" --out "$work/sums-$try/$SUMS_NAME" >/dev/null) ||
      die "could not write $SUMS_NAME"
    gh release upload "$tag" --repo "$repo" "$work/sums-$try/$SUMS_NAME" --clobber || die "cannot upload $SUMS_NAME to $tag"
    gh release download "$tag" --repo "$repo" --pattern "$SUMS_NAME" --dir "$work/back-$try" 2>"$log" || {
      cat "$log" >&2
      die "cannot read $SUMS_NAME back from $tag"
    }
    missing=""
    while IFS= read -r line; do
      if ! grep -Fxq -- "$line" "$work/back-$try/$SUMS_NAME"; then
        missing="$missing ${line#*  }"
      fi
    done <"$work/sums-$try/$SUMS_NAME"
    # Another writer may have attached an asset after this run downloaded them: every asset on the
    # Release now, not only the ones hashed here, must be in the file read back.
    view="$(gh release view "$tag" --repo "$repo" --json assets 2>"$log")" || {
      cat "$log" >&2
      die "cannot list the assets of $tag"
    }
    while IFS= read -r line; do
      [ -n "$line" ] && [ "$line" != "$SUMS_NAME" ] || continue
      awk -v name="$line" 'substr($0, index($0, "  ") + 2) == name { found = 1 } END { exit !found }' \
        "$work/back-$try/$SUMS_NAME" || missing="$missing $line"
    done <<<"$(printf '%s' "$view" | asset_names)"
    [ -n "$missing" ] || return 0
    if [ "$try" -ge "$SUMS_TRIES" ]; then
      die "$SUMS_NAME on $tag still lacks (or has another digest for):$missing, after $SUMS_TRIES tries"
    fi
    echo "$SUMS_NAME on $tag lacks:$missing; rewriting (try $((try + 1)) of $SUMS_TRIES)" >&2
    try=$((try + 1))
  done
}

if [ "$mode" = sums ]; then
  command -v gh >/dev/null 2>&1 || die "gh is not installed or not on PATH (https://cli.github.com)"
  write_sums
  echo "$SUMS_NAME on $tag of $repo lists every asset" >&2
  exit 0
fi

case "${AGENTCLIBRIDGE_PACKAGE_OS:-$(uname -s)}" in
  Linux) kind=deb ;;
  Darwin) kind=pkg ;;
  MINGW* | MSYS* | CYGWIN* | Windows*) kind=exe ;;
  *) die "no installer package for $(uname -s)" ;;
esac

# --- package: the snapshot once, then this OS's package from those bytes -----------------------------

to_native() { if command -v cygpath >/dev/null 2>&1; then cygpath -w "$1"; else printf '%s\n' "$1"; fi; }
from_native() { if command -v cygpath >/dev/null 2>&1; then cygpath -u "$1"; else printf '%s\n' "$1"; fi; }

snapshot_args=(snapshot --out "$out" --repo-dir "$src" --repo "$repo")
[ -z "$tag" ] || snapshot_args+=(--tag "$tag")
snapshot="$(cd "$REPO_ROOT" && PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}" "$py" -m bridge_installer.release "${snapshot_args[@]}" 2>"$log")" || {
  cat "$log" >&2
  die "could not build the snapshot archive"
}
snapshot="$(from_native "$(printf '%s\n' "$snapshot" | tail -n 1 | tr -d '\r')")"
[ -f "$snapshot" ] || die "the snapshot builder printed no archive: $snapshot"

case "$kind" in
  deb) built="$(bash "$HERE/linux/build-deb.sh" --snapshot "$snapshot" --out "$out")" || die "build-deb.sh failed" ;;
  pkg) built="$(bash "$HERE/macos/build-pkg.sh" --snapshot "$snapshot" --out "$out")" || die "build-pkg.sh failed" ;;
  exe)
    shell="$(command -v pwsh || command -v powershell.exe || true)"
    [ -n "$shell" ] || die "PowerShell is needed to build the .exe (pwsh or powershell.exe)"
    built="$("$shell" -NoProfile -File "$(to_native "$HERE/windows/build-exe.ps1")" \
      -Archive "$(to_native "$snapshot")" -OutDir "$(to_native "$out")")" || die "build-exe.ps1 failed"
    built="$(from_native "$(printf '%s\n' "$built" | tail -n 1 | tr -d '\r')")"
    ;;
esac
package="$(printf '%s\n' "$built" | tail -n 1)"
[ -f "$package" ] || die "the package builder printed no file: $package"

if [ "$mode" = package ]; then
  echo "snapshot: $snapshot" >&2
  echo "$package"
  exit 0
fi

# --- release: upload -------------------------------------------------------------------------------

command -v gh >/dev/null 2>&1 || die "gh is not installed or not on PATH (https://cli.github.com)"
pkg_name="$(basename "$package")"
snap_name="$(basename "$snapshot")"
version="${tag#v}"

release_exists=1
assets=""
if view="$(gh release view "$tag" --repo "$repo" --json assets 2>"$log")"; then
  assets="$(printf '%s' "$view" | asset_names)" || die "gh gave no list of assets for $tag"
elif grep -qi 'release not found' "$log"; then
  release_exists=""
else
  cat "$log" >&2
  die "cannot read the Release $tag of $repo with gh"
fi

has_asset() { printf '%s\n' "$assets" | grep -Fxq -- "$1"; }

if [ -n "$release_exists" ] && has_asset "$pkg_name" && [ -z "$clobber" ]; then
  die "$tag already has $pkg_name: nothing was uploaded; pass --clobber (make release CLOBBER=1) to replace it"
fi

upload_snapshot=1
if [ -n "$release_exists" ] && has_asset "$snap_name"; then
  mkdir -p "$work/existing"
  gh release download "$tag" --repo "$repo" --pattern "$snap_name" --dir "$work/existing" 2>"$log" || {
    cat "$log" >&2
    die "cannot download $snap_name from $tag to compare it"
  }
  if cmp -s "$work/existing/$snap_name" "$snapshot"; then
    echo "$snap_name is already on $tag and byte-equal: skipped" >&2
    upload_snapshot=""
  else
    die "$tag already has a different $snap_name: the same commit builds the same bytes, so it came from another commit or toolchain; nothing was uploaded; delete that asset (gh release delete-asset $tag $snap_name) or release a new tag"
  fi
fi

if [ -z "$release_exists" ]; then
  create_args=(release create "$tag" --repo "$repo" --title "$tag" --notes "AgentCliBridge $version installers." --verify-tag)
  case "$version" in *-*) create_args+=(--prerelease) ;; esac
  gh "${create_args[@]}" || die "cannot create the Release $tag of $repo (is the tag pushed?)"
fi

upload_args=(release upload "$tag" --repo "$repo" "$package")
[ -z "$upload_snapshot" ] || upload_args+=("$snapshot")
[ -z "$clobber" ] || upload_args+=(--clobber)
gh "${upload_args[@]}" || die "cannot upload to $tag"

if [ -z "$sums" ]; then
  echo "released $pkg_name to $tag of $repo; $SUMS_NAME left to \`release.sh sums\`" >&2
  echo "$package"
  exit 0
fi
write_sums
echo "released $pkg_name and $snap_name to $tag of $repo; $SUMS_NAME lists every asset" >&2
echo "$package"
