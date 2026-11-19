from django.urls import path
from agreement_clauses.followup import download_evidence
from agreement_clauses.inquiries import agreement_inquiries
from agreement_clauses.records import agreement_details
from agreement_clauses.workflow import workflow
from . import views
from .willingness import download_attachment

app_name = "partnerships"
urlpatterns = [path("<int:pk>/willingness/attachments/<int:attachment_id>/download/", download_attachment, name="attachment_download"), path("", views.index, name="index"), path("new/", views.editor, name="create"), path("<int:pk>/edit/", views.editor, name="edit")]

urlpatterns += [
    path("agreements/inquiries/", agreement_inquiries, name="agreement_inquiries"),
    path("<int:pk>/clauses/", workflow, name="clauses"),
    path("<int:pk>/agreements/<int:agreement_id>/", workflow, name="agreement"),
    path("<int:pk>/agreements/<int:agreement_id>/details/", agreement_details, name="agreement_details"),
    path("<int:pk>/agreements/<int:agreement_id>/evidence/<int:attachment_id>/download/",
         download_evidence, name="agreement_evidence_download"),
]
