"""Accounts / authentication URLs."""

from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.LoginView.as_view(), name="login"),
    path("refresh/", views.TokenRefreshCookieView.as_view(), name="refresh"),
    path("logout/", views.LogoutView.as_view(), name="logout"),
    path("me/", views.MeView.as_view(), name="me"),
    path("csrf/", views.CsrfTokenView.as_view(), name="csrf"),
]
