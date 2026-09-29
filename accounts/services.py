from django.db import transaction
from django.utils import timezone

from .models import AccountApprovalRequest


def can_review_account_request(user, approval_request):
    return user.is_super_admin or (
        user.is_director and user.division_id == approval_request.division_id
    )


@transaction.atomic
def approve_account_request(*, approval_request, actor):
    approval_request = AccountApprovalRequest.objects.select_for_update().select_related("user").get(
        pk=approval_request.pk,
    )
    if not can_review_account_request(actor, approval_request):
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied
    if approval_request.status != AccountApprovalRequest.Status.PENDING:
        return approval_request
    if approval_request.expires_at <= timezone.now():
        if approval_request.user.profile_photo:
            approval_request.user.profile_photo.delete(save=False)
        approval_request.user.delete()
        return None
    user = approval_request.user
    user.is_active = True
    user.supervisor = actor
    user.save(update_fields=["is_active", "supervisor"])
    approval_request.status = AccountApprovalRequest.Status.APPROVED
    approval_request.reviewed_by = actor
    approval_request.reviewed_at = timezone.now()
    approval_request.save(update_fields=["status", "reviewed_by", "reviewed_at"])
    return approval_request


@transaction.atomic
def purge_expired_account_requests():
    expired_users = list(
        AccountApprovalRequest.objects.filter(
            status=AccountApprovalRequest.Status.PENDING,
            expires_at__lte=timezone.now(),
            user__is_active=False,
        ).select_related("user")
    )
    for approval_request in expired_users:
        if approval_request.user.profile_photo:
            approval_request.user.profile_photo.delete(save=False)
        approval_request.user.delete()
    return len(expired_users)
