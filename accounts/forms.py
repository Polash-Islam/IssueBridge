from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.password_validation import validate_password
from .models import Role, User


class OfficerRegistrationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = (
            "first_name", "last_name", "employee_id", "email", "mobile",
            "designation", "division", "profile_photo",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["division"].queryset = self.fields["division"].queryset.filter(is_active=True)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account already exists with this email address.")
        return email

    def clean_division(self):
        division = self.cleaned_data["division"]
        if not User.objects.filter(
            division=division, role__code="director", is_active=True,
        ).exists():
            raise forms.ValidationError("This division does not currently have an active Director to approve the account.")
        return division

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        user.username = user.email
        user.role = Role.objects.get(code="officer")
        user.is_active = False
        director = User.objects.filter(
            division=self.cleaned_data["division"], role__code="director", is_active=True,
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
            excluded = ["super-admin", "director"]
            if manager.division.code != "IT":
                excluded.append("senior-it-consultant")
            self.fields["role"].queryset = Role.objects.exclude(code__in=excluded)
        elif manager and manager.is_senior_it:
            self.fields["division"].queryset = self.fields["division"].queryset.filter(code="IT")
            self.fields["division"].initial = manager.division
            self.fields["role"].queryset = Role.objects.filter(code="officer")
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
            disallowed = {"super-admin", "director"}
            if self.manager.division.code != "IT":
                disallowed.add("senior-it-consultant")
            if role.code in disallowed:
                raise forms.ValidationError("Directors can only assign permitted subordinate roles.")
        if self.manager and self.manager.is_senior_it and role and role.code != "officer":
            raise forms.ValidationError("Senior IT Consultants can only create Officer-role accounts.")
        return role

    def save(self, commit=True):
        user = super().save(commit=False)
        user.username = user.email.lower()
        user.created_by = self.manager
        if self.manager and (self.manager.is_director or self.manager.is_senior_it):
            user.supervisor = self.manager
        if user.role and user.role.code == "director":
            user.designation = "Executive Director"
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
            excluded = ["super-admin", "director"]
            if manager.division.code != "IT":
                excluded.append("senior-it-consultant")
            self.fields["role"].queryset = Role.objects.exclude(code__in=excluded)
        elif manager and manager.is_senior_it:
            self.fields["division"].queryset = self.fields["division"].queryset.filter(code="IT")
            self.fields["role"].queryset = Role.objects.filter(code="officer")

    def clean(self):
        cleaned = super().clean()
        role, division = cleaned.get("role"), cleaned.get("division")
        if self.manager and self.manager.is_director:
            if division != self.manager.division:
                self.add_error("division", "You can only manage users in your division.")
            if role and (role.code in {"super-admin", "director"} or (role.code == "senior-it-consultant" and self.manager.division.code != "IT")):
                self.add_error("role", "That role is outside your management scope.")
        if self.manager and self.manager.is_senior_it:
            if getattr(division, "code", None) != "IT" or not role or role.code != "officer":
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
        if user.role and user.role.code == "director":
            user.designation = "Executive Director"
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
