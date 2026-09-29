from django.db.models import Q


def navigation_context(request):
    if not request.user.is_authenticated:
        return {}
    from communications.models import MeetingParticipant
    from accounts.models import AccountApprovalRequest
    from tickets.access import visible_tickets_for

    tickets = visible_tickets_for(request.user)
    open_tickets = tickets.exclude(status__kind__in=["RESOLVED", "CLOSED"])
    verification_filter = Q()
    if request.user.is_super_admin or request.user.is_senior_it:
        verification_filter |= Q(status__code="ready-for-it-verification")
    if request.user.is_super_admin:
        verification_filter |= Q(status__code="ready-for-verification")
    elif request.user.is_director and request.user.division_id:
        verification_filter |= Q(
            status__code="ready-for-verification",
            requesting_division_id=request.user.division_id,
        )
    else:
        verification_filter |= Q(status__code="ready-for-verification", requester=request.user)
    approval_count = 0
    if request.user.is_super_admin:
        approval_count = AccountApprovalRequest.objects.filter(status=AccountApprovalRequest.Status.PENDING).count()
    elif request.user.is_director:
        approval_count = AccountApprovalRequest.objects.filter(
            status=AccountApprovalRequest.Status.PENDING, division=request.user.division,
        ).count()
    return {
        "nav_can_manage_users": request.user.can_manage_users,
        "nav_is_it": request.user.is_it_user,
        "nav_my_tasks_count": open_tickets.filter(current_assignee=request.user).count(),
        "nav_verification_count": tickets.filter(verification_filter).count(),
        "nav_meetings_count": MeetingParticipant.objects.filter(
            user=request.user, response=MeetingParticipant.Response.PENDING,
        ).exclude(meeting__status__in=["COMPLETED", "CANCELLED"]).count(),
        "nav_account_approval_count": approval_count,
    }
