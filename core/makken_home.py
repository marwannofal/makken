"""Makken landing home page on / (analytics dashboard lives at /dashboard/)."""
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.http import require_GET

from access_control.enforcement import module_view
from accounts.security import add_login_headers


@module_view("home")
@login_required(login_url="accounts:login")
@require_GET
def home(request):
    name = request.user.get_short_name() or request.user.get_username()
    return add_login_headers(render(request, "core/landing_home.html", {
        "display_name": name,
        "avatar_initial": name[:1],
        "active_page": "home",
        "page_heading": "الرئيسية",
    }))
