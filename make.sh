#!/usr/bin/env bash
# Quick content maker.  Examples:
#   ./make.sh video "why the ocean calms the mind"
#   ./make.sh image "3 signs you are healing"
#   ./make.sh text  "a 2-minute breathing reset"
cd "$(dirname "$0")"
kind="$1"; shift
case "$kind" in
  video) exec python3 scripts/make_video.py "$*" --scenes 4 ;;
  image|text) exec python3 scripts/make_post.py "$kind" "$*" ;;
  *) echo "usage: ./make.sh video|image|text \"topic\"" ; exit 1 ;;
esac
