from django.urls import path
from .views import dashboard, report_export, reports

urlpatterns = [
    path("", dashboard, name="dashboard"),
    path("reports/", reports, name="reports"),
    path("reports/export/<str:format>/", report_export, name="report_export"),
]
