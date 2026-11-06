#!/bin/bash
# Run the Valhalla routing server that tools/plan_routes.py needs, on localhost:8002.
#   tools/valhalla.sh up     copy the Arkansas road tiles into a Docker volume (first time) and start the server
#   tools/valhalla.sh down   stop and remove the server (the volume stays for next time)
#
# The road tiles were built by ~/arkansas-routing (OpenStreetMap Arkansas extract). That stack serves them straight
# from a macOS bind mount, which Docker reads so slowly that route requests time out (200 GB of reads in minutes);
# copying the 223 MB tile archive into a Docker volume fixes it. ~/arkansas-routing itself is left untouched, and its
# own server must be stopped first because both use port 8002.
set -euo pipefail
SRC="$HOME/arkansas-routing/data"
IMG="ghcr.io/valhalla/valhalla-scripted:latest"
VOL="mcd-valhalla"
case "${1:-}" in
  up)
    if docker ps --format '{{.Names}}' | grep -qx arkansas-routing-valhalla-1; then
      echo "stopping ~/arkansas-routing's valhalla (it holds port 8002)"; (cd "$HOME/arkansas-routing" && docker compose stop valhalla)
    fi
    docker volume inspect "$VOL" >/dev/null 2>&1 || docker volume create "$VOL" >/dev/null
    if ! docker run --rm -v "$VOL":/tiles --entrypoint test "$IMG" -s /tiles/valhalla_tiles.tar; then
      echo "copying tiles into volume $VOL"
      docker run --rm -v "$VOL":/tiles -v "$SRC":/src:ro --entrypoint sh "$IMG" -c '
        cp /src/valhalla_tiles.tar /src/admins.sqlite /src/timezones.sqlite /tiles/ &&
        sed -e "s#/custom_files/valhalla_tiles.tar#/tiles/valhalla_tiles.tar#" -e "s#/custom_files/valhalla_tiles\"#/tiles/none\"#" \
            -e "s#/custom_files/admins.sqlite#/tiles/admins.sqlite#" -e "s#/custom_files/timezones.sqlite#/tiles/timezones.sqlite#" \
            /src/valhalla.json > /tiles/valhalla.json'
    fi
    docker rm -f mcd-valhalla >/dev/null 2>&1 || true
    docker run -d --name mcd-valhalla -p 8002:8002 -v "$VOL":/tiles --entrypoint valhalla_service "$IMG" /tiles/valhalla.json 4 >/dev/null
    for _ in $(seq 1 30); do curl -sf localhost:8002/status >/dev/null && { echo "valhalla up on :8002"; exit 0; }; sleep 2; done
    echo "valhalla did not answer on :8002"; docker logs --tail 20 mcd-valhalla; exit 1 ;;
  down)
    docker rm -f mcd-valhalla >/dev/null 2>&1 && echo "valhalla stopped" || echo "not running" ;;
  *) echo "usage: $0 up|down"; exit 2 ;;
esac
