from django.urls import path
from . import views
from .willingness import download_attachment

app_name = "partnerships"
urlpatterns = [path("<int:pk>/willingness/attachments/<int:attachment_id>/download/", download_attachment, name="attachment_download"), path("", views.index, name="index"), path("new/", views.editor, name="create"), path("<int:pk>/edit/", views.editor, name="edit")]
