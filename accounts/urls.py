from django.contrib.auth.views import LogoutView
from django.urls import path

from .departments import departments_index
from .views import SiteLoginView

app_name = "accounts"
urlpatterns = [
    path("login", SiteLoginView.as_view(), name="login"),
    path("login/", SiteLoginView.as_view(), name="login_slash"),
    path("logout", LogoutView.as_view(next_page="accounts:login"), name="logout"),
    path("logout/", LogoutView.as_view(next_page="accounts:login"), name="logout_slash"),
    path("settings/departments/", departments_index, name="departments"),
]

from .profile_views import profile, profile_avatar, profile_password

# BEGIN MAKKEN PROFILE URL
urlpatterns = [path("profile/", profile, name="profile"), path("profile/password/", profile_password, name="profile_password"), path("profile/avatar/", profile_avatar, name="profile_avatar")] + list(urlpatterns)
# END MAKKEN PROFILE URL
