# Mr Cafe — QR restaurant ordering & billing

Guests scan a QR code at their table, order from their phone, the kitchen gets
a KOT, and the cashier makes a GST bill with split payments.
Multi-restaurant (SaaS): every restaurant only ever sees its own data.

Stack: Django 5.2 LTS · PostgreSQL · HTMX · Bootstrap 5 · function-based views.

## Setup (Windows, PowerShell)

```powershell
# 1. virtual environment + packages
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt

# 2. settings: copy the example, then set SECRET_KEY=... (any long random text)
copy .env.example .env

# 3. tables + first login (development uses SQLite: db.sqlite3, nothing to install)
python manage.py migrate
python manage.py createsuperuser

# 4. demo data: 2 restaurants, a login for every role, menu, tables, a week of bills
python manage.py seed_demo --with-orders

# 5. run
python manage.py runserver
```

`seed_demo` prints every login (password `Demo@1234`), e.g. `admin@spicegarden.demo`
(tick "Sign in as restaurant admin"), `kitchen@spicegarden.demo`, `cashier@bluebay.demo`.
Run it again with `--reset` to start the demo over; your own restaurants are not touched.

On Linux / macOS use `source venv/bin/activate` and `cp`.

### Using PostgreSQL instead (server, or to test against it)

```powershell
# create the database (or pgAdmin: right-click Databases -> Create)
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -c "CREATE DATABASE resto_db;"
```

Then in `.env` set `USE_SQLITE=False` and fill in `DB_PASSWORD` (and the other
`DB_*` values if they differ), and run `python manage.py migrate` again.
The two databases are separate: data in `db.sqlite3` does not move across.

## Your own first restaurant (without the demo)

1. `createsuperuser` asks for an email: give a real one, it becomes your login.
2. Open http://127.0.0.1:8000/admin/ and log in with the superuser.
3. **Restaurants → Add**: name (slug fills itself), GSTIN, GST %. The
   **Membership** box starts with one monthly period from today and 5 logins.
   At the bottom, under **Staff**, add one row: pick a login from the **Login (user)**
   list, or leave it empty and type a **new email + password** to create the restaurant
   admin's login right there. Type a name and choose role **Admin**. Save.
4. Open http://127.0.0.1:8000/login/, enter the **email** and password and
   **tick "Sign in as restaurant admin"**. You land on the dashboard.
5. **Staff** (left menu) → **Add staff** creates logins (email + password) for
   managers, cashiers, kitchen and waiters. They log in *without* the tick.

## Who uses which panel

| Panel | Who | For |
|---|---|---|
| `/` website | everyone | The landing page. Always shown, even when logged in; staff then get an "Open <restaurant>" button. |
| `/r/<restaurant>/` public menu | everyone | View-only menu to share (WhatsApp, Instagram, Google Maps). No ordering. |
| `/m/<qr_token>/` table menu | guests at a table | Ordering. Only the table's secret QR link can order. |
| `/login/` → staff panel | restaurant admin and staff | **Everything for running the restaurant**: menu, tables, staff, **Restaurant** details (name, address, GSTIN, GST %, logo), floor, kitchen, bills, reports. |
| `/admin/` Django admin | **the developer / platform owner only** | Creating restaurants and setting memberships (plan, dates, logins allowed). |

The app never sends anyone to `/admin/`. A developer superuser who is not staff of a
restaurant sees a short "This is the developer login" page instead of restaurant screens.

## Logins and membership

* **The email is the login ID** (`core/auth.py`). Each staff member has their
  own email and password.
* **"Sign in as restaurant admin"**: ticked only by the Admin role, left empty
  by everyone else. A wrong choice is refused with a clear message.
* **Membership** (Django admin → Restaurants, *Membership* box): plan Monthly
  or Yearly, start and end date. The **"Renew membership"** action adds one
  period. A running membership is extended from its end date, so no paid day is
  lost; an ended one restarts from today.
  After the end date, staff cannot log in, anyone already logged in sees the
  "Membership ended" page, and the QR menus stop taking orders. No data is lost:
  renewing opens everything again.
