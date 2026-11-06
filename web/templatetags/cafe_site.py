"""{% load cafe_site %}: for the Cafe profile tabs."""

from django import template

register = template.Library()


@register.simple_tag
def unread_feedback(restaurant):
    """How many feedback messages the cafe has not opened yet (the Feedback tab's count)."""
    return restaurant.feedback.filter(is_read=False).count() if restaurant else 0
