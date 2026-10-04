from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from accounts.models import User
from tickets.access import visible_tickets_for
from .models import Meeting, MeetingType


class MeetingForm(forms.ModelForm):
    participants = forms.ModelMultipleChoiceField(
        queryset=User.objects.none(), widget=forms.SelectMultiple(attrs={"size": 8}),
        help_text="Select one or more participants.",
    )

    class Meta:
        model = Meeting
        fields = (
            "title", "meeting_type", "reason", "description", "scheduled_start", "scheduled_end",
            "participants", "ticket", "location_link",
        )
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
            "scheduled_start": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
            "scheduled_end": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields["participants"].queryset = User.objects.filter(is_active=True).select_related("division", "role").order_by("division__code", "first_name")
        self.fields["meeting_type"].queryset = MeetingType.objects.filter(is_active=True)
        self.fields["ticket"].queryset = visible_tickets_for(user) if user else self.fields["ticket"].queryset.none()
        self.fields["scheduled_start"].input_formats = ["%Y-%m-%dT%H:%M"]
        self.fields["scheduled_end"].input_formats = ["%Y-%m-%dT%H:%M"]
        start = timezone.localtime() + timezone.timedelta(days=1)
        start = start.replace(minute=0, second=0, microsecond=0)
        self.fields["scheduled_start"].initial = start.strftime("%Y-%m-%dT%H:%M")
        self.fields["scheduled_end"].initial = (start + timezone.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("scheduled_start"), cleaned.get("scheduled_end")
        if start and end and end <= start:
            self.add_error("scheduled_end", "The meeting must end after it starts.")
        if start and start < timezone.now() - timezone.timedelta(minutes=5):
            self.add_error("scheduled_start", "Choose a future meeting time.")
        return cleaned


class MeetingActionForm(forms.Form):
    action = forms.ChoiceField(choices=[
        ("accept", "Accept"), ("decline", "Decline"),
        ("reschedule", "Reschedule"), ("complete", "Complete"), ("cancel", "Cancel"),
    ])
    proposed_start = forms.DateTimeField(
        required=False, widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        input_formats=["%Y-%m-%dT%H:%M"],
    )
    note = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))

    def __init__(self, *args, participant=False, can_manage=False, **kwargs):
        super().__init__(*args, **kwargs)
        choices = []
        if participant:
            choices.extend([("accept", "Accept"), ("decline", "Decline"), ("propose", "Propose new time")])
        if can_manage:
            choices.extend([("reschedule", "Reschedule"), ("complete", "Complete"), ("cancel", "Cancel")])
        self.fields["action"].choices = choices
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("action") in {"propose", "reschedule"} and not cleaned.get("proposed_start"):
            raise ValidationError("Choose the proposed meeting time.")
        if cleaned.get("action") in {"decline", "cancel"} and not cleaned.get("note", "").strip():
            raise ValidationError("A reason is required for this action.")
        return cleaned
