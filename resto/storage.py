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

A new collectstatic while the app runs (resto/startup.py does one after an update) is
picked up by every worker within a few seconds: the list (staticfiles.json) is read again
when it changed, so the new styles show without another restart.
"""

import logging
import os
import time

from django.contrib.staticfiles import finders
from django.contrib.staticfiles.storage import ManifestStaticFilesStorage

logger = logging.getLogger(__name__)
LOOK_AGAIN_AFTER = 5  # seconds between looks at staticfiles.json


class FingerprintedStaticStorage(ManifestStaticFilesStorage):
    manifest_strict = False
    _manifest_seen = None   # (the list's modified time) when it was read
    _looked_at = 0.0

    def stored_name(self, name):
        self._read_new_list()
        try:
            return super().stored_name(name)
        except ValueError:
            source = finders.find(name)
            if source and os.path.isfile(source):  # a real file, only not collected (not Jazzmin's folder)
                logger.warning("Static file %r was not collected: run python manage.py collectstatic --noinput", name)
            return name

    def _list_time(self):
        try:
            return os.path.getmtime(self.manifest_storage.path(self.manifest_name))
        except (OSError, NotImplementedError):
            return None  # not collected yet

    def load_manifest(self):
        self._manifest_seen = self._list_time()  # the list's time as it is read
        return super().load_manifest()

    def _read_new_list(self):
        """collectstatic ran again since this worker read the list: read it again."""
        now = time.monotonic()
        if now - self._looked_at < LOOK_AGAIN_AFTER:
            return
        self._looked_at = now
        if self._list_time() != self._manifest_seen:
            self.hashed_files, self.manifest_hash = self.load_manifest()  # (Django 4.2+: both)
            logger.info("New static files in use (collectstatic ran again).")
