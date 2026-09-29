from django.db.models import Q

from .models import Ticket


def visible_tickets_for(user):
    queryset = Ticket.objects.select_related(
        "requester", "requesting_division", "product", "category", "priority", "status", "current_assignee"
    )
    if user.is_super_admin or user.is_senior_it or (user.is_director and user.is_it_user):
        return queryset
    if user.is_director and user.division_id:
        return queryset.filter(requesting_division_id=user.division_id)
    if not user.division_id:
        return queryset.filter(Q(requester=user) | Q(current_assignee=user)).distinct()
    return queryset.filter(
        Q(requesting_division_id=user.division_id) | Q(requester=user) | Q(current_assignee=user) | Q(watchers=user)
    ).distinct()


def can_view_internal_comments(user):
    return user.is_super_admin or user.is_it_user


def can_review_ticket(user):
    return user.is_super_admin or user.is_senior_it


def can_assign_ticket(user):
    return user.is_super_admin or user.is_senior_it


def can_verify_ticket(user, ticket):
    return user.is_super_admin or user == ticket.requester or (
        user.is_director and user.division_id == ticket.requesting_division_id
    )


def can_technical_verify_ticket(user, ticket):
    return user.is_super_admin or user.is_senior_it
