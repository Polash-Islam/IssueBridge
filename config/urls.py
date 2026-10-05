from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from django.templatetags.static import static as static_url
from django.views.generic import RedirectView
from accounts import views as account_views


urlpatterns = [
    path("favicon.ico", RedirectView.as_view(url=static_url("favicon.svg"))),
    path("admin/", admin.site.urls),
    path(
        "login/",
        auth_views.LoginView.as_view(template_name="registration/login.html", redirect_authenticated_user=True),
        name="login",
    ),
    path("logout/", account_views.logout_user, name="logout"),
    path("register/", account_views.register, name="register"),
    path("register/pending/", account_views.registration_pending, name="registration_pending"),
    path("", include("dashboard.urls")),
    path("tickets/", include("tickets.urls")),
    path("workspace/", include("communications.urls")),
    path("users/", include("accounts.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
