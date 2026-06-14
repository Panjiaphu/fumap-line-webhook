from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.views import LoginView
from django.contrib import messages
from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.utils.translation import gettext as _

from .forms import RegistrationForm
from .models import RateSnapshot, RateSourceStatus
from .services import ExchangeRateEngine


class RememberMeLoginView(LoginView):
    template_name = "registration/login.html"

    def form_valid(self, form):
        remember_me = self.request.POST.get("remember_me")
        if remember_me:
            self.request.session.set_expiry(60 * 60 * 24 * 30)
        else:
            self.request.session.set_expiry(0)
        return super().form_valid(form)


def health_check(request):
    return JsonResponse({"ok": True, "service": "guilua"})


def home(request):
    snapshot = RateSnapshot.objects.first()
    if snapshot is None:
        try:
            snapshot = ExchangeRateEngine().latest_rate()
        except Exception:
            snapshot = None
    return render(request, "core/home.html", {"snapshot": snapshot})


def trade(request):
    return render(request, "core/simple_page.html", {"title": _("Trade"), "body": _("Trade workflow placeholder for the FX product.")})


def events(request):
    return render(request, "core/simple_page.html", {"title": _("Events"), "body": _("Event content will be adapted from reference projects later.")})


def shop(request):
    return render(request, "core/simple_page.html", {"title": _("Shop"), "body": _("Shop content will be designed around the GuiLua commercial experience.")})


@login_required
def member_dashboard(request):
    return render(request, "core/member_dashboard.html")


@user_passes_test(lambda user: user.is_staff)
def admin_dashboard(request):
    statuses = RateSourceStatus.objects.all()
    snapshots = RateSnapshot.objects.all()[:5]
    return render(request, "core/admin_dashboard.html", {"statuses": statuses, "snapshots": snapshots})


def register(request):
    if request.method == "POST":
        form = RegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            activation_url = request.build_absolute_uri(
                reverse(
                    "activate_account",
                    kwargs={
                        "uidb64": urlsafe_base64_encode(force_bytes(user.pk)),
                        "token": default_token_generator.make_token(user),
                    },
                )
            )
            send_mail(
                _("Confirm your GuiLua account"),
                _("Open this link to activate your account: %(url)s") % {"url": activation_url},
                settings.DEFAULT_FROM_EMAIL,
                [user.email],
                fail_silently=False,
            )
            messages.success(request, _("Registration received. Please confirm your email before signing in."))
            return redirect("login")
    else:
        form = RegistrationForm()
    return render(request, "registration/register.html", {"form": form})


def activate_account(request, uidb64, token):
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    if user is not None and default_token_generator.check_token(user, token):
        user.is_active = True
        user.save(update_fields=["is_active"])
        messages.success(request, _("Your account is active. You can sign in now."))
        return redirect("login")

    messages.error(request, _("Activation link is invalid or expired."))
    return redirect("register")
