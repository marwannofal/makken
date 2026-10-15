from django.urls import path
from . import views

app_name = "sectors"
urlpatterns = [path("", views.index, name="index")]
