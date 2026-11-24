from django.urls import path
from . import views

app_name = 'flex_analytics'

urlpatterns = [
    path('', views.index, name='index'),
    path('api/bootstrap/', views.api_bootstrap, name='api_bootstrap'),
    path('api/compatibility/', views.api_compatibility, name='api_compatibility'),
    path('api/dashboards/', views.api_dashboards, name='api_dashboards'),
    path('api/dashboards/<int:pk>/', views.api_dashboard_detail, name='api_dashboard_detail'),
    path('api/dashboards/<int:pk>/action/', views.api_dashboard_action, name='api_dashboard_action'),
    path('api/dashboards/<int:pk>/revisions/', views.api_revisions, name='api_revisions'),
    path('api/dashboards/<int:pk>/shares/', views.api_shares, name='api_shares'),
    path('api/query/', views.api_query, name='api_query'),
    path('api/drilldown/', views.api_drilldown, name='api_drilldown'),
    path('api/export/', views.api_export, name='api_export'),
]
