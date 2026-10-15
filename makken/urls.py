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

# BEGIN MAKKEN FAVICON
from django.contrib.auth.decorators import login_not_required as _makken_favicon_public
from django.http import HttpResponseRedirect as _MakkenFaviconRedirect
from django.templatetags.static import static as _makken_favicon_static
from django.urls import path as _makken_favicon_path

@_makken_favicon_public
def _makken_site_favicon(request):
    response = _MakkenFaviconRedirect(
        _makken_favicon_static("accounts/images/favicon.ico") + "?v=090bd1f32c16"
    )
    response["Cache-Control"] = "no-cache"
    return response

urlpatterns = [
    _makken_favicon_path("favicon.ico", _makken_site_favicon, name="site_favicon"),
] + list(urlpatterns)
# END MAKKEN FAVICON

# BEGIN MAKKEN HOME
from core.makken_home import home as _makken_home_view
from django.urls import path as _makken_home_path
urlpatterns = [_makken_home_path("", _makken_home_view, name="makken_home")] + list(urlpatterns)
# END MAKKEN HOME

# BEGIN MAKKEN CARE STATES
from django.urls import include as _care_include, path as _care_path
urlpatterns = [_care_path("settings/development-states/", _care_include("care_states.urls"))] + list(urlpatterns)
# END MAKKEN CARE STATES

# BEGIN MAKKEN LEVELS
from django.urls import include as _levels_include, path as _levels_path
urlpatterns = [_levels_path("settings/levels/", _levels_include("levels.urls"))] + list(urlpatterns)
# END MAKKEN LEVELS

# BEGIN MAKKEN REGIONS
from django.urls import include as _regions_include, path as _regions_path
urlpatterns = [_regions_path("settings/regions/", _regions_include("regions.urls"))] + list(urlpatterns)
# END MAKKEN REGIONS
