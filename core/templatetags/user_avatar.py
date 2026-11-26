"""Template tag returning the authenticated user's cache-busted avatar URL (or empty string)."""
from __future__ import annotations

from django import template
from django.urls import reverse

register = template.Library()


@register.simple_tag(takes_context=True)
def user_avatar_url(context) -> str:
    request = context.get("request")
    user = getattr(request, "user", None) if request else None
    if not user or not user.is_authenticated:
        return ""
    cached = getattr(request, "_makken_avatar_url", None)
    if cached is not None:
        return cached
    from accounts.models import UserProfile
    prof = UserProfile.objects.filter(user_id=user.pk).only("avatar", "version").first()
    url = f"{reverse('accounts:profile_avatar')}?v={prof.version}" if (prof and prof.avatar) else ""
    request._makken_avatar_url = url
    return url
