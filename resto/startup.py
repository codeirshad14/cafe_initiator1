"""
On the server, each start of the app (every Gunicorn worker: resto/wsgi.py) first makes
sure the database matches the code, so a "git pull" + restart can never run new code on
an old database: the error 500 seen after updates when `migrate` was not run.

  database      a migration of the code not applied yet: `migrate`, before any page is
                served (one worker does it, the others wait for it, then find nothing to do)
  static files  a CSS / JS / icon of the code not collected yet: `collectstatic` in the
                background (one worker), and every worker uses the new files as soon as
                they are there (resto/storage.py notices the new list); meanwhile pages
                still work, with the plain file names

Anything that goes wrong is written to the log (journalctl -u <service>) and the app
starts anyway. Not in development (DEBUG=True), nor with AUTO_UPDATE=False in .env.
deploy/update.sh does the same steps by hand, with their output on screen.
"""

import logging
import os
import tempfile
import threading
from contextlib import contextmanager

logger = logging.getLogger("resto.startup")


@contextmanager
def only_one(name, wait=True):
    """A lock between the workers (a file in the temp folder). Yields True when this worker
    holds it; with wait=False, False at once when another worker has it."""
    try:
        import fcntl
    except ImportError:  # not Linux: a single process anyway
        yield True
        return
    path = os.path.join(tempfile.gettempdir(), f"mrcafe-{name}-{os.getuid()}.lock")
    with open(path, "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX if wait else fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def migrations_to_apply():
    from django.db import DEFAULT_DB_ALIAS, connections
    from django.db.migrations.executor import MigrationExecutor

    executor = MigrationExecutor(connections[DEFAULT_DB_ALIAS])
    return [f"{migration.app_label}.{migration.name}"
            for migration, _ in executor.migration_plan(executor.loader.graph.leaf_nodes())]


def static_to_collect():
    """The code's static files missing from collectstatic's list (only on the server)."""
    from django.contrib.staticfiles import finders
    from django.contrib.staticfiles.storage import staticfiles_storage

    collected = getattr(staticfiles_storage, "hashed_files", None)
    if collected is None:
        return []
    found = {path.replace("\\", "/") for finder in finders.get_finders() for path, _ in finder.list(["CVS", ".*", "*~"])}
    return sorted(found - set(collected))


def update_database():
    with only_one("migrate"):
        waiting = migrations_to_apply()
        if waiting:
            logger.warning("Applying %d database change(s) before starting: %s", len(waiting), ", ".join(waiting))
            from django.core.management import call_command
            call_command("migrate", interactive=False, verbosity=0)
            logger.warning("Database up to date.")


def collect_static_in_background():
    missing = static_to_collect()
    if not missing:
        return

    def collect():
        try:
            with only_one("collectstatic", wait=False) as mine:
                if not mine:
                    return  # another worker is collecting
                logger.warning("Collecting %d new static file(s), e.g. %s", len(missing), missing[0])
                from django.core.management import call_command
                call_command("collectstatic", interactive=False, verbosity=0)
                logger.warning("Static files up to date.")
        except Exception:
            logger.exception("Could not collect the static files (does the app's user own staticfiles/?). "
                             "Run: sudo bash deploy/update.sh")

    threading.Thread(target=collect, name="mrcafe-collectstatic", daemon=True).start()


def bring_up_to_date():
    from django.conf import settings
    from django.db import connections

    if settings.DEBUG or not getattr(settings, "AUTO_UPDATE", True):
        return
    try:
        update_database()
    except Exception:
        logger.exception("Could not update the database at start. Run: sudo bash deploy/update.sh")
    finally:
        connections.close_all()  # each worker opens its own connection when a page needs one
    try:
        collect_static_in_background()
    except Exception:
        logger.exception("Could not check the static files at start.")
