from django.urls import path
from . import views

urlpatterns = [
    path("kanban/", views.kanban_board, name="kanban"),
    path("kanban/move/", views.kanban_move, name="kanban_move"),
    path("attachments/<int:pk>/", views.attachment_download, name="attachment_download"),
    path("", views.ticket_list, name="ticket_list"),
    path("new/", views.ticket_create, name="ticket_create"),
    path("<str:number>/", views.ticket_detail, name="ticket_detail"),
    path("<str:number>/comment/", views.comment_add, name="comment_add"),
    path("<str:number>/review/", views.ticket_review, name="ticket_review"),
    path("<str:number>/assign/", views.ticket_assign, name="ticket_assign"),
    path("<str:number>/transition/", views.ticket_transition, name="ticket_transition"),
    path("<str:number>/technical-verify/", views.ticket_technical_verify, name="ticket_technical_verify"),
    path("<str:number>/verify/", views.ticket_verify, name="ticket_verify"),
]
