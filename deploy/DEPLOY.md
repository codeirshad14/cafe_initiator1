# Deploying Mr Cafe (Ubuntu + PostgreSQL + Gunicorn + Nginx)

These steps assume a fresh Ubuntu 22.04 / 24.04 server, a domain pointing to it
(`order.example.com` below, so replace it everywhere), and the project in
`/srv/resto`, running as the user `resto`.

```
Browser ──HTTPS──> Nginx ──unix socket──> Gunicorn (resto.wsgi) ──> PostgreSQL
                    └── /static/ and /media/ served straight from disk
```

## 1. Packages and the app user

```bash
sudo apt update
sudo apt install -y python3-venv python3-dev postgresql nginx certbot python3-certbot-nginx git
sudo adduser --system --group --home /srv/resto resto
sudo usermod -aG www-data resto
```

## 2. PostgreSQL database

```bash
sudo -u postgres psql <<'SQL'
CREATE USER resto WITH PASSWORD 'choose-a-strong-password';
CREATE DATABASE resto_db OWNER resto;
ALTER ROLE resto SET client_encoding TO 'utf8';
ALTER ROLE resto SET timezone TO 'Asia/Kolkata';
SQL
```

## 3. The code, virtual environment and settings

```bash
sudo -u resto -H bash
cd /srv/resto
git clone <your-repository-url> .        # or copy the project folder here
python3 -m venv venv
venv/bin/pip install -r requirements.txt
venv/bin/pip freeze > requirements.lock   # the exact versions this server got (see below)
cp deploy/env.production.example .env
nano .env                                # SECRET_KEY, DB_PASSWORD, your domain
chmod 600 .env
```

## 4. Database tables, static files, first login

```bash
venv/bin/python manage.py migrate
venv/bin/python manage.py collectstatic --noinput   # -> /srv/resto/staticfiles/
venv/bin/python manage.py createsuperuser           # give a real email: it is the login
venv/bin/python manage.py check --deploy            # read every warning (see the checklist)
mkdir -p media cache                                # photos; the shared login cache
exit
```

`requirements.txt` names the packages without versions, so a new server gets the newest
of each (checked: Django 6.1, reportlab 5.1, gunicorn 26 pass every test). A later
release can change something, so the server keeps the versions it got in
`requirements.lock`: to put the same versions on another server, or back after a bad
update, use `venv/bin/pip install -r requirements.lock`.

Only for a demo server: `venv/bin/python manage.py seed_demo --with-orders`.
Never on the real one, because it makes logins with a known password.

## 5. Gunicorn as a service

```bash
sudo cp /srv/resto/deploy/resto.service /etc/systemd/system/resto.service
sudo systemctl daemon-reload
sudo systemctl enable --now resto
sudo systemctl status resto          # should say "active (running)"
```

## 6. Nginx and HTTPS

```bash
sudo cp /srv/resto/deploy/nginx-resto.conf /etc/nginx/sites-available/resto
sudo nano /etc/nginx/sites-available/resto      # your domain
sudo ln -s /etc/nginx/sites-available/resto /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d order.example.com       # HTTPS + redirect, renews itself
```

Open `https://order.example.com/`: you should see the website. `/login/` is
for staff, and `/admin/` is where you (the developer) set up restaurants and memberships.

## The installable app (phone and desktop)

Staff can install Mr Cafe as an app: **Install app** in the top bar (on phones: the
account menu), **Get the app** on the website, or the button on the login page.
It opens in its own window with the Mr Cafe icon, on Android, iPhone, Windows, Mac and Linux.

- It needs **HTTPS** (step 6). On plain `http://` the button simply does not show.
- Nothing to set in Nginx: `/manifest.webmanifest`, `/sw.js`, `/offline/` and the app's
  icons, script and styles (`/app/...`) come from Django, so the Install button works
  right after `git pull` and a restart, even before `collectstatic`.
- The button always shows in the browser. Where the browser has no install prompt (or
  the app is already installed), it opens the steps for that browser and how to
  install it fresh over the old one.
- After each update `collectstatic` (step 4) is enough: open apps pick up the new
  version on their next start. Pages and orders are never stored on the device,
  only CSS, JS and icons.
- Icons: `static/img/app/`. After changing the mark or the brand red, run
  `python manage.py make_app_icons`, then `collectstatic`.

## A new restaurant

1. `/admin/` > Restaurants > Add: the name, its web address (slug), the restaurant admin's
   **email and password**, and the membership. Save. That email is now its admin login.
2. The restaurant admin opens `/login/`, types that email and password and ticks
   **Sign in as restaurant admin**.
