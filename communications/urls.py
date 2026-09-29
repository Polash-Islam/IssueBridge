from django.urls import path
from . import views

urlpatterns = [
    path("meetings/", views.meeting_list, name="meeting_list"),
    path("meetings/new/", views.meeting_create, name="meeting_create"),
    path("meetings/<str:reference>/", views.meeting_detail, name="meeting_detail"),
    path("meetings/<str:reference>/action/", views.meeting_action, name="meeting_action"),
    path("notifications/", views.notification_list, name="notification_list"),
    path("notifications/read-all/", views.notifications_read_all, name="notifications_read_all"),
    path("notifications/<int:pk>/open/", views.notification_open, name="notification_open"),
    path("calendar/", views.calendar_view, name="calendar"),
]

