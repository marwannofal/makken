from django.urls import path
from . import views
from . import dashboard_views

app_name = "core"

urlpatterns = [
    path('dashboard/', dashboard_views.home, name='dashboard'),
    path('dashboard/export/<str:format>/',dashboard_views.export,name='dashboard_export'),
    path('dashboard/records/<str:kind>/',dashboard_views.records,name='dashboard_records'),
    path("", views.home, name="home"),
]
