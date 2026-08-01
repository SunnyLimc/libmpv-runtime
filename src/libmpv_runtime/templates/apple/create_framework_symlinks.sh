#!/bin/sh
set -eu
source_dir="$1"
links_dir="$2"
relpath() {
  current="${2:+$1}"; target="${2:-$1}"; target="/${target##/}"; current="/${current##/}"
  appendix="${target##/}"; relative=''
  while appendix="${target#"$current"/}"; [ "$current" != '/' ] && [ "$appendix" = "$target" ]; do
    if [ "$current" = "$appendix" ]; then echo "${relative:-.}"; return 0; fi
    current="${current%/*}"; relative="$relative${relative:+/}.."
  done
  echo "$relative${relative:+${appendix:+/}}${appendix#/}"
}
find "$source_dir" -mindepth 1 -maxdepth 1 -type d | while IFS= read -r source; do
  slug="$(basename "$source")"; name="$(echo "$slug" | cut -d '-' -f 1,3)"
  ln -s "$(relpath "$links_dir" "$source")" "$links_dir/$name"
done
