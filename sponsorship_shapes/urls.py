from django.urls import path
from . import views

app_name = "sponsorship_shapes"
urlpatterns = [path("", views.index, name="index")]
