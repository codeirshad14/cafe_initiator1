from django import template

from pwa.files import app_file_url

register = template.Library()


@register.simple_tag
def app_file(name):
    """{% app_file 'install.js' %} -> /app/install.js?v=3f9a1c0b2e (pwa/files.py)."""
    return app_file_url(name)
