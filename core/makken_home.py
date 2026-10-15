from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from accounts.security import add_login_headers


@login_required(login_url="accounts:login")
def home(request):
    name = request.user.get_short_name() or request.user.get_username()
    return add_login_headers(render(request, "core/makken_home.html", {
        "display_name": name,
        "avatar_initial": name[:1],
        "active_page": "home",
    }))
