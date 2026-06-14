from django.conf.urls.i18n import i18n_patterns
from django.contrib import admin
from django.urls import include, path

from core import views


urlpatterns = [
    path("i18n/", include("django.conf.urls.i18n")),
    path("health/", views.health_check, name="health_check"),
]

urlpatterns += i18n_patterns(
    path("", views.home, name="home"),
    path("trade/", views.trade, name="trade"),
    path("events/", views.events, name="events"),
    path("shop/", views.shop, name="shop"),
    path("dashboard/", views.member_dashboard, name="member_dashboard"),
    path("admin-dashboard/", views.admin_dashboard, name="admin_dashboard"),
    path("accounts/login/", views.RememberMeLoginView.as_view(), name="login"),
    path("accounts/", include("django.contrib.auth.urls")),
    path("accounts/register/", views.register, name="register"),
    path("accounts/activate/<uidb64>/<token>/", views.activate_account, name="activate_account"),
    path("admin/", admin.site.urls),
    prefix_default_language=False,
)
