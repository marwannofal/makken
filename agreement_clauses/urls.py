from django.urls import path
from . import views

app_name = "agreement_clauses"
urlpatterns = [path("", views.index, name="index")]
