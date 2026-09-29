from django.db.models import Q
from .models import Meeting


def visible_meetings_for(user):
    meetings = Meeting.objects.select_related(
        "meeting_type", "requested_by", "organizer", "ticket"
    ).prefetch_related("participant_records__user")
    if user.is_super_admin or user.is_it_user:
        return meetings
    if user.is_director and user.division_id:
        return meetings.filter(
            Q(requested_by__division_id=user.division_id)
            | Q(organizer__division_id=user.division_id)
            | Q(participant_records__user__division_id=user.division_id)
        ).distinct()
    return meetings.filter(
        Q(requested_by=user) | Q(organizer=user) | Q(participant_records__user=user)
    ).distinct()

