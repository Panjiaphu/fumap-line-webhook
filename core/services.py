from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import logging

from django.conf import settings

from .models import RateSnapshot, RateSourceStatus, SiteRateSettings

logger = logging.getLogger(__name__)


@dataclass
class ProviderResult:
    ok: bool
    payload: dict
    error: str = ""


def decimal_or_none(value):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError):
        return None


class ExchangeRateEngine:
    """
    Business assumption:
    official TWD/VND = average Binance USDT/VND sell price / MaiCoin TWD/USDT buy price - 20.
    The "subtract 20" rule is explicit, but final rounding and spread policy still need owner confirmation.
    """

    subtract_before_publish = Decimal("20")

    def fetch_binance_usdt_vnd_sell(self):
        import requests

        body = {
            "asset": "USDT",
            "fiat": "VND",
            "tradeType": "SELL",
            "page": 1,
            "rows": 10,
            "payTypes": [],
        }
        try:
            response = requests.post(settings.BINANCE_P2P_API_URL, json=body, timeout=12)
            response.raise_for_status()
            payload = response.json()
            ads = payload.get("data", [])
            prices = [
                decimal_or_none(item.get("adv", {}).get("price"))
                for item in ads
            ]
            prices = [price for price in prices if price is not None]
            if not prices:
                raise ValueError("No Binance P2P prices returned")
            average = sum(prices) / Decimal(len(prices))
            return ProviderResult(True, {"average_sell_price": str(average), "offers": ads[:5]})
        except Exception as exc:
            logger.warning("Binance source failed: %s", exc)
            return ProviderResult(False, {}, str(exc))

    def fetch_maicoin_usdt_twd_buy(self):
        import requests

        try:
            response = requests.get(settings.MAICOIN_API_URL, timeout=12)
            response.raise_for_status()
            payload = response.json()
            ticker = payload.get("ticker", payload)
            buy_price = decimal_or_none(ticker.get("buy") or ticker.get("bid") or ticker.get("last"))
            sell_price = decimal_or_none(ticker.get("sell") or ticker.get("ask"))
            if buy_price is None:
                raise ValueError("No MaiCoin buy price returned")
            return ProviderResult(
                True,
                {
                    "buy_price": str(buy_price),
                    "sell_price": str(sell_price) if sell_price is not None else None,
                    "ticker": ticker,
                },
            )
        except Exception as exc:
            logger.warning("MaiCoin source failed: %s", exc)
            return ProviderResult(False, {}, str(exc))

    def calculate_official_rate(self, usdt_vnd_sell, usdt_twd_buy):
        intermediate = usdt_vnd_sell / usdt_twd_buy
        official = intermediate - self.subtract_before_publish
        return {
            "usdt_vnd_sell_average": str(usdt_vnd_sell),
            "usdt_twd_buy": str(usdt_twd_buy),
            "intermediate_twd_vnd": str(intermediate),
            "subtract_before_publish": str(self.subtract_before_publish),
            "official_twd_vnd": str(official),
        }

    def latest_rate(self):
        settings_obj, _ = SiteRateSettings.objects.get_or_create(name="default")
        if settings_obj.manual_mode or not settings_obj.api_enabled or settings.MANUAL_RATE_ENABLED:
            return self._manual_snapshot(settings_obj, "manual")

        binance = self.fetch_binance_usdt_vnd_sell()
        maicoin = self.fetch_maicoin_usdt_twd_buy()
        self._record_status("binance", binance)
        self._record_status("maicoin", maicoin)

        if binance.ok and maicoin.ok:
            usdt_vnd_sell = Decimal(binance.payload["average_sell_price"])
            usdt_twd_buy = Decimal(maicoin.payload["buy_price"])
            calculation = self.calculate_official_rate(usdt_vnd_sell, usdt_twd_buy)
            return RateSnapshot.objects.create(
                raw_binance=binance.payload,
                raw_maicoin=maicoin.payload,
                calculation=calculation,
                official_twd_vnd_rate=Decimal(calculation["official_twd_vnd"]),
                usdt_vnd_sell=usdt_vnd_sell,
                usdt_twd_buy=usdt_twd_buy,
                usdt_twd_sell=decimal_or_none(maicoin.payload.get("sell_price")),
                provider_mode="live",
            )

        return self._manual_snapshot(settings_obj, "manual_fallback")

    def _manual_snapshot(self, settings_obj, mode):
        return RateSnapshot.objects.create(
            raw_binance={},
            raw_maicoin={},
            calculation={"mode": mode, "assumption": "admin-entered manual prices"},
            official_twd_vnd_rate=settings_obj.manual_twd_vnd_rate,
            usdt_vnd_buy=settings_obj.manual_usdt_vnd_buy,
            usdt_vnd_sell=settings_obj.manual_usdt_vnd_sell,
            usdt_twd_buy=settings_obj.manual_usdt_twd_buy,
            usdt_twd_sell=settings_obj.manual_usdt_twd_sell,
            provider_mode=mode,
        )

    def _record_status(self, source, result):
        RateSourceStatus.objects.update_or_create(
            source=source,
            defaults={"ok": result.ok, "message": result.error},
        )

