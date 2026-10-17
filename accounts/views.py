from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth import logout, update_session_auth_hash
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import OfficerRegistrationForm, ProfileForm, TicketIntakeRouteForm, UserCreateForm, UserEditForm
from .models import AccountApprovalRequest, User
from .services import approve_account_request, can_review_account_request, purge_expired_account_requests
from tickets.models import TicketIntakeRoute


@require_POST
def logout_user(request):
    
    logout(request)
    return redirect("login")


@transaction.atomic
def register(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = OfficerRegistrationForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        approval_request = AccountApprovalRequest.objects.create(user=user, division=user.division)
        from communications.models import Notification
        from communications.services import notify_users
        directors = User.objects.filter(
            division=user.division, role__is_division_director=True, is_active=True,
        )
        approvers = directors
        if not directors.exists():
            approvers = User.objects.filter(is_active=True).filter(
                Q(is_superuser=True) | Q(role__code="super-admin"),
            )
        notify_users(
            approvers, kind=Notification.Kind.ACCOUNT_APPROVAL,
            verb=f"requested a {user.role.name} account for {user.division.code}",
            approval_request=approval_request,
        )
        request.session["registration_submitted"] = {
            "email": user.email,
            "division": user.division.name,
            "role": user.role.name,
            "expires_at": timezone.localtime(approval_request.expires_at).isoformat(),
        }
        return redirect("registration_pending")
    return render(request, "registration/register.html", {"form": form})


def registration_pending(request):
    submitted = request.session.get("registration_submitted")
    if not submitted:
        return redirect("register")
    return render(request, "registration/registration_pending.html", {"submitted": submitted})


def _require_manager(user):
    if not user.can_manage_users:
        raise PermissionDenied


def _can_manage_target(manager, target):
    if manager.is_super_admin:
        return True
    if manager.is_director:
        if target.division_id != manager.division_id or target.is_super_admin or target.is_director:
            return False
        if target.role_code == "senior-it-consultant" and manager.division.code != "IT":
            return False
        return True
    if manager.is_senior_it:
        return target.division and target.division.code == "IT" and target.role_code == "officer"
    return False


@login_required
def user_list(request):
    purge_expired_account_requests()
    _require_manager(request.user)
    users = User.objects.select_related("division", "role", "supervisor").exclude(
        approval_request__status=AccountApprovalRequest.Status.PENDING,
    ).order_by("division__code", "first_name")
    if request.user.is_director:
        users = users.filter(division=request.user.division).exclude(
            role__is_division_director=True,
        ).exclude(role__code="super-admin")
    elif request.user.is_senior_it:
        users = users.filter(division__code="IT").filter(
            Q(role__code="officer") | Q(role__name="Junior IT Consultant"),
        )
    q = request.GET.get("q", "").strip()
    if q:
        users = users.filter(Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(email__icontains=q) | Q(employee_id__icontains=q))
    approvals = AccountApprovalRequest.objects.none()
    if request.user.is_super_admin:
        approvals = AccountApprovalRequest.objects.filter(status=AccountApprovalRequest.Status.PENDING)
    elif request.user.is_director:
        approvals = AccountApprovalRequest.objects.filter(
            status=AccountApprovalRequest.Status.PENDING, division=request.user.division,
        )
    approvals = approvals.select_related("user", "division").order_by("expires_at")
    return render(request, "accounts/user_list.html", {"users": users, "q": q, "approvals": approvals})


@login_required
def account_approval_list(request):
    if not (request.user.is_super_admin or request.user.is_director):
        raise PermissionDenied
    purge_expired_account_requests()
    approvals = AccountApprovalRequest.objects.filter(status=AccountApprovalRequest.Status.PENDING)
    if request.user.is_director and not request.user.is_super_admin:
        approvals = approvals.filter(division=request.user.division)
    return render(request, "accounts/account_approval_list.html", {
        "approvals": approvals.select_related("user", "division").order_by("expires_at"),
    })


@login_required
def account_approve(request, pk):
    if request.method != "POST":
        raise PermissionDenied
    approval_request = get_object_or_404(
        AccountApprovalRequest.objects.select_related("user", "division"), pk=pk,
    )
    if not can_review_account_request(request.user, approval_request):
        raise PermissionDenied
    applicant = approval_request.user
    approved = approve_account_request(approval_request=approval_request, actor=request.user)
    if approved is None:
        messages.error(request, "The one-day approval window expired and the pending account was removed.")
    else:
        from communications.models import Notification
        from communications.services import notify_users
        notify_users(
            [applicant], kind=Notification.Kind.ACCOUNT_APPROVAL,
            verb=f"approved your {applicant.role.name} account", actor=request.user, approval_request=approved,
        )
        messages.success(request, f"{applicant.full_name}'s {applicant.role.name} account was approved and can now sign in.")
    return redirect("account_approval_list")


@login_required
def user_create(request):
    _require_manager(request.user)
    form = UserCreateForm(request.POST or None, request.FILES or None, manager=request.user)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        messages.success(request, f"{user.full_name} was added successfully.")
        return redirect("user_list")
    return render(request, "accounts/user_form.html", {"form": form})


@login_required
def user_edit(request, pk):
    _require_manager(request.user)
    target = get_object_or_404(User.objects.select_related("division", "role"), pk=pk)
    if not _can_manage_target(request.user, target):
        raise PermissionDenied
    form = UserEditForm(request.POST or None, request.FILES or None, instance=target, manager=request.user)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        messages.success(request, f"{user.full_name}'s account was updated.")
        return redirect("user_list")
    return render(request, "accounts/user_edit.html", {"form": form, "target": target})


@login_required
def ticket_intake_routing(request):
    if not (request.user.is_super_admin or (request.user.is_director and request.user.is_it_user)):
        raise PermissionDenied
    from core.models import Division
    division = get_object_or_404(Division, code="IT")
    route = TicketIntakeRoute.objects.filter(division=division).first()
    form = TicketIntakeRouteForm(request.POST or None, instance=route)
    if request.method == "POST" and form.is_valid():
        route = form.save(commit=False)
        route.division = division
        route.updated_by = request.user
        route.save()
        form.save_m2m()
        routed_names = ", ".join(
            user.full_name for user in route.selected_users.order_by("first_name", "last_name")
        )
        messages.success(request, f"New tickets will be routed to {routed_names}.")
        return redirect("ticket_intake_routing")
    return render(request, "accounts/ticket_intake_routing.html", {"form": form, "route": route})


@login_required
@require_POST
def ticket_intake_routing_remove_user(request, user_id):
    if not (request.user.is_super_admin or (request.user.is_director and request.user.is_it_user)):
        raise PermissionDenied
    from core.models import Division
    division = get_object_or_404(Division, code="IT")
    route = get_object_or_404(TicketIntakeRoute, division=division)
    selected_user = get_object_or_404(route.selected_users, pk=user_id)
    route.selected_users.remove(selected_user)
    messages.success(request, f"{selected_user.full_name} was removed from ticket routing.")
    return redirect("ticket_intake_routing")


@login_required
def profile(request):
    return render(request, "accounts/profile.html", {"profile_user": request.user})


@login_required
def profile_edit(request):
    form = ProfileForm(request.POST or None, request.FILES or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Your profile was updated.")
        return redirect("profile")
    return render(request, "accounts/profile_edit.html", {"form": form})


@login_required
def password_change(request):
    form = PasswordChangeForm(request.user, request.POST or None)
    for field in form.fields.values():
        field.widget.attrs.setdefault("class", "form-control")
    if request.method == "POST" and form.is_valid():
        user = form.save()
        update_session_auth_hash(request, user)
        messages.success(request, "Your password was changed successfully.")
        return redirect("profile")
    return render(request, "accounts/password_change.html", {"form": form})
