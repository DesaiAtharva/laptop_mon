from django.urls import path
from apps.billing.views import BillingOverviewView, BillingWebhookView, PlanListView

urlpatterns = [
    path("plans", PlanListView.as_view(), name="billing-plans"),
    path("overview", BillingOverviewView.as_view(), name="billing-overview"),
    path("webhook", BillingWebhookView.as_view(), name="billing-webhook"),
]
