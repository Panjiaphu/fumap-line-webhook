from django.contrib import admin

from .models import RateSourceStatus, RateSnapshot, SiteRateSettings


@admin.register(SiteRateSettings)
class SiteRateSettingsAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "api_enabled",
        "manual_mode",
        "manual_twd_vnd_rate",
        "updated_at",
    )
    fieldsets = (
        ("Source control", {"fields": ("name", "api_enabled", "manual_mode")}),
        (
            "Manual fallback prices",
            {
                "fields": (
                    "manual_twd_vnd_rate",
                    "manual_usdt_vnd_buy",
                    "manual_usdt_vnd_sell",
                    "manual_usdt_twd_buy",
                    "manual_usdt_twd_sell",
                )
            },
        ),
    )


@admin.register(RateSnapshot)
class RateSnapshotAdmin(admin.ModelAdmin):
    list_display = ("official_twd_vnd_rate", "provider_mode", "created_at")
    readonly_fields = ("raw_binance", "raw_maicoin", "calculation", "created_at")


@admin.register(RateSourceStatus)
class RateSourceStatusAdmin(admin.ModelAdmin):
    list_display = ("source", "ok", "last_checked_at")
    readonly_fields = ("last_checked_at",)

