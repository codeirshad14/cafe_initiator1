"""
Who may do what: every role and its screens in one place. Views use these
lists in @role_required(...); the left menu (core/navigation.py) and the
"Roles" table on Cafe profile > Staff read them too.

    Admin            everything, every location (the owner's login)
    Manager          everything, every location
    Restaurant mgr   everything at their own location(s): service, bills,
                     cancelling, menu, tables, reports (not the company's
                     profile, staff logins or offers)
    All-rounder      every service screen at their location(s): orders,
                     kitchen, bills, deliveries, the waiter's and the
                     rider's screens (not setup, reports or cancelling)
    Cashier (bills)  bills and payments, the Floor (table, takeaway and
                     delivery orders, like every Floor role), deliveries, bookings,
                     the kitchen board (sees and moves KOTs, prints them),
                     menu items, categories, tables & QR
    Waiter           takes orders, sees and moves KOTs (cook, ready, served),
                     sees the bills and their amounts (and prints them) but
                     makes no bill and takes no payment
    Kitchen          the KOT board and the dishes' stock
    Rider            only their own deliveries: picked up, delivered and paid;
                     never takes orders or makes KOTs
"""

ADMIN = "ADMIN"
MANAGER = "MANAGER"
RM = "RM"
ALL = "ALL"
CASHIER = "CASHIER"
KITCHEN = "KITCHEN"
WAITER = "WAITER"
RIDER = "RIDER"

COMPANY = (ADMIN, MANAGER)                     # the company's profile, staff logins, offers, printers
OUTLET_HEADS = COMPANY + (RM,)                 # run a location: setup, cancelling, reports, dashboard
SERVICE = OUTLET_HEADS + (ALL,)                # every service screen

DASHBOARD = OUTLET_HEADS
REPORTS = OUTLET_HEADS
MENU_SETUP = OUTLET_HEADS + (CASHIER,)         # menu items, categories, tables & QR codes
CANCEL = OUTLET_HEADS                          # cancel orders, KOTs and bills

FLOOR = SERVICE + (CASHIER, WAITER)
TABLE_ORDERS = FLOOR                           # whoever sees the Floor takes orders on it, the same way
COUNTER_ORDERS = FLOOR                         # New takeaway / New delivery
KITCHEN_BOARD = SERVICE + (KITCHEN, WAITER, CASHIER)  # the waiter and the cashier check the KOTs too
COOK = SERVICE + (KITCHEN, WAITER, CASHIER)    # Start cooking / Mark ready
SERVE = SERVICE + (WAITER,)                    # Mark served
READY_LIST = (WAITER, ALL)                     # "Ready to serve" for the waiter
STOCK = SERVICE + (KITCHEN, CASHIER)           # dishes running out today
PRINT_KOT = SERVICE + (KITCHEN, WAITER, CASHIER)
BILLING = SERVICE + (CASHIER,)
BILL_VIEW = BILLING + (WAITER,)                # see the bills and their amounts; the waiter only looks
DELIVERIES = SERVICE + (CASHIER, WAITER)
RIDING = (RIDER, ALL)                          # the rider's own deliveries
BOOKINGS = SERVICE + (CASHIER, WAITER)

# the Staff tab's "who can do what" table: (what, roles)
MATRIX = [
    ("Dashboard & reports", DASHBOARD),
    ("Menu, categories, tables & QR", MENU_SETUP),
    ("Cafe profile, staff logins, offers, printers", COMPANY),
    ("Floor (see tables)", FLOOR),
    ("Take table orders", TABLE_ORDERS),
    ("Takeaway & delivery orders", COUNTER_ORDERS),
    ("Kitchen board, start cooking, mark ready", COOK),
    ("Mark served", SERVE),
    ("See bills & amounts, print them", BILL_VIEW),
    ("Make bills, take payments", BILLING),
    ("Cancel orders, KOTs & bills", CANCEL),
    ("Deliveries board", DELIVERIES),
    ("Rider screen (own deliveries)", RIDING),
    ("Table bookings", BOOKINGS),
]
ROLE_ORDER = (ADMIN, MANAGER, RM, ALL, CASHIER, WAITER, KITCHEN, RIDER)
