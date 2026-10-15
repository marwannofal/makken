from django.urls import path
from . import views

app_name = "care_states"
urlpatterns = [path("", views.index, name="index")]
