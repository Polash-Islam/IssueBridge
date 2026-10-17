from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.password_validation import validate_password
from django.db.models import Q
from core.models import Division
from .reference_data import DIVISION_ROLES, DIVISIONS, ROLE_CODES, ROLE_NAMES_BY_CODE
from .models import Role, User
from tickets.models import TicketIntakeRoute


class OfficerRegistrationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = (
            "first_name", "last_name", "employee_id", "email", "mobile",
            "division", "role", "profile_photo",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["division"].queryset = self.fields["division"].queryset.filter(
            code__in=[code for code, _ in DIVISIONS],
        )
        self.fields["division"].required = True
        self.fields["division"].empty_label = "Select Your Division"
        division_labels = dict(DIVISIONS)
        self.fields["division"].label_from_instance = lambda item: division_labels[item.code]
        division_id = self.data.get(self.add_prefix("division")) if self.is_bound else self.initial.get("division")
        division_id = getattr(division_id, "pk", division_id)
        self.fields["role"].queryset = Role.objects.none()
        self.fields["role"].required = True
        role_rows = Role.objects.filter(
            division__code__in=[code for code, _ in DIVISIONS],
            code__in=list(ROLE_CODES.values()),
        ).values("pk", "code", "division_id", "division__code")
        self.role_options = [
            {"pk": item["pk"], "name": ROLE_NAMES_BY_CODE[item["code"]], "division_id": item["division_id"]}
            for item in role_rows
            if item["code"] in ROLE_CODES.values()
            and ROLE_NAMES_BY_CODE[item["code"]] in DIVISION_ROLES.get(item["division__code"], [])
        ]
        if division_id:
            division_code = Division.objects.filter(pk=division_id).values_list("code", flat=True).first()
            self.fields["role"].queryset = Role.objects.filter(
                division_id=division_id,
                code__in=[ROLE_CODES[name] for name in DIVISION_ROLES.get(division_code, [])],
            ).order_by("name")
        self.fields["role"].label_from_instance = lambda item: ROLE_NAMES_BY_CODE[item.code]
        self.fields["division"].widget.attrs["data-role-field"] = "id_role"
        self.fields["role"].widget.attrs["data-division-field"] = "id_division"
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account already exists with this email address.")
        return email

    def clean_division(self):
        division = self.cleaned_data["division"]
        has_division_head = User.objects.filter(
            division=division, role__is_division_director=True, is_active=True,
        ).exists()
        if not has_division_head and not User.objects.filter(
            Q(is_active=True, is_superuser=True) | Q(is_active=True, role__code="super-admin"),
        ).exists():
            raise forms.ValidationError("There is no active Division Head or Super Admin available to approve this account.")
        return division

    def clean(self):
        cleaned = super().clean()
        division, role = cleaned.get("division"), cleaned.get("role")
        if division and role and role.division_id != division.pk:
            self.add_error("role", "Select a role that belongs to the selected division.")
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        user.username = user.email
        user.role = self.cleaned_data["role"]
        user.designation = ROLE_NAMES_BY_CODE[user.role.code]
        user.is_active = False
        director = User.objects.filter(
            division=self.cleaned_data["division"], role__is_division_director=True, is_active=True,
        ).order_by("pk").first()
        user.supervisor = director
        if commit:
            user.save()
        return user


class UserCreateForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = (
            "first_name", "last_name", "employee_id", "email", "mobile",
            "designation", "division", "role", "joining_date", "profile_photo", "is_active",
        )
        widgets = {"joining_date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, manager=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.manager = manager
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
        if manager and manager.is_director and manager.division:
            self.fields["division"].queryset = self.fields["division"].queryset.filter(pk=manager.division_id)
            self.fields["division"].initial = manager.division
            excluded = Q(code="super-admin") | Q(is_division_director=True)
            if manager.division.code != "IT":
                excluded |= Q(code="senior-it-consultant")
            self.fields["role"].queryset = Role.objects.exclude(excluded)
        elif manager and manager.is_senior_it:
            self.fields["division"].queryset = self.fields["division"].queryset.filter(code="IT")
            self.fields["division"].initial = manager.division
            self.fields["role"].queryset = Role.objects.filter(
                Q(code="officer") | Q(name="Junior IT Consultant"),
            )
            self.fields["role"].initial = self.fields["role"].queryset.first()

    def clean_division(self):
        division = self.cleaned_data.get("division")
        if self.manager and self.manager.is_director and division != self.manager.division:
            raise forms.ValidationError("Directors can only create users in their own division.")
        if self.manager and self.manager.is_senior_it and getattr(division, "code", None) != "IT":
            raise forms.ValidationError("Senior IT Consultants can only create IT Officer accounts.")
        return division

    def clean_role(self):
        role = self.cleaned_data.get("role")
        if self.manager and self.manager.is_director and role:
            if (
                role.code == "super-admin"
                or role.is_division_director
                or (role.code == "senior-it-consultant" and self.manager.division.code != "IT")
            ):
                raise forms.ValidationError("Directors can only assign permitted subordinate roles.")
        if self.manager and self.manager.is_senior_it and role and role.name not in {"Officer", "Junior IT Consultant"} and role.code != "officer":
            raise forms.ValidationError("Senior IT Consultants can only create Officer-role accounts.")
        return role

    def save(self, commit=True):
        user = super().save(commit=False)
        user.username = user.email.lower()
        user.created_by = self.manager
        if self.manager and (self.manager.is_director or self.manager.is_senior_it):
            user.supervisor = self.manager
        if commit:
            user.save()
        return user


class UserEditForm(forms.ModelForm):
    new_password1 = forms.CharField(required=False, label="New password", widget=forms.PasswordInput)
    new_password2 = forms.CharField(required=False, label="Confirm new password", widget=forms.PasswordInput)

    class Meta:
        model = User
        fields = (
            "first_name", "last_name", "employee_id", "email", "mobile", "designation",
            "division", "role", "joining_date", "profile_photo", "is_active",
        )
        widgets = {"joining_date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, manager=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.manager = manager
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
        if manager and manager.is_director:
            self.fields["division"].queryset = self.fields["division"].queryset.filter(pk=manager.division_id)
            excluded = Q(code="super-admin") | Q(is_division_director=True)
            if manager.division.code != "IT":
                excluded |= Q(code="senior-it-consultant")
            self.fields["role"].queryset = Role.objects.exclude(excluded)
        elif manager and manager.is_senior_it:
            self.fields["division"].queryset = self.fields["division"].queryset.filter(code="IT")
            self.fields["role"].queryset = Role.objects.filter(
                Q(code="officer") | Q(name="Junior IT Consultant"),
            )

    def clean(self):
        cleaned = super().clean()
        role, division = cleaned.get("role"), cleaned.get("division")
        if self.manager and self.manager.is_director:
            if division != self.manager.division:
                self.add_error("division", "You can only manage users in your division.")
            if role and (
                role.code == "super-admin"
                or role.is_division_director
                or (role.code == "senior-it-consultant" and self.manager.division.code != "IT")
            ):
                self.add_error("role", "That role is outside your management scope.")
        if self.manager and self.manager.is_senior_it:
            if getattr(division, "code", None) != "IT" or not role or (
                role.code != "officer" and role.name != "Junior IT Consultant"
            ):
                raise forms.ValidationError("Senior IT Consultants can only edit IT Officer accounts.")
        password1, password2 = cleaned.get("new_password1"), cleaned.get("new_password2")
        if password1 or password2:
            if password1 != password2:
                self.add_error("new_password2", "The passwords do not match.")
            elif password1:
                validate_password(password1, self.instance)
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.username = user.email.lower()
        if self.cleaned_data.get("new_password1"):
            user.set_password(self.cleaned_data["new_password1"])
        if commit:
            user.save()
        return user


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("first_name", "last_name", "mobile", "profile_photo")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")


class TicketIntakeRouteForm(forms.ModelForm):
    class Meta:
        model = TicketIntakeRoute
        fields = ("selected_user",)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["selected_user"].queryset = User.objects.filter(
            is_active=True,
        ).filter(
            Q(division__code="IT") | Q(division__name__iexact="IT"),
        ).exclude(role__is_division_director=True).select_related(
            "division", "role",
        ).order_by("first_name", "last_name", "email")
        self.fields["selected_user"].label = "Route new tickets to"
        self.fields["selected_user"].help_text = "This user will receive new tickets and can review and assign them."
        self.fields["selected_user"].widget.attrs.setdefault("class", "form-control")

    def clean_selected_user(self):
        selected_user = self.cleaned_data["selected_user"]
        if not selected_user.is_active or not selected_user.is_it_user:
            raise forms.ValidationError("Choose an active user from the IT Division.")
        if selected_user.is_director:
            raise forms.ValidationError("Choose an IT user other than the Division Head.")
        return selected_user
