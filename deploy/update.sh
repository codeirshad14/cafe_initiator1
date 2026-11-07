#!/usr/bin/env bash
# Update the server to the newest code from GitHub: every step, in the right order,
# as the right user. Run it once from the project folder:
#
#     sudo bash deploy/update.sh            # finds the service by itself
#     sudo bash deploy/update.sh cafe1      # or name the service
#
# 1 code (git pull)   2 packages   3 folders the app writes (owned by the app's user)
# 4 database (migrate)   5 static files (collectstatic)   6 automatic from now on
# 7 restart   8 check_setup
#
# Step 6 makes every later update safe by itself: each start of the service first runs
# migrate and collectstatic (a systemd setting), and a plain "git pull" restarts the
# service (a git hook). A missed migrate / collectstatic was behind every error 500
# after an update; after this script has run once, that step can no longer be missed.
set -euo pipefail

main() {  # (all in a function: bash reads the whole script before git pull may change it)
  [ "$(id -u)" = 0 ] || { echo "Run it with sudo:  sudo bash deploy/update.sh"; exit 1; }
  cd "$(dirname "$0")/.."
  APP_DIR=$(pwd)
  SYSTEMD_DIR=${MRCAFE_SYSTEMD_DIR:-/etc/systemd/system}

  find_service "${1:-}"
  echo "Folder $APP_DIR · service $SERVICE · user $APP_USER · python $PY"

  say "1/8 Code from GitHub"
  # MRCAFE_UPDATING: the git hook (step 6) leaves the restart to this script
  run_as "$(stat -c %U .git)" env MRCAFE_UPDATING=1 git -C "$APP_DIR" pull --ff-only

  say "2/8 Python packages"
  run_as "$(stat -c %U "$(dirname "$PY")")" "$PY" -m pip install --quiet --disable-pip-version-check -r requirements.txt

  say "3/8 Folders the app writes (owner: $APP_USER)"
  read_dirs
  for folder in "$APP_DIR/staticfiles" "$MEDIA_DIR" "$CACHE_DIR"; do
    mkdir -p "$folder"
    chown -R "$APP_USER" "$folder"
    echo "  $folder"
  done

  say "4/8 Database (migrate)"
  waiting=$(run_as "$APP_USER" "$PY" manage.py showmigrations --plan 2>/dev/null | grep -c '^\[ \]' || true)
  echo "  $waiting change(s) to apply"
  run_as "$APP_USER" "$PY" manage.py migrate --noinput

  say "5/8 Static files (collectstatic)"
  run_as "$APP_USER" "$PY" manage.py collectstatic --noinput | tail -n 1

  say "6/8 Every later update: automatic"
  install_start_steps
  install_pull_hook

  say "7/8 Restart $SERVICE"
  systemctl restart "$SERVICE"
  sleep 2
  if ! systemctl is-active --quiet "$SERVICE"; then
    echo "$SERVICE did not start. Its last lines:"
    journalctl -u "$SERVICE" -n 30 --no-pager
    exit 1
  fi
  echo "  $SERVICE is running"

  say "8/8 Check (settings, database, files, pages, logins)"
  if run_as "$APP_USER" "$PY" manage.py check_setup; then
    printf '\nUpdated. In the browser press Ctrl+F5 once.\n'
  else
    printf '\nUpdated, but check_setup found the problem(s) above: each FAIL line says the fix.\n'
    exit 1
  fi
  printf 'From now on "git pull" here is the whole update (it restarts %s, which migrates and collects first).\n' "$SERVICE"
}

say() { printf '\n\033[1;31m== %s\033[0m\n' "$1"; }

run_as() {  # run_as <user> <command...>
  local who=$1; shift
  if [ "$who" = root ]; then "$@"; else sudo -u "$who" -H "$@"; fi
}

