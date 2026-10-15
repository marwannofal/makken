from django.urls import path
from . import views

app_name = "training_programs"
urlpatterns = [path("", views.index, name="index")]
