from django.urls import path
from . import views

urlpatterns = [
    path("", views.user_list, name="user_list"),
    path("new/", views.user_create, name="user_create"),
    path("approvals/", views.account_approval_list, name="account_approval_list"),
    path("approvals/<int:pk>/approve/", views.account_approve, name="account_approve"),
    path("profile/", views.profile, name="profile"),
    path("profile/edit/", views.profile_edit, name="profile_edit"),
    path("profile/password/", views.password_change, name="password_change"),
    path("<int:pk>/edit/", views.user_edit, name="user_edit"),
]
