from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("core.urls")),
]

# BEGIN MAKKEN LOGIN ROUTES
from django.urls import include as _makken_login_include, path as _makken_login_path
urlpatterns = [
    _makken_login_path("", _makken_login_include("accounts.urls")),
] + urlpatterns
# END MAKKEN LOGIN ROUTES