* **Logins allowed (`max_users`)**: how many staff logins may be *active*, the
  admin included (default 5; editable right in the admin list). The Staff page
  shows "3 / 5 logins". Adding an active login or switching one back on is
  refused once the limit is full. Inactive logins do not count.

## Public website

http://127.0.0.1:8000/ is a one-page website for restaurant owners:
features, how it works, plans, FAQ and a **"Book a free demo"** form. Requests
land in Django admin → **Website → Demo requests**. Contact phone / email for
the page are set in `.env` (`CONTACT_PHONE`, `CONTACT_EMAIL`).

## Testing the QR codes with a phone

The QR code holds the full menu address, so the phone must be able to reach
your PC. On the same Wi-Fi:

1. Find your PC's IP (`ipconfig` → IPv4 Address, e.g. `192.168.1.10`).
2. In `.env`: `ALLOWED_HOSTS=127.0.0.1,localhost,192.168.1.10` and
   `SITE_URL=http://192.168.1.10:8000`
3. Run `python manage.py runserver 0.0.0.0:8000` (allow it through the
   Windows firewall when asked).

Each table's QR uses a random secret (`qr_token`), never the table id.

## Customer ordering (no login)

* `/m/<qr_token>/`: menu. **Add / − 2 +** buttons update the cart without a
  reload; the cart lives in the session (one cart per table).
* `/m/<qr_token>/cart/`: name (required), mobile (optional), note,
  **Place order**. This creates the table's Order (or reuses its open one, for a
  2nd / 3rd round) plus a new KOT, with each dish's name and price copied in.
* `/track/<public_token>/`: "Your order is placed", order number and the live
  status of every round, refreshing every 10 seconds.
* `/m/<qr_token>/track/`: find an order of the last 24 hours by its number.
* Once the bill is made (order BILLED), new dine-in rounds are paused until it is paid
  (a take-away parcel can still be ordered).

## Portions (Qtr / Half / Full)

* In a dish's side panel (Menu items → Edit), fill the **Portions** rows: a name and a price
  each. **Fill Qtr · Half · Full** types the usual names; any names work (Small / Large, 250 ml …).
  Leave them empty for a single-price dish. The dish's own price becomes its smallest portion's.
* Guests and waiters pick the size: the menu card shows the sizes side by side, each with its
  own Add. KOT and bill lines read "Butter Chicken (Half)" at the Half price, so the item-wise
  report shows sales per size. Old orders keep their names and prices if portions change later.

## The menu board (QR menu and public menu)

Both menus share one design, made for phones and tablets: a hero with the restaurant's name,
a sticky bar with category chips, search and Veg / Non-veg, and each category as a row of
dish cards you **slide left and right**, with **See all** to open it as a grid. Searching or
filtering shows every match as a grid. Shared parts: `orders/_menu_board.html`,
`orders/_dish_card.html`, `static/js/menu_board.js`.

## Dine in, Take away, Delivery

* An order is **Dine in** (at a table, from its QR), **Take away** or **Delivery**. Name, mobile
  and address are optional for dine in and take away, and needed for delivery.
* Each restaurant has one default **Takeaway table**, the counter (made automatically, shown on
  Tables & QR with its own QR). Take-away and delivery orders go on it, **many at once**, each
  with its own order number, KOT and bill. A dine-in table still holds one order at a time.
* The **public menu** (`/r/<slug>/`) orders for the counter: Take away, or Delivery when the
  restaurant takes deliveries. Dine-in needs the table's own QR, so nobody orders for a table
  they are not at. Staff use **Floor → New takeaway / New delivery** (waiters, cashiers, admin, manager).
* Floor shows a **Takeaway** tile (open parcels, a bell when one is ready) that opens the list
  of open parcels. The kitchen board and KOT slip say **Parcel / TAKE AWAY**, and the bill says
  TAKE AWAY with the mobile number.
* Switching the Takeaway table off (Tables & QR) turns take-away and delivery off.
* **Separate bills at one table:** people at a table share one order (one bill) by default.
  Someone who wants to pay separately picks **My own order** in the cart (or the waiter presses
  **Separate bill** on the table page). The table then holds two orders, each with its own KOTs
  and bill; the floor tile says "2 bills" and the table page has a tab per order.

