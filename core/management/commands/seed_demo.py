"""
python manage.py seed_demo                 two demo restaurants with staff, menu and tables
python manage.py seed_demo --with-orders   ... plus a week of paid bills and live orders
python manage.py seed_demo --reset         delete the demo restaurants first, then make them again

Two restaurants prove the data isolation: log in to one and you never see the other.
Every login's password is printed at the end.
"""

import random
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from billing.models import Bill, BillItem, Payment
from billing.services import add_payment, make_bill
from core.models import Restaurant, Staff, membership_end_for
from menu.models import Category, MenuItem, MenuItemPortion
from orders.delivery import assign_rider, pick_up
from orders.models import KOT, KOTItem, Order
from orders.services import move_kot, place_kot
from tables.models import Booking, DiningTable, takeaway_table

PASSWORD = "Demo@1234"
ROLES = ["ADMIN", "MANAGER", "RM", "ALL", "CASHIER", "KITCHEN", "WAITER", "RIDER"]  # one login per role (8 = max_users)
NAMES = {"RM": "Outlet", "ALL": "Allrounder"}  # the demo person's first name (rm@ / all@ log in)

# dishes sold in sizes (Qtr / Half / Full ...), each with its own price
PORTIONS = {
    "Tandoori Chicken": [("Qtr", "199"), ("Half", "329"), ("Full", "599")],
    "Butter Chicken": [("Half", "229"), ("Full", "349")],
    "Paneer Butter Masala": [("Half", "179"), ("Full", "269")],
    "Chicken Dum Biryani": [("Half", "219"), ("Full", "329")],
    "Cold Coffee": [("Regular", "149"), ("Large", "199")],
    "Mango Shake": [("Regular", "159"), ("Large", "209")],
}

RESTAURANTS = [
    {
        "name": "Spice Garden", "slug": "demo-spice-garden", "domain": "spicegarden.demo",
        "address": "12, MG Road, Camp\nPune, Maharashtra 411001", "phone": "020 2612 3456",
        "gstin": "27AAACS1234F1Z5", "fssai_no": "11520034000123",
        "tables": [("T1", "AC Hall", 4), ("T2", "AC Hall", 4), ("T3", "AC Hall", 2), ("T4", "AC Hall", 6),
                   ("T5", "AC Hall", 4), ("T6", "AC Hall", 8), ("R1", "Rooftop", 4), ("R2", "Rooftop", 4)],
        "menu": {
            "Starters": [
                ("Paneer Tikka", "VEG", "249", "Cottage cheese, charred in the tandoor"),
                ("Hara Bhara Kabab", "VEG", "199", "Spinach and green pea patties"),
                ("Chicken 65", "NON_VEG", "289", "Crisp, curry-leaf tempered"),
                ("Tandoori Chicken", "NON_VEG", "199", "Marinated overnight, smoky"),
            ],
            "Main Course": [
                ("Dal Makhani", "VEG", "229", "Black lentils, slow cooked with butter"),
                ("Paneer Butter Masala", "VEG", "269", "Rich tomato and cashew gravy"),
                ("Butter Chicken", "NON_VEG", "349", "The classic, mildly spiced"),
                ("Egg Curry", "NON_VEG", "199", "Two boiled eggs in onion-tomato masala"),
            ],
            "Breads": [
                ("Tandoori Roti", "VEG", "35", ""),
                ("Butter Naan", "VEG", "60", ""),
                ("Garlic Naan", "VEG", "75", ""),
                ("Laccha Paratha", "VEG", "65", "Flaky, layered"),
            ],
            "Rice & Biryani": [
                ("Jeera Rice", "VEG", "149", ""),
                ("Veg Biryani", "VEG", "249", "With raita"),
                ("Chicken Dum Biryani", "NON_VEG", "329", "Hyderabadi style, with raita and salan"),
                ("Egg Biryani", "NON_VEG", "269", ""),
            ],
            "Desserts & Drinks": [
                ("Gulab Jamun (2 pcs)", "VEG", "99", "Served warm"),
                ("Kulfi Falooda", "VEG", "149", ""),
                ("Sweet Lassi", "VEG", "89", ""),
                ("Masala Chaas", "VEG", "59", ""),
            ],
        },
    },
    {
        "name": "Blue Bay Cafe", "slug": "demo-blue-bay", "domain": "bluebay.demo",
        "address": "Beach Road, Calangute\nGoa 403516", "phone": "0832 227 8899",
        "gstin": "30AAACB5678K1Z2", "fssai_no": "10019031000456",
        "tables": [("C1", "Indoor", 2), ("C2", "Indoor", 2), ("C3", "Indoor", 4), ("C4", "Indoor", 4),
                   ("D1", "Deck", 4), ("D2", "Deck", 4), ("D3", "Deck", 6), ("D4", "Deck", 6)],
        "menu": {
            "Breakfast": [
                ("Masala Omelette", "NON_VEG", "149", "With toast"),
                ("Aloo Paratha", "VEG", "129", "With curd and pickle"),
                ("Pancake Stack", "NON_VEG", "179", "Maple syrup, butter"),
                ("Poha", "VEG", "89", ""),
            ],
            "Sandwiches": [
                ("Bombay Veg Grill", "VEG", "159", ""),
                ("Chicken Tikka Sandwich", "NON_VEG", "199", ""),
                ("Egg Mayo Sandwich", "NON_VEG", "149", ""),
                ("Paneer Bhurji Wrap", "VEG", "179", ""),
            ],
            "Pasta & Mains": [
                ("Penne Arrabbiata", "VEG", "249", ""),
                ("Prawn Xacuti", "NON_VEG", "399", "Goan curry with rice"),
                ("Fish Thali", "NON_VEG", "349", "Catch of the day"),
                ("Veg Thali", "VEG", "249", ""),
            ],
            "Coffee & Shakes": [
                ("Filter Coffee", "VEG", "69", ""),
                ("Cold Coffee", "VEG", "149", ""),
                ("Kokum Sherbet", "VEG", "79", ""),
                ("Mango Shake", "VEG", "159", ""),
            ],
            "Desserts": [
                ("Bebinca", "NON_VEG", "149", "Goan layered pudding"),
                ("Brownie with Ice Cream", "NON_VEG", "189", ""),
                ("Serradura", "VEG", "159", ""),
                ("Fruit Salad", "VEG", "119", ""),
            ],
        },
    },
]


