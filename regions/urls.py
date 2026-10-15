from django.urls import path
from . import views

app_name = "regions"
urlpatterns = [path("", views.index, name="index")]
