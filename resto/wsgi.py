"""
WSGI config for resto project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.0/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'resto.settings')

application = get_wsgi_application()

# the server: the database (and the static files) brought up to date with the code
# before the first page, so an update can never end in error 500 (resto/startup.py)
from resto.startup import bring_up_to_date  # noqa: E402

bring_up_to_date()
