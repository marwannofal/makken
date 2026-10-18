from django.urls import path
from . import views

app_name = "market_needs"
urlpatterns = [
    path("", views.index, name="index"),
    path("new/", views.editor, name="create"),
    path("<int:pk>/edit/", views.editor, name="edit"),
    path("<int:pk>/sponsors/", views.followup, name="followup"),
    path("<int:pk>/attachments/<int:attachment_id>/download/", views.download, name="download"),
]
