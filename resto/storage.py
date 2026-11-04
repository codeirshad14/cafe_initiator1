"""
Static files on the server (settings.STORAGES, DEBUG=False): every CSS / JS file gets a
fingerprint in its name (app.3f9a1c.css) by collectstatic, so after an update every
browser loads the new files at once although Nginx tells them to keep them 30 days.

Not strict: a name with no fingerprinted file keeps its plain name instead of
stopping the page. Jazzmin's admin asks for the folder 'vendor/bootswatch' (its theme
switcher), which is no file, and the admin would answer 500 on every page.
"""

from django.contrib.staticfiles.storage import ManifestStaticFilesStorage


class FingerprintedStaticStorage(ManifestStaticFilesStorage):
    manifest_strict = False
