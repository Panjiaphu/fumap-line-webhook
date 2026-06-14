from django.db import models


class SiteRateSettings(models.Model):
    name = models.CharField(max_length=80, default="default", unique=True)
    api_enabled = models.BooleanField(default=True)
    manual_mode = models.BooleanField(default=False)
    manual_twd_vnd_rate = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    manual_usdt_vnd_buy = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    manual_usdt_vnd_sell = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    manual_usdt_twd_buy = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    manual_usdt_twd_sell = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "site rate setting"
        verbose_name_plural = "site rate settings"

    def __str__(self):
        return self.name


class RateSnapshot(models.Model):
    raw_binance = models.JSONField(default=dict, blank=True)
    raw_maicoin = models.JSONField(default=dict, blank=True)
    calculation = models.JSONField(default=dict, blank=True)
    official_twd_vnd_rate = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    usdt_vnd_buy = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    usdt_vnd_sell = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    usdt_twd_buy = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    usdt_twd_sell = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    provider_mode = models.CharField(max_length=40, default="live_with_manual_fallback")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class RateSourceStatus(models.Model):
    source = models.CharField(max_length=40, unique=True)
    ok = models.BooleanField(default=False)
    message = models.TextField(blank=True)
    last_checked_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "rate source status"
        verbose_name_plural = "rate source statuses"

    def __str__(self):
        return self.source