## Home delivery and riders

Anyone can open the public menu, so a delivery asked for there **waits as "To confirm"**: the
order is PENDING and its KOT HELD (out of the kitchen) until staff call the customer and press
**Confirm**, or **Reject** a fake one. A delivery staff take on a call goes straight to the kitchen.

1. **Deliveries** (`/deliveries/`): columns *To confirm → In the kitchen → Ready for a rider →
   Out for delivery*, then *Delivered today* and **Cash with riders today**. Choose a rider on
   each card.
2. **Make the bill before the rider leaves**, so the amount to collect is known. The bill adds the
   restaurant's **delivery charge** (free from the "free delivery from" amount; both in
   Restaurant settings), taxed with the food.
3. The **Rider** login (`/rider/`, made for a phone) shows only that rider's deliveries: address,
   **Call**, **Map**, items, **Collect ₹…**, then **Picked up** and **Delivered** with Cash or UPI.
   That payment settles the bill and closes the order.
4. The customer's status page shows Placed → Confirmed → Cooking → On the way → Delivered.

The steps are in `orders/delivery.py`, the screens in `orders/delivery_views.py`.

## Table bookings

* Bookings are mostly taken by staff (**New booking**, below). The public menu has no booking
  button; guests can still be sent the booking page `/r/<slug>/book/` (day up to 30 days ahead,
  time, guests, name and mobile). Such a request is **Requested** until staff call and confirm.
  One mobile number can ask once per day.
* **Bookings** (`/tables/bookings/`, Admin / Manager / Cashier / Waiter): requests to confirm,
  then a day's list with **Confirm, Give table, Seated, No-show, Cancel** and **New booking** for
  phone calls. A table cannot be booked twice within 2 hours.
* The floor shows **Booked 8:30 PM** on a free table booked for today.
* Bookings and delivery can each be switched off in Restaurant settings.

## Service screens (staff)

| Screen | Who | What |
|---|---|---|
| `/floor/` | Admin, Manager, Cashier, Waiter | A tile per table: **green** free, **orange** occupied, **blue** bill printed; a bell when food is ready. Refreshes every 10 s. |
| `/floor/table/<id>/` | same | The running order, every round (KOT) with status buttons, **New KOT**, **Cancel order** (Admin / Manager, with a reason). |
| `/waiter/order/<table_id>/` | Waiter, Admin, Manager | The menu with + / − on the staff phone, then **Send to kitchen**. |
| `/kitchen/` | Kitchen, Admin, Manager | Columns **New / Preparing / Ready**, refreshing every 5 s. Waiting 15 min or more shows red. Buttons: Start cooking, Mark ready, Print. **Stock** switches dishes out of stock. Optional beep for new KOTs. |
| `/waiter/ready/` | Waiter | Food that is ready, oldest first, with **Mark served**. |
| `/kot/<id>/print/` | Kitchen, Admin, Manager | 80 mm KOT slip (no prices); the print dialog opens by itself. |

Who may move a KOT where is one table in `orders/services.py` (`KOT_MOVES`):
New → Preparing → Ready (kitchen), Ready → Served (waiter), cancel (admin / manager).
If two people press at once, the second just gets a fresh screen saying so.

## Billing (Cashier, Admin, Manager)

1. Table page → **Generate bill**: every round of the order on one bill (the same dish at the
   same rate is one line), an optional discount in ₹ or %, then **Confirm**. The order becomes
   BILLED (blue on the floor) and guests cannot add rounds.
2. Bill page → **Take payment**: add one payment row per mode, e.g. Cash ₹500 + UPI ₹740.
   For cash, "Cash given" shows the change to return (not stored). A wrong row can be removed
   until the bill is fully paid.
3. Once the payments cover the grand total, the bill is **PAID**, the order **CLOSED** and the
   table free.

* **Reopen for more orders** (unpaid bill, no payments yet): the order takes new rounds again.
  The next "Generate bill" redoes the **same** bill number.
* **Cancel bill** (Admin / Manager, with a reason, only without payments): the bill and order are
  cancelled. The number stays in the register.
