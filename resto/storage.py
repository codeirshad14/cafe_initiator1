"""
Static files on the server (settings.STORAGES, DEBUG=False): every CSS / JS file gets a
fingerprint in its name (app.3f9a1c.css) by collectstatic, so after an update every
browser loads the new files at once although Nginx tells them to keep them 30 days.

Never an error 500 because of a static file. Django's own storage stops the whole page
when a file is not in collectstatic's list: a new file after a `git pull` without
`collectstatic` (the app icons took the login page and every staff page down this way),
or Jazzmin's admin asking for the folder 'vendor/bootswatch', which is no file.
Here such a file keeps its plain name (at worst that one picture or script is missing)
and the log says which file to collect. `python manage.py check_setup` lists them too.
"""

import logging
import os

from django.contrib.staticfiles import finders
from django.contrib.staticfiles.storage import ManifestStaticFilesStorage

logger = logging.getLogger(__name__)


class FingerprintedStaticStorage(ManifestStaticFilesStorage):
    manifest_strict = False

    def stored_name(self, name):
        try:
            return super().stored_name(name)
        except ValueError:
            source = finders.find(name)
            if source and os.path.isfile(source):  # a real file, only not collected (not Jazzmin's folder)
                logger.warning("Static file %r was not collected: run python manage.py collectstatic --noinput", name)
            return name
