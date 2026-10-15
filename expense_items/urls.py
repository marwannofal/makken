from django.urls import path
from . import views

app_name = "expense_items"
urlpatterns = [path("", views.index, name="index")]
