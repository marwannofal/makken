from django.urls import path
from . import views

app_name = "levels"
urlpatterns = [path("", views.index, name="index")]
