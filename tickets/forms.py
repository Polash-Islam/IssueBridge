from django import forms
from django.db import models
from django.utils import timezone

from accounts.models import User
from core.models import Division
from .models import (
    Product, Ticket, TicketCategory, TicketComment, TicketPriority, TicketReview,
    TicketVerification, WorkflowStatus,
    TicketTechnicalVerification,
)
from .validators import validate_attachment


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput(attrs={"accept": ".png,.jpg,.jpeg,.pdf,.doc,.docx,.xls,.xlsx,.zip"}))
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single_clean = super().clean
        if isinstance(data, (list, tuple)):
            result = [single_clean(item, initial) for item in data]
        else:
            result = [single_clean(data, initial)] if data else []
        for uploaded in result:
            validate_attachment(uploaded)
        return result


class RequesterChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, user):
        full_name = " ".join(
            part.strip() for part in (user.first_name, user.last_name) if part and part.strip()
        )
        if full_name and user.email:
            return f"{full_name} ({user.email})"
        return full_name or user.email or user.username


class RequesterMultipleChoiceField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, user):
        full_name = " ".join(
            part.strip() for part in (user.first_name, user.last_name) if part and part.strip()
        )
        if full_name and user.email:
            return f"{full_name} ({user.email})"
        return full_name or user.email or user.username


class TicketCreateForm(forms.ModelForm):
    request_type = forms.ChoiceField(
        choices=Ticket.RequestType.choices, required=False, initial=Ticket.RequestType.IT,
    )
    assign_to = RequesterChoiceField(
        queryset=User.objects.none(), required=False, label="Assign work to",
    )
    requesting_division = forms.ModelChoiceField(
        queryset=Division.objects.none(), required=False, label="Division for this request",
    )
    recipients = RequesterMultipleChoiceField(
        queryset=User.objects.none(), required=False,
        widget=forms.SelectMultiple(attrs={"size": 6}),
        help_text="Approval is complete when all recipients have approved.",
    )
    attachments = MultipleFileField(required=False, help_text="PNG, JPG, PDF, Office, or ZIP. Maximum 10 MB each.")

    class Meta:
        model = Ticket
        fields = (
            "request_type", "title", "description", "product", "category", "priority",
            "expected_behavior", "actual_behavior",
            "browser_device", "additional_notes", "parent",
        )
        widgets = {
            "description": forms.Textarea(attrs={"rows": 5, "placeholder": "Describe what happened, including steps to reproduce the problem."}),
            "expected_behavior": forms.Textarea(attrs={"rows": 3}),
            "actual_behavior": forms.Textarea(attrs={"rows": 3}),
            "additional_notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields["product"].queryset = Product.objects.filter(is_active=True).select_related("division")
        self.fields["category"].queryset = TicketCategory.objects.filter(is_active=True)
        self.fields["priority"].queryset = TicketPriority.objects.filter(is_active=True)
        self.fields["product"].empty_label = "Select Product / System"
        self.fields["category"].empty_label = "Select Category"
        self.fields["priority"].empty_label = "Select Priority"
        self.fields["product"].required = False
        self.fields["category"].required = False
        self.fields["priority"].required = False
        self.fields["parent"].queryset = Ticket.objects.none()
        self.fields["requesting_division"].queryset = Division.objects.filter(is_active=True)
        if user and user.division_id:
            self.fields.pop("requesting_division")
        if user and (user.is_super_admin or user.is_senior_it):
            self.fields["assign_to"].queryset = User.objects.filter(is_active=True).exclude(
                role__is_division_director=True,
            ).select_related("division", "role").order_by("division__code", "first_name", "last_name")
            self.fields["assign_to"].empty_label = "Select a responsible person"
        else:
            self.fields.pop("assign_to")
        self.fields["recipients"].queryset = User.objects.filter(is_active=True).exclude(
            pk=getattr(user, "pk", None),
        ).select_related("division", "role").order_by(
            "division__code", "first_name", "last_name",
        )
        if user:
            from .access import visible_tickets_for
            self.fields["parent"].queryset = visible_tickets_for(user)
        for name, field in self.fields.items():
            field.widget.attrs.setdefault("class", "form-control")
            if not field.widget.attrs.get("placeholder"):
                field.widget.attrs["placeholder"] = field.label

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("request_type"):
            cleaned["request_type"] = Ticket.RequestType.IT
        requester = self.user
        if cleaned.get("request_type") == Ticket.RequestType.DIRECT:
            recipients = cleaned.get("recipients", [])
            if not recipients:
                self.add_error("recipients", "Select at least one recipient.")
            if requester and any(recipient.pk == requester.pk for recipient in recipients):
                self.add_error("recipients", "The requester cannot also be a recipient.")
        elif cleaned.get("request_type") == Ticket.RequestType.IT:
            for name in ("product", "category", "priority"):
                if not cleaned.get(name):
                    self.add_error(name, "This field is required for IT support tickets.")
        self.requesting_division = (
            requester.division if requester and requester.division_id
            else cleaned.get("requesting_division")
        )
        if not self.requesting_division:
            if "requesting_division" in self.fields:
                self.add_error("requesting_division", "Select the division this request belongs to.")
            else:
                raise forms.ValidationError("Your account must be assigned to a Division before creating a ticket.")
        return cleaned

    def save(self, commit=True):
        ticket = super().save(commit=False)
        ticket.requesting_division = self.requesting_division
        if commit:
            ticket.save()
            self.save_m2m()
        return ticket


class DirectRequestResponseForm(forms.Form):
    class Action(models.TextChoices):
        APPROVE = "APPROVE", "Approve"
        DECLINE = "DECLINE", "Decline"
        DISCUSS = "DISCUSS", "Request a discussion"
        MEETING = "MEETING", "Request a meeting"

    action = forms.ChoiceField(choices=Action.choices)
    deadline = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        input_formats=["%Y-%m-%dT%H:%M"],
    )
    reason = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))
    note = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")

    def clean(self):
        cleaned = super().clean()
        action = cleaned.get("action")
        if action == self.Action.APPROVE:
            deadline = cleaned.get("deadline")
            if not deadline:
                self.add_error("deadline", "Provide the deadline you can commit to.")
            elif deadline <= timezone.now():
                self.add_error("deadline", "Choose a future deadline.")
        elif action == self.Action.DECLINE and not cleaned.get("reason", "").strip():
            self.add_error("reason", "A reason is required when declining.")
        return cleaned


