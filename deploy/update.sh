#!/usr/bin/env bash
# Update the server to the newest code from GitHub: every step, in the right order,
# as the right user. Run it from the project folder after each push:
#
#     sudo bash deploy/update.sh            # finds the service by itself
#     sudo bash deploy/update.sh cafe1      # or name the service
#
# 1 code (git pull)   2 packages   3 folders the app writes (owned by the app's user)
# 4 database (migrate)   5 static files (collectstatic)   6 restart   7 check_setup
# A missed step was behind every error 500 after an update; this does them all.
set -euo pipefail

[ "$(id -u)" = 0 ] || { echo "Run it with sudo:  sudo bash deploy/update.sh"; exit 1; }
cd "$(dirname "$0")/.."
APP_DIR=$(pwd)

say() { printf '\n\033[1;31m== %s\033[0m\n' "$1"; }
run_as() {  # run_as <user> <command...>
  local who=$1; shift
  if [ "$who" = root ]; then "$@"; else sudo -u "$who" -H "$@"; fi
}

# ---------------------------------------------------------- what runs this folder
SERVICE=${1:-}
if [ -z "$SERVICE" ]; then
  unit=$(grep -ls "^WorkingDirectory=$APP_DIR/\?\s*$" /etc/systemd/system/*.service | head -n1 || true)
  SERVICE=$(basename "${unit:-}" .service)
fi
[ -n "$SERVICE" ] && systemctl cat "$SERVICE" >/dev/null 2>&1 || {
  echo "No systemd service found for $APP_DIR. Name it:  sudo bash deploy/update.sh <service>"; exit 1; }
APP_USER=$(systemctl show -p User --value "$SERVICE"); APP_USER=${APP_USER:-root}
GUNICORN=$(systemctl show -p ExecStart --value "$SERVICE" | grep -o 'path=[^ ;]*' | head -n1 | cut -d= -f2 || true)
PY="$(dirname "${GUNICORN:-/nonexistent/x}")/python"
for candidate in "$PY" venv/bin/python .venv/bin/python env/bin/python; do
  if [ -x "$candidate" ]; then PY=$candidate; break; fi
done
[ -x "$PY" ] || { echo "Could not find the virtual environment's python."; exit 1; }
echo "Folder $APP_DIR · service $SERVICE · user $APP_USER · python $PY"

# ---------------------------------------------------------- 1 code
say "1/7 Code from GitHub"
run_as "$(stat -c %U .git)" git -C "$APP_DIR" pull --ff-only

# ---------------------------------------------------------- 2 packages
say "2/7 Python packages"
run_as "$(stat -c %U "$(dirname "$PY")")" "$PY" -m pip install --quiet --disable-pip-version-check -r requirements.txt

# ---------------------------------------------------------- 3 folders the app writes
say "3/7 Folders the app writes (owner: $APP_USER)"
CACHE_DIR=$(grep -E '^CACHE_DIR=' .env 2>/dev/null | tail -n1 | cut -d= -f2- | tr -d '"'"'" || true)
CACHE_DIR=${CACHE_DIR:-$APP_DIR/cache}
MEDIA_DIR=$(grep -E '^MEDIA_ROOT=' .env 2>/dev/null | tail -n1 | cut -d= -f2- | tr -d '"'"'" || true)
MEDIA_DIR=${MEDIA_DIR:-$APP_DIR/media}
for folder in "$APP_DIR/staticfiles" "$MEDIA_DIR" "$CACHE_DIR"; do
  mkdir -p "$folder"
  chown -R "$APP_USER" "$folder"
  echo "  $folder"
done

# ---------------------------------------------------------- 4, 5
say "4/7 Database (migrate)"
run_as "$APP_USER" "$PY" manage.py migrate --noinput

say "5/7 Static files (collectstatic)"
run_as "$APP_USER" "$PY" manage.py collectstatic --noinput | tail -n 1

# ---------------------------------------------------------- 6 restart
say "6/7 Restart $SERVICE"
systemctl restart "$SERVICE"
sleep 2
if ! systemctl is-active --quiet "$SERVICE"; then
  echo "$SERVICE did not start. Its last lines:"
  journalctl -u "$SERVICE" -n 30 --no-pager
  exit 1
fi
echo "  $SERVICE is running"

# ---------------------------------------------------------- 7 check
say "7/7 Check (settings, database, files, pages, logins)"
if run_as "$APP_USER" "$PY" manage.py check_setup; then
  printf '\nUpdated. In the browser press Ctrl+F5 once.\n'
else
  printf '\nUpdated, but check_setup found the problem(s) above: each FAIL line says the fix.\n'
  exit 1
fi
