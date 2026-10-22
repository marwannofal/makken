from django.urls import path
from . import execution_views as views

app_name = "program_execution"
urlpatterns = [
    path("", views.index, name="index"),
    path("assignments/", views.assignments, name="assignments"),
    path("<int:pk>/providers/", views.assignment, name="assignment"),
]
