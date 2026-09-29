from django.contrib import admin
from .models import Meeting, MeetingHistory, MeetingParticipant, MeetingType, Notification


class ParticipantInline(admin.TabularInline):
    model = MeetingParticipant
    extra = 0


@admin.register(Meeting)
class MeetingAdmin(admin.ModelAdmin):
    list_display = ("reference", "title", "meeting_type", "scheduled_start", "status", "organizer")
    list_filter = ("status", "meeting_type")
    search_fields = ("reference", "title", "reason")
    inlines = (ParticipantInline,)


admin.site.register(MeetingType)
admin.site.register(MeetingHistory)
admin.site.register(Notification)
