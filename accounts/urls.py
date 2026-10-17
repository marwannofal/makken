from django.contrib.auth.views import LogoutView
from django.urls import path

from .views import SiteLoginView

app_name = "accounts"
urlpatterns = [
    path("login", SiteLoginView.as_view(), name="login"),
    path("login/", SiteLoginView.as_view(), name="login_slash"),
    path("logout", LogoutView.as_view(next_page="accounts:login"), name="logout"),
    path("logout/", LogoutView.as_view(next_page="accounts:login"), name="logout_slash"),
]

from .profile_views import profile

# BEGIN MAKKEN PROFILE URL
urlpatterns = [path("profile/", profile, name="profile")] + list(urlpatterns)
# END MAKKEN PROFILE URL