class CommentForm(forms.ModelForm):
    attachments = MultipleFileField(required=False)

    class Meta:
        model = TicketComment
        fields = ("body", "visibility")
        widgets = {"body": forms.Textarea(attrs={"rows": 3, "placeholder": "Write an update or reply…"})}

    def __init__(self, *args, user=None, allow_internal=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.allow_internal = (
            bool(user and (user.is_super_admin or user.is_it_user))
            if allow_internal is None else allow_internal
        )
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
        if not self.allow_internal:
            self.fields["visibility"].choices = [(TicketComment.Visibility.PUBLIC, "Requester visible")]

    def clean_visibility(self):
        visibility = self.cleaned_data["visibility"]
        if visibility == TicketComment.Visibility.INTERNAL and not self.allow_internal:
            raise forms.ValidationError("Internal comments are restricted to IT.")
        return visibility


class ReviewForm(forms.Form):
    decision = forms.ChoiceField(choices=TicketReview.Decision.choices)
    reason = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3, "placeholder": "Reason or information required from the requester"}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")


class AssignmentForm(forms.Form):
    assigned_to = RequesterChoiceField(queryset=User.objects.none(), label="Responsible person")
    task_description = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}))
    technical_instructions = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))
    expected_output = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))
    deadline = forms.DateTimeField(required=False, widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"), input_formats=["%Y-%m-%dT%H:%M"])
    additional_notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assigned_to"].queryset = User.objects.filter(is_active=True).exclude(
            role__is_division_director=True,
        ).select_related("division", "role").order_by(
            "division__code", "first_name", "last_name",
        )
        self.fields["assigned_to"].empty_label = "Select a responsible person"
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")


class DeadlineExtensionForm(forms.Form):
    deadline = forms.DateTimeField(
        label="New deadline",
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        input_formats=["%Y-%m-%dT%H:%M"],
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["deadline"].widget.attrs.setdefault("class", "form-control")

    def clean_deadline(self):
        deadline = self.cleaned_data["deadline"]
        if deadline <= timezone.now():
            raise forms.ValidationError("Choose a future date and time.")
        return deadline


class TransitionForm(forms.Form):
    to_status = forms.ModelChoiceField(queryset=WorkflowStatus.objects.none())
    comment = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2, "placeholder": "Add a reason or update (required for some changes)"}))

    def __init__(self, *args, queryset=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["to_status"].queryset = queryset or WorkflowStatus.objects.none()
        self.fields["to_status"].empty_label = None
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")


class VerificationForm(forms.Form):
    decision = forms.ChoiceField(choices=TicketVerification.Decision.choices, widget=forms.RadioSelect)
    reason = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3, "placeholder": "If the problem remains, describe exactly what still fails."}))


class TechnicalVerificationForm(forms.Form):
    decision = forms.ChoiceField(choices=TicketTechnicalVerification.Decision.choices, widget=forms.RadioSelect)
    reason = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3, "placeholder": "Record checks performed, or explain what the responsible person must correct."}))

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("decision") == TicketTechnicalVerification.Decision.RETURNED and not cleaned.get("reason", "").strip():
            raise forms.ValidationError("Explain what the responsible person must correct before resubmitting.")
        return cleaned