find_service() {
  # which systemd service runs this folder, as which user, with which Python (the one with Django)
  SERVICE=$1
  if [ -z "$SERVICE" ]; then
    local unit
    unit=$(grep -ls "^WorkingDirectory=$APP_DIR/\?\s*$" "$SYSTEMD_DIR"/*.service /lib/systemd/system/*.service 2>/dev/null | head -n1 || true)
    SERVICE=$(basename "${unit:-}" .service)
  fi
  if [ -z "$SERVICE" ] || ! systemctl cat "$SERVICE" >/dev/null 2>&1; then
    echo "No systemd service found for $APP_DIR. Name it:  sudo bash deploy/update.sh <service>"; exit 1
  fi
  APP_USER=$(systemctl show -p User --value "$SERVICE"); APP_USER=${APP_USER:-root}
  local start candidate
  start=$(systemctl show -p ExecStart --value "$SERVICE" || true)
  PY=""
  for candidate in $(printf '%s\n' "$start" | grep -oE '/[^ ;"]*/bin/' | sed 's|$|python|' | sort -u) \
                   "$APP_DIR/venv/bin/python" "$APP_DIR/.venv/bin/python" "$APP_DIR/env/bin/python"; do
    if [ -x "$candidate" ] && "$candidate" -c "import django" 2>/dev/null; then PY=$candidate; break; fi
  done
  [ -n "$PY" ] || { echo "Could not find the virtual environment's python (with Django)."; exit 1; }
}

read_dirs() {
  CACHE_DIR=$(grep -E '^CACHE_DIR=' .env 2>/dev/null | tail -n1 | cut -d= -f2- | tr -d '"'"'" || true)
  CACHE_DIR=${CACHE_DIR:-$APP_DIR/cache}
  MEDIA_DIR=$(grep -E '^MEDIA_ROOT=' .env 2>/dev/null | tail -n1 | cut -d= -f2- | tr -d '"'"'" || true)
  MEDIA_DIR=${MEDIA_DIR:-$APP_DIR/media}
}

install_start_steps() {
  # every start of the service: folders to the app's user, then migrate and collectstatic
  # ("+": as root; "-": a failure is logged and the app still starts)
  local dir="$SYSTEMD_DIR/$SERVICE.service.d"
  mkdir -p "$dir"
  cat > "$dir/mrcafe-update.conf" <<EOF
# Mr Cafe (written by deploy/update.sh): every start of $SERVICE first brings the
# database (migrate) and the static files (collectstatic) up to date, so a
# "git pull" + restart never leaves the new code on an old database (error 500).
[Service]
TimeoutStartSec=600
ExecStartPre=+/bin/sh -c 'mkdir -p "$APP_DIR/staticfiles" "$CACHE_DIR" && chown -R $APP_USER "$APP_DIR/staticfiles" "$CACHE_DIR"'
ExecStartPre=-$PY $APP_DIR/manage.py migrate --noinput
ExecStartPre=-$PY $APP_DIR/manage.py collectstatic --noinput -v 0
EOF
  systemctl daemon-reload
  echo "  each start of $SERVICE: migrate + collectstatic first  ($dir/mrcafe-update.conf)"
}

install_pull_hook() {
  # after a "git pull" that brought new code: restart the service (which migrates and collects)
  local hook="$APP_DIR/.git/hooks/post-merge"
  mkdir -p "$APP_DIR/.git/hooks"
  cat > "$hook" <<EOF
#!/bin/sh
# Mr Cafe (written by deploy/update.sh): new code was pulled, so restart $SERVICE;
# its start migrates the database and collects the static files first.
[ -n "\$MRCAFE_UPDATING" ] && exit 0   # deploy/update.sh restarts by itself
if [ "\$(id -u)" = 0 ]; then
  echo "Mr Cafe: restarting $SERVICE (database and static files are brought up to date first)..."
  if systemctl restart $SERVICE && systemctl is-active --quiet $SERVICE; then
    echo "Mr Cafe: $SERVICE is running the new code. Press Ctrl+F5 in the browser."
  else
    echo "Mr Cafe: $SERVICE did not start. See: journalctl -u $SERVICE -n 50"
  fi
else
  echo "Mr Cafe: now run   sudo systemctl restart $SERVICE   (it updates the database and static files)"
fi
EOF
  chmod +x "$hook"
  chown "$(stat -c %U "$APP_DIR/.git")" "$hook"
  echo "  git pull: restarts $SERVICE by itself  (.git/hooks/post-merge)"
}

main "$@"
exit
