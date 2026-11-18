from django.urls import path
from . import views
from .references import reference_catalog

app_name = "agreement_clauses"
urlpatterns = [path("", views.index, name="index"), path("references/", reference_catalog, name="references")]
