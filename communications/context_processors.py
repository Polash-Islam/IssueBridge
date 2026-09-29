def notification_context(request):
    if not request.user.is_authenticated:
        return {}
    queryset = request.user.notifications.select_related("actor", "ticket", "meeting", "approval_request")
    return {
        "unread_notification_count": queryset.filter(is_read=False).count(),
        "recent_notifications": queryset[:5],
    }
