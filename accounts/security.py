from ipaddress import ip_address

from django.utils.cache import patch_cache_control


LOGIN_PATHS = {"/login", "/login/", "/logout", "/logout/"}


def client_ip(request):
    """Trust X-Real-IP only from the local/private reverse proxy.

    This requires Nginx to overwrite X-Real-IP with $remote_addr, and the
    backend port to remain bound to 127.0.0.1, as in the deployed configuration.
    """
    remote = request.META.get("REMOTE_ADDR", "")
    try:
        peer = ip_address(remote)
    except ValueError:
        return None
    if peer.is_private or peer.is_loopback:
        forwarded = request.META.get("HTTP_X_REAL_IP", "")
        try:
            return str(ip_address(forwarded))
        except ValueError:
            pass
    return str(peer)


def add_login_headers(response):
    patch_cache_control(response, private=True, no_store=True, no_cache=True, max_age=0)
    response["Pragma"] = "no-cache"
    response["X-Frame-Options"] = "DENY"
    response["X-Content-Type-Options"] = "nosniff"
    response["Referrer-Policy"] = "same-origin"
    response["X-Robots-Tag"] = "noindex, nofollow"
    response["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self' https://fonts.googleapis.com; "
        "img-src 'self' data:; font-src 'self' https://fonts.gstatic.com; "
        "connect-src 'self' https://fonts.googleapis.com https://fonts.gstatic.com; "
        "form-action 'self'; frame-ancestors 'none'; base-uri 'self'; object-src 'none'"
    )
    return response


class LoginSecurityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path in LOGIN_PATHS and request.method == "POST":
            try:
                too_large = int(request.META.get("CONTENT_LENGTH") or 0) > 16384
            except (TypeError, ValueError):
                too_large = True
            if too_large:
                from accounts.views import render_login_error
                response = render_login_error(
                    request, "تعذّر إتمام الطلب. أعد تحميل الصفحة وحاول مرة أخرى.", status=400
                )
                return add_login_headers(response)
        response = self.get_response(request)
        if request.path in LOGIN_PATHS:
            add_login_headers(response)
        return response