* **Print**: an 80 mm bill with GSTIN, CGST / SGST, round off and payment modes.
* `/billing/` is the bill register (date range, status, search).

Arithmetic (`billing/calc.py`, all `Decimal`): subtotal − discount = taxable; CGST = SGST =
taxable × GST% ÷ 2 (to the paisa); grand total rounded to the rupee, and the difference shown as round off.

## Reports and dashboard (Admin, Manager)

`/dashboard/` shows today's sales, open tables, pending KOTs, money collected by payment
mode, the last 7 days, top dishes and the latest bills.

`/reports/` has 8 reports, each with From / To dates (today by default, plus quick ranges),
a table on screen, Print and **Export CSV** (opens in Excel):
daily sales summary · payment modes · item-wise · category-wise · table-wise · waiter-wise ·
bill register · cancelled KOTs & bills. They are built with the Django ORM only (`reports/reports.py`).
Cancelled bills are listed but never added into sales.

## Tests

```powershell
python manage.py test
```

90 tests: data isolation between restaurants (404s), two orders on one table = one order with
two KOTs, bill totals (discount, CGST / SGST, round off), multi-mode payment closing the order,
KOT moves by role, email login + membership + login limit, reports and CSV, the landing page
never redirecting, the public menu, restaurant settings and the slider, portions, take away,
delivery (confirm first, charge, rider pick-up and collection), table bookings and separate bills.

## Deployment

See [deploy/DEPLOY.md](deploy/DEPLOY.md) for Ubuntu + PostgreSQL + Gunicorn + Nginx + HTTPS
step by step, with the `DEBUG=False` checklist, backups and updates. The service and site files
are in `deploy/`.

## Roles

| Role | Sees |
|---|---|
| Admin | everything, including Staff |
| Manager | dashboard, menu, tables, floor, kitchen, bills, reports |
| Cashier | floor, deliveries, bookings, bills; counter orders (take away, delivery) |
| Kitchen | kitchen board |
| Waiter | floor, deliveries, bookings, ready-to-serve list |
| Rider | own deliveries: pick up, deliver, collect cash / UPI |

The sidebar links and their roles live in `core/navigation.py`.
Views are protected with `@role_required("ADMIN", "MANAGER")` from
`core/decorators.py`. Links to pages not built yet show as *Soon*.

## Project layout

```
core/       Restaurant (+ membership, delivery and booking settings), Staff (roles incl. Rider),
            email login, dashboard, staff, restaurant settings, role_required, utils
menu/       Category, MenuItem, MenuItemPortion (Qtr / Half / Full)
tables/     DiningTable + QR codes; Booking (booking_views.py)
orders/     Order, KOT, KOTItem
              services.py        the order rules: which order, place_kot, KOT moves, cancel
              delivery.py        the delivery steps: confirm, rider, pick up, deliver
              cart.py            the guest's / waiter's cart, kept in the session
              guest_views.py     public menu, QR menu, cart, track (no login)
              staff_views.py     floor, waiter screen, kitchen, KOT print
              delivery_views.py  deliveries board, rider's screen
billing/    Bill, BillItem, Payment; calc.py (totals), services.py (bill + payment steps)
reports/    reports.py (the 8 reports), views only, no models
web/        public one-page website + demo requests
deploy/     resto.service (Gunicorn), nginx-resto.conf, env.production.example, DEPLOY.md
docs/       ARCHITECTURE.md: how the pieces fit, for a developer new to the code
templates/  base_staff.html, base_customer.html, partials/, one folder per app
static/     css/app.css (all styles), js/app.js (every page), menu.js (guest menu),
            waiter.js, live.js (kitchen beep), billing.js
```

New to the code? Start with [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## How the HTMX screens work

* Add / edit forms load into the right-hand side panel (`#panel`).
* On a successful save the view returns `core.utils.htmx_saved("message")`:
  status 204 with an `HX-Trigger` header. `static/js/app.js` then closes the
  panel, shows the message, and the list reloads itself (`rowsChanged`).
* On errors the view returns the same form partial with the messages.
