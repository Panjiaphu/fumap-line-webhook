from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="RateSnapshot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("raw_binance", models.JSONField(blank=True, default=dict)),
                ("raw_maicoin", models.JSONField(blank=True, default=dict)),
                ("calculation", models.JSONField(blank=True, default=dict)),
                ("official_twd_vnd_rate", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ("usdt_vnd_buy", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ("usdt_vnd_sell", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ("usdt_twd_buy", models.DecimalField(blank=True, decimal_places=4, max_digits=12, null=True)),
                ("usdt_twd_sell", models.DecimalField(blank=True, decimal_places=4, max_digits=12, null=True)),
                ("provider_mode", models.CharField(default="live_with_manual_fallback", max_length=40)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="RateSourceStatus",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("source", models.CharField(max_length=40, unique=True)),
                ("ok", models.BooleanField(default=False)),
                ("message", models.TextField(blank=True)),
                ("last_checked_at", models.DateTimeField(auto_now=True)),
            ],
            options={"verbose_name": "rate source status", "verbose_name_plural": "rate source statuses"},
        ),
        migrations.CreateModel(
            name="SiteRateSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(default="default", max_length=80, unique=True)),
                ("api_enabled", models.BooleanField(default=True)),
                ("manual_mode", models.BooleanField(default=False)),
                ("manual_twd_vnd_rate", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ("manual_usdt_vnd_buy", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ("manual_usdt_vnd_sell", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ("manual_usdt_twd_buy", models.DecimalField(blank=True, decimal_places=4, max_digits=12, null=True)),
                ("manual_usdt_twd_sell", models.DecimalField(blank=True, decimal_places=4, max_digits=12, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"verbose_name": "site rate setting", "verbose_name_plural": "site rate settings"},
        ),
    ]

