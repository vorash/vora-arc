#!/usr/bin/env bash
# Fetch the ARC-AGI-1 and ARC-AGI-2 public task sets into data/, each pinned
# to one upstream commit. Safe to rerun: a dataset whose stamp matches its pin
# is left alone, and a partial download never replaces a complete one.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
data="$root/data"

fetch() {
  local name="$1" repo="$2" commit="$3"
  local dest="$data/$name"
  if [[ -f "$dest/COMMIT" && "$(cat "$dest/COMMIT")" == "$commit" ]]; then
    echo "$name: already at $commit"
    return
  fi

  local work
  work="$(mktemp -d "$data/.$name.XXXXXX")"
  trap 'rm -rf "$work"' RETURN
  curl -fsSL "https://codeload.github.com/$repo/tar.gz/$commit" \
    | tar -xz -C "$work" --strip-components=2 --wildcards \
        '*/data/training/*.json' '*/data/evaluation/*.json'
  echo "$commit" > "$work/COMMIT"

  rm -rf "$dest"
  mv "$work" "$dest"
  echo "$name: $(ls "$dest/training" | wc -l) training, $(ls "$dest/evaluation" | wc -l) evaluation at $commit"
}

mkdir -p "$data"
fetch arc1 fchollet/ARC-AGI 399030444e0ab0cc8b4e199870fb20b863846f34
fetch arc2 arcprize/ARC-AGI-2 f3283f727488ad98fe575ea6a5ac981e4a188e49