class Command(BaseCommand):
    help = "Create two demo restaurants with staff for every role, menu and tables (optionally a week of orders)."

    def add_arguments(self, parser):
        parser.add_argument("--with-orders", action="store_true", help="also make a week of bills and some live orders")
        parser.add_argument("--reset", action="store_true", help="delete the demo restaurants first")

    def handle(self, *args, **options):
        random.seed(42)  # the same demo every time
        slugs = [spec["slug"] for spec in RESTAURANTS]

        if options["reset"]:
            for restaurant in Restaurant.objects.filter(slug__in=slugs):
                self.delete_restaurant(restaurant)
                self.stdout.write(f"Deleted {restaurant.name}")
        elif Restaurant.objects.filter(slug__in=slugs).exists():
            self.stdout.write(self.style.WARNING("The demo restaurants are already there. Use --reset to make them again."))
            return

        logins = []
        for spec in RESTAURANTS:
            with transaction.atomic():
                restaurant, staff = self.make_restaurant(spec)
                if options["with_orders"]:
                    self.make_orders(restaurant, staff)
            logins += [(restaurant.name, role, member.user.email) for role, member in staff.items()]
            self.stdout.write(self.style.SUCCESS(f"Made {restaurant.name}"))

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING(f"Logins (password for all: {PASSWORD})"))
        for name, role, email in logins:
            tick = "  <- tick 'Sign in as restaurant admin'" if role == "ADMIN" else ""
            self.stdout.write(f"  {name:<14} {role:<8} {email}{tick}")

    # ------------------------------------------------------------ build

    def make_restaurant(self, spec):
        today = timezone.localdate()
        restaurant = Restaurant.objects.create(
            name=spec["name"], slug=spec["slug"], address=spec["address"], phone=spec["phone"],
            email=f"hello@{spec['domain']}", gstin=spec["gstin"], fssai_no=spec["fssai_no"],
            gst_percent=Decimal("5.00"), tier="ULTIMATE", plan=Restaurant.Plan.YEARLY,  # the demo shows every app
            membership_start=today, membership_end=membership_end_for(today, Restaurant.Plan.YEARLY),
            max_users=8, delivery_charge=Decimal("30.00"), free_delivery_above=Decimal("500.00"),
        )

        staff = {}
        for role in ROLES:
            email = f"{role.lower()}@{spec['domain']}"
            User.objects.filter(username=email).delete()  # an old demo login with this email
            user = User.objects.create_user(email, email=email, password=PASSWORD, first_name=role.title())
            staff[role] = Staff.objects.create(
                user=user, restaurant=restaurant, role=role,
                name=f"{NAMES.get(role, role.title())} {spec['name'].split()[0]}",
            )

        for order, (category_name, dishes) in enumerate(spec["menu"].items(), start=1):
            category = Category.objects.create(restaurant=restaurant, name=category_name, sort_order=order)
            for sort, (name, food_type, price, about) in enumerate(dishes, start=1):
                item = MenuItem.objects.create(
                    restaurant=restaurant, category=category, name=name, food_type=food_type,
                    price=Decimal(price), description=about, sort_order=sort,
                )
                for position, (size, size_price) in enumerate(PORTIONS.get(name, [])):
                    MenuItemPortion.objects.create(item=item, name=size, price=Decimal(size_price), sort_order=position)

        for name, section, seats in spec["tables"]:
            DiningTable.objects.create(restaurant=restaurant, name=name, section=section, capacity=seats)
        return restaurant, staff

    def make_orders(self, restaurant, staff):
        """A week of paid bills, then a few tables busy right now (cooking, ready, waiting for payment)."""
        items = list(MenuItem.objects.filter(restaurant=restaurant).prefetch_related("portions"))
        tables = list(DiningTable.objects.filter(restaurant=restaurant))
        guests = ["Meera", "Rahul", "Ananya", "Vikram", "Sana", "Arjun", "Priya", "Kabir", "Isha", "Rohan"]
        modes = [Payment.Mode.CASH, Payment.Mode.UPI, Payment.Mode.UPI, Payment.Mode.CREDIT_CARD,
                 Payment.Mode.DEBIT_CARD, Payment.Mode.ONLINE]
        today = timezone.localdate()

        def some_dishes():
            """2 to 5 random dishes; a dish sold in sizes is ordered in one of them."""
            lines = []
            for item in random.sample(items, random.randint(2, 5)):
                line = {"item": item, "qty": random.randint(1, 3)}
                sizes = list(item.portions.all())
                if sizes:
                    size = random.choice(sizes)
                    line.update(name=f"{item.name} ({size.name})", rate=size.price)
                lines.append(line)
            return lines

        # ---- the last 7 days, today included: paid bills
        for days_ago in range(6, -1, -1):
            day = today - timedelta(days=days_ago)
            for _ in range(random.randint(5, 9) if days_ago else 4):
                table = random.choice(tables[2:])  # keep the first two free for the live orders below
                waiter = staff["WAITER"] if random.random() < 0.5 else None
                kot = place_kot(table, some_dishes(), customer_name=random.choice(guests),
                                source=Order.Source.WAITER if waiter else Order.Source.QR, waiter=waiter)
                if random.random() < 0.4:
                    place_kot(table, some_dishes(), customer_name="", waiter=waiter, add_to=kot.order)  # a 2nd round
                for each in kot.order.kots.all():
                    for status in (KOT.Status.PREPARING, KOT.Status.READY, KOT.Status.SERVED):
                        move_kot(each, status, staff["WAITER"])
                discount = random.choice([0, 0, 0, 5, 10])
                bill = make_bill(kot.order, staff["CASHIER"], "PERCENT", discount)
                self.pay(bill, modes, staff["CASHIER"])
                self.move_to_day(kot.order, bill, day)

        # ---- live right now: one table cooking, one ready, one waiting for payment
        cooking = place_kot(tables[0], some_dishes(), customer_name="Kabir", note="less spicy")
        move_kot(cooking, KOT.Status.PREPARING, staff["KITCHEN"])
        place_kot(tables[0], some_dishes(), customer_name="Kabir", add_to=cooking.order)  # a new round, still NEW
        # someone else at Kabir's table pays separately: a second order (bill) on the same table
        place_kot(tables[0], some_dishes(), customer_name="Neha")

        ready = place_kot(tables[1], some_dishes(), customer_name="Guest", source=Order.Source.WAITER, waiter=staff["WAITER"])
        move_kot(ready, KOT.Status.PREPARING, staff["KITCHEN"])
        move_kot(ready, KOT.Status.READY, staff["KITCHEN"])

        unpaid_table = next(t for t in tables[2:] if not Order.objects.filter(table=t, status__in=Order.RUNNING).exists())
        waiting = place_kot(unpaid_table, some_dishes(), customer_name="Isha")
        for status in (KOT.Status.PREPARING, KOT.Status.READY, KOT.Status.SERVED):
            move_kot(waiting, status, staff["WAITER"])
        make_bill(waiting.order, staff["CASHIER"])

        # ---- deliveries: one from the public menu to confirm, one cooking, one with the rider
        counter = takeaway_table(restaurant)
        place_kot(counter, some_dishes(), "Rohan", "9876500011", customer_address="B-204, Lake View Society, Kalyani Nagar",
                  order_type=Order.OrderType.DELIVERY, to_confirm=True)
        cooking_delivery = place_kot(counter, some_dishes(), "Priya", "9876500012", order_type=Order.OrderType.DELIVERY,
                                     customer_address="7 Rose Lane, near City Mall", source=Order.Source.WAITER,
                                     waiter=staff["WAITER"])
        move_kot(cooking_delivery, KOT.Status.PREPARING, staff["KITCHEN"])
        assign_rider(cooking_delivery.order, staff["RIDER"])
        on_the_way = place_kot(counter, some_dishes(), "Arjun", "9876500013", order_type=Order.OrderType.DELIVERY,
                               customer_address="Flat 12, Shanti Apartments, MG Road", source=Order.Source.WAITER,
                               waiter=staff["WAITER"])
        for status in (KOT.Status.PREPARING, KOT.Status.READY):
            move_kot(on_the_way, status, staff["KITCHEN"])
        make_bill(on_the_way.order, staff["CASHIER"])
        assign_rider(on_the_way.order, staff["RIDER"])
        pick_up(on_the_way.order, staff["RIDER"])

        # ---- bookings: tonight (confirmed, with a table), a request to call back, one tomorrow
        def book(number, day, at, name, phone, guests, status, table=None, source=Booking.Source.PUBLIC):
            Booking.objects.create(restaurant=restaurant, booking_no=number, date=day, time=at, customer_name=name,
                                   customer_phone=phone, guests=guests, status=status, table=table, source=source)
        book(1, today, time(20, 30), "Sana", "9876500021", 4, Booking.Status.CONFIRMED, tables[-1], Booking.Source.STAFF)
        book(2, today, time(21, 15), "Vikram", "9876500022", 2, Booking.Status.REQUESTED)
        book(3, today + timedelta(days=1), time(13, 0), "Ananya", "9876500023", 6, Booking.Status.REQUESTED)

    def pay(self, bill, modes, cashier):
        """Pay a bill in one mode, or now and then in two (cash + UPI)."""
        bill.refresh_from_db()
        if bill.balance <= 0:
            return
        if random.random() < 0.25 and bill.balance > 200:
            first = (bill.balance / 2).quantize(Decimal("1"))
            add_payment(bill, Payment.Mode.CASH, first, "", cashier)
            bill.refresh_from_db()
            add_payment(bill, Payment.Mode.UPI, bill.balance, f"UPI{random.randint(100000, 999999)}", cashier)
        else:
            mode = random.choice(modes)
            reference = f"{random.randint(1000, 9999)}" if "CARD" in mode else ""
            add_payment(bill, mode, bill.balance, reference, cashier)

    def move_to_day(self, order, bill, day):
        """Put an order, its KOTs, bill and payments on a past day (lunch or dinner time)."""
        hour = random.choice([12, 13, 14, 19, 20, 21, 22])
        moment = timezone.make_aware(datetime.combine(day, time(hour, random.randint(0, 59))))
        if moment > timezone.now():
            moment = timezone.now() - timedelta(minutes=random.randint(5, 90))
        Order.objects.filter(pk=order.pk).update(created_at=moment, closed_at=moment + timedelta(minutes=55))
        KOT.objects.filter(order=order).update(created_at=moment, ready_at=moment + timedelta(minutes=18),
                                               served_at=moment + timedelta(minutes=22))
        Bill.objects.filter(pk=bill.pk).update(bill_date=day, created_at=moment + timedelta(minutes=50))
        Payment.objects.filter(bill=bill).update(created_at=moment + timedelta(minutes=52))

    # ------------------------------------------------------------ reset

    def delete_restaurant(self, restaurant):
        """Everything of one restaurant, children first (most links are PROTECT)."""
        with transaction.atomic():
            Payment.objects.filter(restaurant=restaurant).delete()
            BillItem.objects.filter(bill__restaurant=restaurant).delete()
            Bill.objects.filter(restaurant=restaurant).delete()
            KOTItem.objects.filter(kot__restaurant=restaurant).delete()
            KOT.objects.filter(restaurant=restaurant).delete()
            Order.objects.filter(restaurant=restaurant).delete()
            MenuItem.objects.filter(restaurant=restaurant).delete()
            Category.objects.filter(restaurant=restaurant).delete()
            Booking.objects.filter(restaurant=restaurant).delete()
            DiningTable.objects.filter(restaurant=restaurant).delete()
            user_ids = list(restaurant.staff_members.values_list("user_id", flat=True))
            restaurant.staff_members.all().delete()
            User.objects.filter(pk__in=user_ids, is_superuser=False).delete()
            restaurant.delete()
