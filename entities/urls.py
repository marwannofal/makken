from django.urls import path
from . import views

app_name = "entities"
urlpatterns = [path("", views.index, name="index")]
