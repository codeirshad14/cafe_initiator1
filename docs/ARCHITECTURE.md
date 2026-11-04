# How Mr Cafe is put together

A guide for a developer new to this code. It explains where things live and how
an order travels through the system. The [README](../README.md) covers setup and
how each screen is used.

## The idea in one paragraph

Mr Cafe is one Django project serving many restaurants (SaaS). Every business
row (dish, table, order, bill …) points to a `Restaurant`, and every staff query
is filtered by the logged-in user's restaurant. Guests never log in: a table's
QR code carries a secret token for that table, and the public menu is found by
the restaurant's web address (`/r/<slug>/`). Staff log in with their email and
see only what their role allows.

## Apps and what they own

| App | Owns | Key files |
|---|---|---|
| `core` | `Restaurant` (membership, delivery and booking settings), `Staff` (role) | `decorators.py` (`role_required`), `utils.py` (`next_number`, `htmx_saved`), `navigation.py` (sidebar) |
| `menu` | `Category`, `MenuItem`, `MenuItemPortion` | `forms.py` (dish + sizes) |
| `tables` | `DiningTable` (+ the counter table), `Booking` | `qr.py`, `booking_views.py` |
| `orders` | `Order`, `KOT`, `KOTItem` | `services.py`, `delivery.py`, `cart.py`, three view files |
| `billing` | `Bill`, `BillItem`, `Payment` | `calc.py` (totals), `services.py` (bill and payment steps) |
| `reports` | no models | `reports.py` (ORM queries) |
| `web` | `DemoRequest` | the public website at `/` |

Rule of thumb: **views stay thin**. A view reads the request, calls a function in
`services.py` (or `delivery.py`, `billing/services.py`) and renders a template.
The rules (what may happen, in what order) live in those service files, so they
are written once and tested directly.

## The three ways to order

```
1. Dine in      guest scans the table's QR  ->  /m/<qr_token>/  (the table is known from the token)
                or a waiter uses /waiter/order/<table>/
2. Take away    guest on the public menu /r/<slug>/ or the counter QR,
                or the cashier: Floor -> New takeaway
3. Delivery     guest on the public menu (waits "To confirm"),
                or the cashier on a phone call: Floor -> New delivery
```

Take-away and delivery orders sit on one special table per restaurant, the
**counter** (`DiningTable.is_takeaway`, made by `tables.models.takeaway_table`).
It holds many orders at once.

## Life of an order

```
cart (session)  --place_kot()-->  Order (OPEN) + KOT (NEW)
                                     |
kitchen:   KOT  NEW -> PREPARING -> READY          (move_kot, roles in KOT_MOVES)
waiter:    KOT  READY -> SERVED
cashier:   make_bill()     Order OPEN   -> BILLED   (billing/services.py)
           add_payment()   paid in full -> Order CLOSED
or:        cancel_order()  -> CANCELLED (with a reason)
```

* **A round** = one KOT. More rounds can be added to an OPEN order.
* **Prices are copied** onto each KOT line and bill line (`item_name`, `rate`),
  so changing the menu later never changes an old order or bill.
* **Numbers** (order, KOT, bill, booking) count from 1 per restaurant:
  `core.utils.next_number`, always inside `transaction.atomic()` with the
  restaurant row locked.

### Which order does a dine-in round go on? (separate bills)

Usually a table has one order and everyone shares one bill. If someone at the
same table wants to pay separately, they pick **"My own order"** and get an
order of their own on that table. `services.order_to_join()` decides:

* the guest chose an order → that order (if it is still OPEN);
* the guest chose "My own order" → a new order;
* no choice → this phone's own order, else the table's oldest open order, else a new one.

The floor tile adds a table's orders up ("2 bills"), and the table page shows one
tab per order. Each order is billed and paid on its own.

### Delivery

A delivery from the public menu is **PENDING** and its KOT **HELD**. The kitchen
only shows NEW / PREPARING / READY, so a held KOT stays out of it. Staff call the
customer, then `delivery.confirm_delivery()` makes it OPEN / NEW. After that:
choose a rider → make the bill → `pick_up()` → `deliver()`, which records the
rider's cash or UPI payment and so closes the order. A rider is simply a
`Staff` member with the role `RIDER`.

### Table booking

`tables.Booking`: Requested (from the public menu) → Confirmed (staff called) →
Seated, or Cancelled / No-show. A confirmed booking with a table shows as
"Booked 8:30 PM" on the floor that day.

## Requests, templates and HTMX

* **Full page:** `templates/<app>/<page>.html`, extending `base_staff.html` or
  `base_customer.html`.
* **Partial (starts with `_`):** a piece of a page that HTMX swaps in, e.g. the
  kitchen board refreshing every 5 seconds (`hx-trigger="every 5s"`). A view
  sends the partial when `is_htmx(request)` is true, and the full page otherwise.
* **Side panel forms:** add / edit forms load into `#panel`. On success the view
  returns `htmx_saved("message")`: an empty 204 answer whose `HX-Trigger` header
  tells `static/js/app.js` to close the panel, show the message and reload the list.
* **Small behaviours are switched on by HTML attributes** handled in `app.js`:
  `data-show-for="TAKEAWAY DELIVERY"` (show only for those order types),
  `data-submit-once` (no double orders), `data-copy`, `data-fill-portions`.

## Security in short

* Every staff view has `@role_required(...)`, and every lookup uses
  `get_object_or_404(..., restaurant=<the user's restaurant>)`. Another
  restaurant's record answers 404, never someone else's data.
* QR links use a random UUID per table, never the table id.
* The public menu can only order take-away or delivery; deliveries wait for a
  phone call before the kitchen sees them.

## Where to change things

| I want to … | Look at |
|---|---|
| change who may move a KOT | `orders/services.py` → `KOT_MOVES` |
| change bill arithmetic (GST, round off, delivery charge) | `billing/calc.py` |
| add a sidebar link or change who sees it | `core/navigation.py` |
| change how separate bills are chosen | `orders/services.py` → `order_to_join` |
| change a delivery step | `orders/delivery.py` |
| add a report | `reports/reports.py` + `reports/views.py` |
| change colours or spacing | `static/css/app.css` (tokens at the top) |

## Tests

`python manage.py test`: every app has a `tests.py`. Test helpers (make a
restaurant, menu, table, staff, a logged-in client) are in `core/testing.py`.
