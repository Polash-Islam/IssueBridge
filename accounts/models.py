from django.contrib.auth.models import AbstractUser, Permission
from django.db import models
from django.utils import timezone
from datetime import timedelta


def approval_expiry_time():
    return timezone.now() + timedelta(days=1)


class Role(models.Model):
    class Scope(models.TextChoices):
        GLOBAL = "GLOBAL", "Global"
        DIVISION = "DIVISION", "Division"
        OWN = "OWN", "Own records"

    name = models.CharField(max_length=80, unique=True)
    code = models.SlugField(max_length=50, unique=True)
    description = models.TextField(blank=True)
    scope = models.CharField(max_length=12, choices=Scope.choices, default=Scope.OWN)
    permissions = models.ManyToManyField(Permission, blank=True)
    is_system = models.BooleanField(default=False)
    is_division_director = models.BooleanField(
        default=False,
        help_text="Users with this role act as the head/director of their assigned division.",
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class User(AbstractUser):
    email = models.EmailField(unique=True)
    employee_id = models.CharField(max_length=40, unique=True, null=True, blank=True)
    mobile = models.CharField(max_length=30, blank=True)
    designation = models.CharField(max_length=120, blank=True)
    division = models.ForeignKey(
        "core.Division", on_delete=models.PROTECT, related_name="users", null=True, blank=True
    )
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="users", null=True, blank=True)
    profile_photo = models.ImageField(upload_to="profiles/%Y/%m/", blank=True)
    joining_date = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="created_users"
    )
    supervisor = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="direct_reports"
    )

    @property
    def full_name(self):
        return self.get_full_name() or self.username

    @property
    def role_code(self):
        if self.is_superuser:
            return "super-admin"
        return self.role.code if self.role else ""

    @property
    def is_super_admin(self):
        return self.is_superuser or self.role_code == "super-admin"

    @property
    def is_director(self):
        return bool(self.role_id and self.role.is_division_director)

    @property
    def is_senior_it(self):
        return self.role_code == "senior-it-consultant"

    @property
    def is_it_user(self):
        return bool(self.division and self.division.code == "IT")

    @property
    def can_manage_users(self):
        return self.is_super_admin or self.is_director or self.is_senior_it

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)

    def __str__(self):
        return self.full_name


class AccountApprovalRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="approval_request")
    division = models.ForeignKey("core.Division", on_delete=models.PROTECT, related_name="account_approval_requests")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True)
    requested_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(default=approval_expiry_time, db_index=True)
    reviewed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="reviewed_account_requests",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["expires_at"]
        indexes = [models.Index(fields=["status", "expires_at"])]

    @property
    def is_expired(self):
        return self.status == self.Status.PENDING and self.expires_at <= timezone.now()

    def __str__(self):
        return f"{self.user.email} — {self.get_status_display()}"
