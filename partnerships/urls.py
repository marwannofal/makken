from django.urls import path
from . import views

app_name = "partnerships"
urlpatterns = [path("", views.index, name="index"), path("new/", views.editor, name="create"), path("<int:pk>/edit/", views.editor, name="edit")]
