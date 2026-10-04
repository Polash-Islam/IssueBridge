from datetime import timedelta

from django.core.management import call_command
from django.db.models.deletion import ProtectedError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from communications.models import Notification
from core.models import Division
from .forms import OfficerRegistrationForm
from .models import AccountApprovalRequest, Role, User
from .services import purge_expired_account_requests


class RoleAdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(
            username="role-admin", email="role-admin@example.com", password="TestPassword2026!",
        )
        cls.division = Division.objects.create(name="Information Technology", code="IT")

    def setUp(self):
        self.client.force_login(self.admin)

    def test_admin_requires_division_when_creating_role(self):
        response = self.client.post(reverse("admin:accounts_role_add"), {
            "name": "IT Support", "code": "it-support", "scope": Role.Scope.OWN,
            "_save": "Save",
        })
        self.assertFormError(response.context["adminform"].form, "division", "This field is required.")
        self.assertFalse(Role.objects.filter(code="it-support").exists())

    def test_admin_creates_role_under_selected_division(self):
        response = self.client.post(reverse("admin:accounts_role_add"), {
            "name": "IT Support", "code": "it-support", "division": self.division.pk,
            "scope": Role.Scope.OWN, "_save": "Save",
        })
        self.assertRedirects(response, reverse("admin:accounts_role_changelist"))
        role = Role.objects.get(code="it-support")
        self.assertEqual(role.division, self.division)
        with self.assertRaises(ProtectedError):
            self.division.delete()

    def test_admin_can_filter_roles_by_division(self):
        role = Role.objects.create(name="IT Support", code="it-support", division=self.division)
        other_division = Division.objects.create(name="Audit Practice Review", code="APR")
        Role.objects.create(name="APR Support", code="apr-support", division=other_division)
        response = self.client.get(reverse("admin:accounts_role_changelist"), {
            "division__id__exact": self.division.pk,
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["cl"].result_list), [role])

    def test_admin_allows_same_role_name_and_code_in_different_divisions(self):
        Role.objects.create(name="Administrative Officer", code="administrative-officer", division=self.division)
        other_division = Division.objects.create(name="Financial Reporting Monitoring", code="FRM")
        response = self.client.post(reverse("admin:accounts_role_add"), {
            "name": "Administrative Officer", "code": "administrative-officer",
            "division": other_division.pk, "scope": Role.Scope.OWN, "_save": "Save",
        })
        self.assertRedirects(response, reverse("admin:accounts_role_changelist"))
        self.assertEqual(Role.objects.filter(code="administrative-officer").count(), 2)

    def test_admin_rejects_duplicate_name_or_code_in_same_division(self):
        Role.objects.create(name="Administrative Officer", code="administrative-officer", division=self.division)
        for name, code in [("Administrative Officer", "another-code"), ("Another Name", "administrative-officer")]:
            with self.subTest(name=name, code=code):
                response = self.client.post(reverse("admin:accounts_role_add"), {
                    "name": name, "code": code, "division": self.division.pk,
                    "scope": Role.Scope.OWN, "_save": "Save",
                })
                self.assertTrue(response.context["adminform"].form.non_field_errors())
        self.assertEqual(Role.objects.filter(division=self.division).count(), 1)

    def test_existing_shared_role_can_be_assigned_to_division(self):
        role = Role.objects.create(name="Legacy Support", code="legacy-support")
        response = self.client.post(reverse("admin:accounts_role_change", args=[role.pk]), {
            "name": role.name, "code": role.code, "division": self.division.pk,
            "scope": role.scope, "_save": "Save",
        })
        self.assertRedirects(response, reverse("admin:accounts_role_changelist"))
        role.refresh_from_db()
        self.assertEqual(role.division, self.division)


class AccountManagementTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", with_demo_data=True, verbosity=0)
        cls.consultant = User.objects.get(email="consultant@frc.gov.bd")
        cls.it_officer = User.objects.get(email="it.officer@frc.gov.bd")
        cls.it_director = User.objects.get(email="it.director@frc.gov.bd")
        cls.apr_director = User.objects.get(email="apr.director@frc.gov.bd")

    def _creation_data(self, **overrides):
        data = {
            "first_name": "New", "last_name": "Officer", "employee_id": "FRC-2200",
            "email": "new.officer@frc.gov.bd", "mobile": "01700000000",
            "designation": "IT Officer", "division": Division.objects.get(code="IT").pk,
            "role": Role.objects.get(code="officer").pk, "is_active": "on",
            "password1": "StrongTestPass2026!", "password2": "StrongTestPass2026!",
        }
        data.update(overrides)
        return data

    def test_senior_it_can_create_only_it_officers(self):
        self.client.force_login(self.consultant)
        response = self.client.post(reverse("user_create"), self._creation_data())
        self.assertRedirects(response, reverse("user_list"))
        created = User.objects.get(email="new.officer@frc.gov.bd")
        self.assertEqual(created.division.code, "IT")
        self.assertEqual(created.role_code, "officer")
        self.assertEqual(created.supervisor, self.consultant)

        response = self.client.post(reverse("user_create"), self._creation_data(
            email="blocked@frc.gov.bd", employee_id="FRC-2201",
            role=Role.objects.get(code="senior-it-consultant").pk,
        ))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(email="blocked@frc.gov.bd").exists())

    def test_senior_it_cannot_edit_non_it_officer(self):
        self.client.force_login(self.consultant)
        response = self.client.get(reverse("user_edit", args=[self.apr_director.pk]))
        self.assertEqual(response.status_code, 403)

    def test_it_director_can_create_senior_it_consultant(self):
        self.client.force_login(self.it_director)
        response = self.client.post(reverse("user_create"), self._creation_data(
            first_name="Senior", last_name="Consultant", email="senior.two@frc.gov.bd",
            employee_id="FRC-2202", designation="Senior IT Consultant",
            role=Role.objects.get(code="senior-it-consultant").pk,
        ))
        self.assertRedirects(response, reverse("user_list"))
        created = User.objects.get(email="senior.two@frc.gov.bd")
        self.assertEqual(created.supervisor, self.it_director)
        self.assertEqual(created.role_code, "senior-it-consultant")

    def test_director_can_keep_a_specific_designation(self):
        self.apr_director.designation = "Changed manually"
        self.apr_director.save()
        self.apr_director.refresh_from_db()
        self.assertEqual(self.apr_director.designation, "Changed manually")

    def test_each_user_can_view_and_edit_own_profile(self):
        self.client.force_login(self.it_officer)
        self.assertEqual(self.client.get(reverse("profile")).status_code, 200)
        response = self.client.post(reverse("profile_edit"), {
            "first_name": "Arif", "last_name": "Hasan", "mobile": "01812345678",
        })
        self.assertRedirects(response, reverse("profile"))
        self.it_officer.refresh_from_db()
        self.assertEqual(self.it_officer.mobile, "01812345678")


class OfficerSelfRegistrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("seed_demo", with_demo_data=True, verbosity=0)
        cls.apr = Division.objects.get(code="APR")
        cls.apr_director = User.objects.get(email="apr.director@frc.gov.bd")
        cls.frm_director = User.objects.create_user(
            username="frm.director.test@frc.gov.bd", email="frm.director.test@frc.gov.bd",
            password="StrongTestPass2026!", first_name="FRM", last_name="Director",
            division=Division.objects.get(code="FRM"), role=Role.objects.get(code="director"),
        )

    def registration_data(self, **overrides):
        data = {
            "first_name": "New", "last_name": "APR Officer", "employee_id": "SELF-1001",
            "email": "self.registered@frc.gov.bd", "mobile": "01700000001",
            "designation": "Admin Officer", "division": self.apr.pk,
            "password1": "StrongSelfPass2026!", "password2": "StrongSelfPass2026!",
        }
        data.update(overrides)
        return data

    def create_pending_account(self):
        response = self.client.post(reverse("register"), self.registration_data())
        self.assertRedirects(response, reverse("registration_pending"))
        user = User.objects.get(email="self.registered@frc.gov.bd")
        return user, user.approval_request

    def test_registration_orders_division_before_designation(self):
        response = self.client.get(reverse("register"))
        fields = list(response.context["form"].fields)
        self.assertEqual(fields[fields.index("mobile") + 1:fields.index("mobile") + 3],
                         ["division", "designation"])
        self.assertContains(response, 'id="registration-designation-roles"')
        self.assertContains(response, 'js/registration.js')

    def test_registration_rejects_designation_from_another_division(self):
        response = self.client.post(
            reverse("register"), self.registration_data(designation="Junior IT Consultant")
        )
        self.assertIn("designation", response.context["form"].errors)
        self.assertFalse(User.objects.filter(email="self.registered@frc.gov.bd").exists())

    def test_registration_allows_admin_officer_for_every_division(self):
        response = self.client.post(reverse("register"), self.registration_data())
        self.assertRedirects(response, reverse("registration_pending"))
        user = User.objects.get(email="self.registered@frc.gov.bd")
        self.assertEqual(user.designation, "Admin Officer")
        self.assertEqual(user.role_code, "officer")

    def test_it_division_has_multiple_safe_designations(self):
        form = OfficerRegistrationForm(initial={"division": Division.objects.get(code="IT")})
        values = {value for value, label in form.fields["designation"].choices}
        self.assertTrue({
            "Admin Officer", "Junior IT Consultant", "Senior IT Consultant", "Intern",
        }.issubset(values))

    def test_registration_rejects_free_text_and_blank_designation(self):
        for designation in ["Arbitrary designation", ""]:
            with self.subTest(designation=designation):
                response = self.client.post(reverse("register"), self.registration_data(designation=designation))
                self.assertIn("designation", response.context["form"].errors)
                self.assertFalse(User.objects.filter(email="self.registered@frc.gov.bd").exists())

    def test_registration_preserves_designation_when_other_field_is_invalid(self):
        response = self.client.post(reverse("register"), self.registration_data(password2="mismatch"))
        form = response.context["form"]
        self.assertIn("password2", form.errors)
        self.assertNotIn("designation", form.errors)
        self.assertEqual(form["designation"].value(), "Admin Officer")

    def test_registration_requires_division(self):
        response = self.client.post(reverse("register"), self.registration_data(division=""))
        self.assertIn("division", response.context["form"].errors)
        self.assertFalse(User.objects.filter(email="self.registered@frc.gov.bd").exists())

    def test_login_page_uses_frc_logo_and_registration_link(self):
        response = self.client.get(reverse("login"))
        self.assertContains(response, "/media/FRC_Logo.png")
        self.assertContains(response, reverse("register"))
        self.assertNotContains(response, "APR Software access review")

    def test_registration_creates_inactive_officer_and_notifies_division_director(self):
        user, approval = self.create_pending_account()
        self.assertFalse(user.is_active)
        self.assertEqual(user.role_code, "officer")
        self.assertEqual(user.designation, "Admin Officer")
        self.assertEqual(approval.division, self.apr)
        approval_window = approval.expires_at - approval.requested_at
        self.assertGreaterEqual(approval_window, timedelta(hours=23, minutes=59))
        self.assertLessEqual(approval_window, timedelta(days=1, minutes=1))
        self.assertFalse(self.client.login(username=user.email, password="StrongSelfPass2026!"))
        self.assertTrue(Notification.objects.filter(
            recipient=self.apr_director, approval_request=approval,
            kind=Notification.Kind.ACCOUNT_APPROVAL,
        ).exists())

    def test_registration_uses_officer_role_from_selected_division(self):
        officer = Role.objects.create(name="Officer", code="officer", division=self.apr)
        Role.objects.create(name="Officer", code="officer", division=Division.objects.get(code="FRM"))
        user, _ = self.create_pending_account()
        self.assertEqual(user.role, officer)

    def test_custom_named_head_role_is_detected_as_director(self):
        custom_role = Role.objects.create(
            name="Custom Division Head", code="custom-division-head",
            scope=Role.Scope.DIVISION, is_division_director=True,
        )
        self.apr_director.role = custom_role
        self.apr_director.designation = "ED APR"
        self.apr_director.save()

        user, approval = self.create_pending_account()

        self.assertEqual(user.supervisor, self.apr_director)
        self.assertTrue(Notification.objects.filter(
            recipient=self.apr_director, approval_request=approval,
            kind=Notification.Kind.ACCOUNT_APPROVAL,
        ).exists())

    def test_matching_director_can_approve_and_enable_login(self):
        user, approval = self.create_pending_account()
        self.client.force_login(self.apr_director)
        response = self.client.post(reverse("account_approve", args=[approval.pk]))
        self.assertRedirects(response, reverse("account_approval_list"))
        user.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertEqual(user.supervisor, self.apr_director)
        self.client.logout()
        self.assertTrue(self.client.login(username=user.email, password="StrongSelfPass2026!"))

    def test_other_division_director_cannot_approve(self):
        _, approval = self.create_pending_account()
        self.client.force_login(self.frm_director)
        self.assertEqual(
            self.client.post(reverse("account_approve", args=[approval.pk])).status_code, 403,
        )

    def test_expired_pending_account_is_deleted(self):
        user, approval = self.create_pending_account()
        approval.expires_at = timezone.now() - timedelta(seconds=1)
        approval.save(update_fields=["expires_at"])
        self.assertEqual(purge_expired_account_requests(), 1)
        self.assertFalse(User.objects.filter(pk=user.pk).exists())
