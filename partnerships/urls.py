from django.urls import path
from agreement_clauses.followup import download_evidence
from agreement_clauses.inquiries import agreement_inquiries
from agreement_clauses.records import agreement_details
from agreement_clauses.workflow import workflow
from . import views
from .achievement import partnership_achievement_report
from .sponsor_requests import (
    public_sponsor_register,
    public_sponsor_thanks,
    sponsor_request_queue,
    sponsor_request_attachment_download,
    sponsor_request_review,
)
from .willingness import download_attachment

app_name = "partnerships"
urlpatterns = [path("<int:pk>/willingness/attachments/<int:attachment_id>/download/", download_attachment, name="attachment_download"), path("", views.index, name="index"), path("all/", views.all_index, name="all_index"), path("capability/", views.capability_index, name="capability_index"), path("willingness/", views.willingness_index, name="willingness_index"), path("willingness/new/", views.editor_willingness, name="create_willingness"), path("new/", views.editor, name="create"), path("<int:pk>/edit/", views.editor, name="edit")]

urlpatterns += [
    path("agreements/inquiries/", agreement_inquiries, name="agreement_inquiries"),
    path("reports/achievement/", partnership_achievement_report, name="achievement_report"),
    path("register/", public_sponsor_register, name="public_sponsor_register"),
    path("register/submitted/", public_sponsor_thanks, name="public_sponsor_thanks"),
    path("requests/", sponsor_request_queue, name="sponsor_requests"),
    path("requests/<int:request_id>/", sponsor_request_review, name="sponsor_request_review"),
    path("requests/<int:request_id>/attachments/<int:attachment_id>/download/", sponsor_request_attachment_download, name="sponsor_request_attachment_download"),
    path("<int:pk>/clauses/", workflow, name="clauses"),
    path("<int:pk>/clauses-progress/", views.clauses_progress, name="clauses_progress"),
    path("<int:pk>/works/<int:work_pk>/", views.work_assignment_edit, name="work_edit"),
    path("<int:pk>/clauses-evidence/<int:evidence_id>/download/", views.download_clause_evidence, name="clause_evidence_download"),
    path("<int:pk>/agreements/<int:agreement_id>/", workflow, name="agreement"),
    path("<int:pk>/agreements/<int:agreement_id>/details/", agreement_details, name="agreement_details"),
    path("<int:pk>/agreements/<int:agreement_id>/evidence/<int:attachment_id>/download/",
         download_evidence, name="agreement_evidence_download"),
]
