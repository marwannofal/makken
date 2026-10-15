from django.urls import path
from . import views

app_name = "specializations"
urlpatterns = [path("", views.index, name="index")]