3. The first login opens **Create Update Profile** ("Step 1 of 2"): address and phone (and
   GSTIN, FSSAI, logo). Saving it goes on to **Staff**, where the admin adds the cashier,
   waiter, kitchen and rider logins (they log in without the tick).

Nothing else is set in `/admin/`. To reset a restaurant admin's password, open the
restaurant there and type a new **Admin login password**.

## When a page shows error 500 or a login will not go in

```bash
cd /srv/resto && sudo -u resto venv/bin/python manage.py check_setup
```

It checks `.env`, the database and its migrations, the static files, `media/` and the
cache, and every restaurant's admin login, and prints OK or FAIL with the fix. It
changes nothing. Then `sudo journalctl -u resto -n 80 --no-pager` shows the error itself.

## `DEBUG=False` checklist

- [ ] `DEBUG=False` in `.env`. With `True`, error pages show your settings to anyone.
- [ ] `SECRET_KEY` is new, long and random, not the one from development.
- [ ] `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` name your domain (with `https://` for CSRF).
- [ ] `SITE_URL=https://your-domain`, then print the **QR sheet again**: old QR codes point to your PC.
- [ ] `USE_SQLITE=False` and the PostgreSQL password is set.
- [ ] `python manage.py check --deploy` shows nothing you have not chosen to accept.
      (`SECURE_HSTS_SECONDS` is 0 until HTTPS works everywhere; then set `31536000`.)
      Three warnings stay, on purpose: W008 (Nginx makes the HTTPS redirect, not Django),
      W005 and W021 (HSTS for subdomains and the browsers' preload list: only if every
      subdomain of yours is HTTPS for good).
- [ ] `collectstatic` was run after the last update, and Nginx serves `/static/` (CSS loads).
      With `DEBUG=False` the CSS and JS names carry a fingerprint (`app.7709642c.css`):
      without `collectstatic` the pages answer with error 500.
- [ ] The `cache/` folder in the project exists and the `resto` user can write it (the count
      of wrong passwords: 5 for an email, then 15 minutes' wait, shared by all Gunicorn
      workers). If it cannot, logins still work, without the count, and the log says so.
- [ ] `python manage.py check_setup` says "All good."
- [ ] `.env` is `chmod 600`, and is not in git (`.gitignore` already lists it).
- [ ] HTTPS works and `http://` redirects to `https://` (certbot does this).
- [ ] Backups run (below), and you have tried restoring one once.
- [ ] Only you have Django superuser logins. Restaurant staff never get `is_staff`.

## Backups

```bash
# every night at 02:30, keep 14 days
sudo -u resto crontab -e
30 2 * * * pg_dump resto_db | gzip > /srv/resto/backups/resto_$(date +\%F).sql.gz && find /srv/resto/backups -name '*.sql.gz' -mtime +14 -delete
```

Make the folder first with `sudo -u resto mkdir -p /srv/resto/backups`. Copy
the backups off the server too, and back up `/srv/resto/media/` (menu photos).

## Updating to a new version

One command, from the project folder, after every push:

```bash
sudo bash deploy/update.sh            # or: sudo bash deploy/update.sh cafe1
```

It finds the service, its user and its Python by itself, then: `git pull`, packages,
makes the folders the app writes (static, media, cache) belong to the app's user,
`migrate`, `collectstatic`, restart, and `check_setup`. It ends with "Updated" or with
the FAIL lines and their fixes. Never skip it for a plain `git pull` + restart: a new
file without `collectstatic`, or a migration without `migrate`, is what broke pages before.

## When something is wrong

| Symptom | Look at |
|---|---|
| 502 Bad Gateway | `sudo systemctl status resto` and `sudo journalctl -u resto -n 50` |
| Page has no styles | `collectstatic` was not run, or the `/static/` alias path is wrong |
| "Bad Request (400)" | your domain is missing from `ALLOWED_HOSTS` |
| "CSRF verification failed" | `CSRF_TRUSTED_ORIGINS` needs `https://your-domain` |
| QR opens the wrong address | `SITE_URL`, then print the QR sheet again |
| Photo upload fails | dish photos are up to 5 MB; `client_max_body_size 8M` in Nginx; `media/` must be writable by `resto` |
| Every page is error 500 after an update | run `sudo bash deploy/update.sh` (it does `migrate` and `collectstatic`), then read its check |
| "Too many wrong passwords" | wait 15 minutes, or empty the project's `cache/` folder to let everyone try again |
| A login will not go in | `python manage.py check_setup` (an email used by two logins, no password, membership ended …) |
