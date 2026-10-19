from access_control.integration import permission_aware_login
# MAKKEN RBAC INTEGRATION v1
from django.contrib.auth.views import LoginView
from django.shortcuts import render
from django.views.csrf import csrf_failure as default_csrf_failure

from .forms import SiteAuthenticationForm
from .security import add_login_headers


@permission_aware_login
class SiteLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = SiteAuthenticationForm
    redirect_authenticated_user = True

    def form_valid(self, form):
        response = super().form_valid(form)
        self.request.session.set_expiry(
            60 * 60 * 24 * 14 if form.cleaned_data["remember_me"] else 0
        )
        return response


def render_login_error(request, message, status=403):
    response = render(request, "accounts/login.html", {
        "form": SiteAuthenticationForm(request=request),
        "security_message": message,
        "next": "",
    }, status=status)
    return add_login_headers(response)


def lockout(request, original_response=None, credentials=None):
    response = render_login_error(
        request,
        "تجاوزت الحد المسموح لمحاولات الدخول. يُرجى الانتظار 15 دقيقة ثم المحاولة مرة أخرى.",
        status=429,
    )
    response["Retry-After"] = "900"
    return response


def csrf_failure(request, reason=""):
    if request.path in {"/login", "/login/", "/logout", "/logout/"}:
        return render_login_error(
            request,
            "تعذّر التحقق من أمان الطلب. أعد تحميل الصفحة ثم حاول مرة أخرى.",
            status=403,
        )
    return default_csrf_failure(request, reason=reason)
