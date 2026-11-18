from django.urls import path
from . import views

app_name = 'makken_mail'
urlpatterns = [
    path('notifications/', views.index, name='index'),
    path('notifications/rules/<str:code>/', views.rule_editor, name='rule'),
    path('notifications/recipient/', views.recipient_select, name='recipient'),
    path('notifications/users/<int:pk>/', views.preferences, name='preferences'),
    path('notifications/smtp/', views.smtp_settings, name='smtp'),
    path('notifications/smtp/test/', views.smtp_test, name='smtp_test'),
    path('notifications/preview/', views.preview, name='preview'),
    path('notifications/deliveries/', views.deliveries, name='deliveries'),
    path('my-work/', views.work_index, name='work_index'),
    path('my-work/new/', views.work_editor, name='work_create'),
    path('my-work/targets/', views.target_options, name='work_targets'),
    path('my-work/<int:pk>/', views.work_detail, name='work_detail'),
    path('my-work/<int:pk>/edit/', views.work_editor, name='work_edit'),
]
