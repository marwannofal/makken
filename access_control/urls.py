from django.urls import path
from . import views
app_name='access_control'
urlpatterns=[
    path('',views.index,name='index'),
    path('users/new/',views.user_editor,name='user_create'),
    path('users/<int:pk>/',views.user_editor,name='user_edit'),
    path('users/<int:pk>/status/',views.user_status,name='user_status'),
    path('users/<int:pk>/password/',views.password,name='password'),
    path('roles/',views.roles,name='roles'),
    path('roles/new/',views.role_editor,name='role_create'),
    path('roles/<int:pk>/',views.role_editor,name='role_edit'),
    path('roles/<int:pk>/<str:operation>/',views.role_action,name='role_action'),
    path('logs/',views.logs,name='logs'),
    path('landing/',views.landing,name='landing'),
    path('no-access/',views.no_access,name='no_access'),
]
