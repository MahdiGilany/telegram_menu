#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# asll_pay_menu.py — fixed order flow using BaseMessage callbacks (not callables)
#
# NOTE:
# - This version aligns with the framework’s expected callback types:
#   for buttons that should open a new UI, the callback is a BaseMessage INSTANCE
#   (not a method). See models.py and navigation.py for how callbacks are handled.
#   :contentReference[oaicite:0]{index=0}  :contentReference[oaicite:1]{index=1}
#
# - "🛒 سفارش" now opens either:
#     • an inline amount/region selector (for items needing a user amount/option), or
#     • a final inline order summary (for fixed-price items).
#
# - For percent-based services (مثل Apple/Google gift) قیمت = مبلغ انتخابی + درصد.
#   برای PlayStation: US ~5% زیر قیمت اسمی، سایر ریجن‌ها ~5% بالاتر.
#   برای Prepaid (Visa/Master): کارمزد پلّه‌ای ۵٪..۱۰٪ روی مبلغ انتخابی.
#
# - پس از انتخاب، یک پیام خلاصه سفارش (inline) نشان می‌دهد:
#   مبلغ نهایی دلاری + شماره‌حساب پرداخت + یادآوری ارسال رسید به @asll_pay
#
# - شماره حساب از متغیر محیطی ASLLPAY_ACCOUNT_NO خوانده می‌شود (پیش‌فرض: "—").
#
# - برای افزودن موارد جدید، فقط PRICING و منوها را آپدیت کنید.

import os
import datetime
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from telegram import ReplyKeyboardMarkup

from telegram.ext._callbackcontext import CallbackContext
from telegram.ext._utils.types import BD, BT, CD, UD

from telegram_menu import BaseMessage, MenuButton, ButtonType
from telegram_menu import NavigationHandler as _BaseNav  # type: ignore

ROOT_FOLDER = Path(__file__).parent

# ========= App Config =========
ADMIN_USER = "@asll_pay"
ACCOUNT_NO = os.getenv("ASLLPAY_ACCOUNT_NO", "—")

# ========= Pricing =========
# strategy.type ∈ {"fixed","percent","psn_region","prepaid_tier","quote_needed"}
PRICING: Dict[str, Dict[str, Any]] = {
    # Gift Cards
    "apple_gift":   {"type": "percent", "percent": 5.0},
    "google_play":  {"type": "percent", "percent": 5.0},
    "playstation":  {"type": "psn_region"},
    "prepaid_card": {"type": "prepaid_tier"},
    # Accounts / Fixed
    "paypal":       {"type": "fixed", "amount": 40.0},
    "mastercard":   {"type": "fixed", "amount": 130.0},
    # Others require quote
    "wirex":        {"type": "quote_needed"},
    "wise":         {"type": "quote_needed"},
    "university_fee": {"type": "quote_needed"},
    "saas_purchase":  {"type": "quote_needed"},
    "flight_hotel":   {"type": "quote_needed"},
    "fx_to_rial":     {"type": "quote_needed"},
}

COMMON_DENOMS_SMALL = [5, 10, 15, 20, 25, 30, 40, 50, 75, 100]
PREPAID_DENOMS = [1, 5, 10, 15, 20, 25, 30, 40, 50, 75, 100, 150, 200, 250]


def _fmt_usd(amount: float) -> str:
    return f"${amount:,.2f}"


def _calc_percent(amount: float, pct: float) -> float:
    return round(amount * (1.0 + pct / 100.0), 2)


def _calc_discount(amount: float, pct: float) -> float:
    return round(amount * (1.0 - pct / 100.0), 2)


def _prepaid_tier(amount: float) -> float:
    """Tier:
      <=20 → +10%
      <=50 → +9%
      <=100 → +8%
      <=200 → +6%
      >200 → +5%
    """
    if amount <= 20:
        pct = 10.0
    elif amount <= 50:
        pct = 9.0
    elif amount <= 100:
        pct = 8.0
    elif amount <= 200:
        pct = 6.0
    else:
        pct = 5.0
    return _calc_percent(amount, pct)


def compute_total(service_key: str, base_amount: Optional[float] = None, region: Optional[str] = None) -> Tuple[Optional[float], str]:
    """Return (price_usd, note). If price_usd is None => quote needed."""
    strat = PRICING.get(service_key, {"type": "quote_needed"})
    t = strat["type"]

    if t == "fixed":
        return float(strat["amount"]), "قیمت ثابت"

    if t == "percent":
        if base_amount is None:
            return None, "برای محاسبه قیمت، مبلغ دلاری لازم است."
        pct = float(strat["percent"])
        return _calc_percent(base_amount, pct), f"{pct}٪ کارمزد"

    if t == "psn_region":
        if base_amount is None:
            return None, "برای محاسبه، مبلغ گیفت لازم است."
        # US cheaper ~5%, others +5%
        if (region or "").lower() in ["us", "usa", "america", "united states", "🇺🇸", "امریکا", "آمریکا"]:
            return _calc_discount(base_amount, 5.0), "ریجن آمریکا ~۵٪ زیر قیمت اسمی"
        else:
            return _calc_percent(base_amount, 5.0), "سایر ریجن‌ها ~۵٪ بالاتر از اسمی"

    if t == "prepaid_tier":
        if base_amount is None:
            return None, "برای محاسبه، مبلغ شارژ لازم است."
        return _prepaid_tier(base_amount), "کارمزد پلّه‌ای ۵٪ تا ۱۰٪"

    return None, "نیاز به استعلام قیمت"


# ========= Messages =========
class MyNavigationHandler(_BaseNav):
    """Optional extension if needed; kept for symmetry with the user's codebase."""
    async def goto_back(self) -> int:
        return await self.select_menu_button("Back")


class OrderSummaryMessage(BaseMessage):
    """Inline final summary (inlined=True so it appears as an app message)."""
    def __init__(
        self,
        navigation: MyNavigationHandler,
        title: str,
        price_usd: Optional[float],
        note: str,
        service_key: str,
        base_amount: Optional[float] = None,
        extra: Optional[str] = None,
    ):
        super().__init__(navigation, label=f"order_summary:{service_key}", inlined=True, notification=True)
        self.title = title
        self.price_usd = price_usd
        self.note = note
        self.service_key = service_key
        self.base_amount = base_amount
        self.extra = extra

        # Inline summary: keep it simple, no navigation changes required here.
        # (Inline messages are handled by app_message_button_callback)
        self.keyboard = [[]]  # no buttons

    def update(self, context: Optional[CallbackContext[BT, UD, CD, BD]] = None) -> str:
        lines: List[str] = [f"<b>نهایی‌سازی سفارش — {self.title}</b>"]
        if self.base_amount is not None:
            lines.append(f"مبلغ انتخابی: {_fmt_usd(self.base_amount)}")
        if self.price_usd is not None:
            lines.append(f"<b>مبلغ پرداخت نهایی:</b> {_fmt_usd(self.price_usd)} ({self.note})")
            lines.append(f"\n✅ لطفاً مبلغ فوق را به شماره‌حساب زیر واریز کنید:\n<b>{ACCOUNT_NO}</b>")
            lines.append(f"و سپس <b>رسید</b> را برای ادمین {ADMIN_USER} ارسال نمایید.")
        else:
            lines.append(f"⛳ {self.note}")
            lines.append(f"برای ادامه و استعلام دقیق، با ادمین {ADMIN_USER} در ارتباط باشید.")
        if self.extra:
            lines.append(f"\nاطلاعات تکمیلی:\n{self.extra}")
        return "\n".join(lines)


class AmountSelectorInline(BaseMessage):
    """
    Inline selector to collect options WITHOUT creating a new menu.
    - Can optionally ask for region (PlayStation).
    - Builds amount buttons dynamically so each button callback is a BaseMessage INSTANCE.
    """
    def __init__(
        self,
        navigation: MyNavigationHandler,
        title: str,
        service_key: str,
        denoms: List[int],
        region_prompt: bool = False,
        extra: Optional[str] = None,
    ):
        super().__init__(navigation, label=f"amount_selector:{service_key}", inlined=True, notification=False)
        self.title = title
        self.service_key = service_key
        self.denoms = denoms
        self.region_prompt = region_prompt
        self.region_selected: Optional[str] = None  # "US" or "OTHER"
        self.extra = extra

        # keyboard will be built in update() each time (dynamic)

    # --- Small actions to toggle region. Return strings (status) so framework shows a toast and then we edit.
    def _set_region_us(self) -> str:
        self.region_selected = "US"
        return "ریجن روی آمریکا تنظیم شد. یکی از مبالغ را انتخاب کنید."

    def _set_region_other(self) -> str:
        self.region_selected = "OTHER"
        return "ریجن روی سایر کشورها تنظیم شد. یکی از مبالغ را انتخاب کنید."

    def _build_amount_buttons(self) -> List[List[MenuButton]]:
        """
        Create per-amount buttons whose callback is an OrderSummaryMessage INSTANCE
        (so selecting a button opens an inline summary directly).
        """
        rows: List[List[MenuButton]] = []
        row: List[MenuButton] = []
        for d in self.denoms:
            # compute price & note with current region
            price, note = compute_total(
                self.service_key,
                base_amount=float(d),
                region=self.region_selected if self.region_selected else None,
            )
            summary = OrderSummaryMessage(
                self.navigation,
                title=self.title,
                price_usd=price,
                note=note,
                service_key=self.service_key,
                base_amount=float(d),
                extra=self.extra,
            )
            # each amount opens a summary (BaseMessage)
            btn = MenuButton(f"{d}$", callback=summary, btype=ButtonType.NOTIFICATION)
            row.append(btn)
            # Arrange 4 per row for inline
            if len(row) == 4:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        return rows

    def update(self, context: Optional[CallbackContext[BT, UD, CD, BD]] = None) -> str:
        # Build dynamic inline keyboard
        keyboard: List[List[MenuButton]] = []

        # 1) Region controls (if applicable)
        if self.region_prompt:
            keyboard.append(
                [
                    MenuButton("🇺🇸 US", callback=self._set_region_us, btype=ButtonType.NOTIFICATION),
                    MenuButton("🌍 Other", callback=self._set_region_other, btype=ButtonType.NOTIFICATION),
                ]
            )

        # 2) Amount buttons (depend on selected region if needed)
        keyboard.extend(self._build_amount_buttons())

        # 3) Helper/message buttons
        keyboard.append(
            [MenuButton("🔢 راهنمای مبلغ دلخواه", callback=self._help_custom_amount, btype=ButtonType.MESSAGE)]
        )

        self.keyboard = keyboard

        # Content text
        lines = [f"انتخاب مبلغ — {self.title}"]
        if self.region_prompt:
            if self.region_selected == "US":
                lines.append("ریجن: 🇺🇸 آمریکا (~۵٪ زیر قیمت اسمی)")
            elif self.region_selected == "OTHER":
                lines.append("ریجن: 🌍 سایر کشورها (~۵٪ بالاتر از اسمی)")
            else:
                lines.append("ابتدا ریجن را انتخاب کنید، سپس مبلغ را بزنید.")
        lines.append("یکی از مبالغ متداول را انتخاب کنید یا راهنمای مبلغ دلخواه را بزنید.")
        return "\n".join(lines)

    def _help_custom_amount(self) -> str:
        return (
            "اگر مبلغ موردنظر در لیست نیست، عدد دلاری را به صورت متنی ارسال کنید یا با ادمین "
            f"{ADMIN_USER} هماهنگ کنید. محاسبه‌ی نهایی با همین فرمول انجام می‌شود."
        )

    async def text_input(self, text: str, context: Optional[CallbackContext[BT, UD, CD, BD]] = None) -> None:
        """
        Optional: allow user to type a custom USD amount (e.g., '37').
        We'll parse it and send an inline OrderSummaryMessage.
        """
        try:
            amt = float(text.replace("$", "").strip())
        except Exception:
            await self.navigation.send_message("لطفاً مبلغ دلاری معتبر وارد کنید (مثلاً 37 یا 37$).", notification=True)
            return
        price, note = compute_total(
            self.service_key, base_amount=amt, region=self.region_selected if self.region_selected else None
        )
        summary = OrderSummaryMessage(
            self.navigation, self.title, price, note, self.service_key, base_amount=amt, extra=self.extra
        )
        # Send as inline app message
        await self.navigation._send_app_message(summary, label="custom_amount", context=context)


class ActionAppMessage(BaseMessage):
    """Single action message used for showing static content (like details)."""
    LABEL = "action"

    def __init__(self, navigation: MyNavigationHandler, shared_content: Optional[str] = None) -> None:
        super().__init__(
            navigation,
            ActionAppMessage.LABEL,
            expiry_period=datetime.timedelta(seconds=5),
            inlined=True,
        )
        self.shared_content = shared_content

    def update(self) -> str:
        return self.shared_content or "تعریف نشده"


# ---------- Product Detail (menu level) ----------
class ProductDetailMessage(BaseMessage):
    """
    Menu message describing a product/service with a '🛒 سفارش' button.
    The '🛒 سفارش' button now points to a BaseMessage instance (NOT a method),
    per framework expectations.
    """
    def __init__(
        self,
        navigation: MyNavigationHandler,
        title: str,
        description: str,
        details: Optional[str] = None,
        service_key: Optional[str] = None,
    ):
        super().__init__(navigation, label=f"detail:{title}", notification=True)
        self.title = title
        self.description = description
        self.details = details
        self.service_key = (service_key or title.lower().replace(" ", "_")).strip()

        # Build the correct "order target" as a BaseMessage instance
        self._order_target = self._build_order_target()

        # Buttons (menu-level)
        # IMPORTANT: callback is a BaseMessage instance to open either an inline selector or an inline summary
        self.add_button("🛒 سفارش", callback=self._order_target)
        if details:
            # Use ActionAppMessage instead of btype=ButtonType.MESSAGE
            self.add_button("اطلاعات تکمیلی", callback=ActionAppMessage(navigation, self.details))
        self.add_button(label="⬅️ بازگشت", callback=navigation.goto_back)
        self.add_button(label="🏠 خانه", callback=navigation.goto_home)

    def _details_msg(self) -> str:
        return self.details or "—"

    def _build_order_target(self) -> BaseMessage:
        key = self.service_key
        strat = PRICING.get(key, {"type": "quote_needed"})["type"]

        # Services needing user amount/options → inline selector
        if strat == "percent":
            return AmountSelectorInline(self.navigation, self.title, key, COMMON_DENOMS_SMALL, region_prompt=False, extra=self.details)
        if strat == "psn_region":
            return AmountSelectorInline(self.navigation, self.title, key, COMMON_DENOMS_SMALL, region_prompt=True, extra=self.details)
        if strat == "prepaid_tier":
            return AmountSelectorInline(self.navigation, self.title, key, PREPAID_DENOMS, region_prompt=False, extra=self.details)

        # Fixed-price service → inline final summary immediately
        if strat == "fixed":
            price, note = compute_total(key)
            return OrderSummaryMessage(self.navigation, self.title, price, note, key, extra=self.details)

        # Quote needed
        return OrderSummaryMessage(self.navigation, self.title, None, "قیمت‌گذاری این مورد نیاز به استعلام دارد.", key, extra=self.details)

    def update(self, context: Optional[CallbackContext[BT, UD, CD, BD]] = None) -> str:
        txt = f"<b>{self.title}</b>\n\n{self.description}\n\nبرای سفارش دکمه «🛒 سفارش» را بزنید."
        return txt


# ---------- Category Menus (menu level) ----------
def _read_file_if_exists(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip() if path.exists() else ""


def _load_text(resources_dir: Path, stem: str) -> Tuple[str, str]:
    desc = _read_file_if_exists(resources_dir / f"{stem}_desc.txt") or "—"
    details = _read_file_if_exists(resources_dir / f"{stem}_details.txt") or ""
    return desc, details


class GiftCardsMenuMessage(BaseMessage):
    LABEL = "💳 گیفت‌کارت‌ها"

    def __init__(self, navigation: MyNavigationHandler):
        super().__init__(navigation, label=self.LABEL, notification=False)
        resources = (ROOT_FOLDER.parent / "resources")

        products = [
            ("apple_gift", "Apple Gift Card"),
            ("google_play", "Google Play"),
            ("playstation", "PlayStation"),
            ("prepaid_card", "Prepaid Master/Visa"),
        ]
        for key, display in products:
            desc, details = _load_text(resources, key)
            self.add_button(
                display,
                callback=ProductDetailMessage(navigation, display, desc, details, service_key=key),
            )

        self.add_button(label="⬅️ بازگشت", callback=navigation.goto_back)
        self.add_button(label="🏠 خانه", callback=navigation.goto_home)

    def update(self, context: Optional[CallbackContext[BT, UD, CD, BD]] = None) -> str:
        return "یکی از گیفت‌کارت‌ها را انتخاب کنید:"


class AccountsMenuMessage(BaseMessage):
    LABEL = "🏦 حساب‌های بین‌المللی"

    def __init__(self, navigation: MyNavigationHandler):
        super().__init__(navigation, label=self.LABEL, notification=False)
        resources = (ROOT_FOLDER.parent / "resources")

        accounts = [
            ("paypal", "PayPal"),
            ("wirex", "Wirex"),
            ("mastercard", "MasterCard 🇹🇷"),
            ("wise", "Wise (TransferWise)"),
        ]
        for key, display in accounts:
            desc, details = _load_text(resources, key)
            self.add_button(display, callback=ProductDetailMessage(navigation, display, desc, details, service_key=key))

        self.add_button(label="⬅️ بازگشت", callback=navigation.goto_back)
        self.add_button(label="🏠 خانه", callback=navigation.goto_home)

    def update(self, context: Optional[CallbackContext[BT, UD, CD, BD]] = None) -> str:
        return "کدام نوع حساب بین‌المللی را می‌خواهید؟"


class PaymentsMenuMessage(BaseMessage):
    LABEL = "💵 پرداخت‌های ارزی"

    def __init__(self, navigation: MyNavigationHandler):
        super().__init__(navigation, label=self.LABEL, notification=False)
        resources = (ROOT_FOLDER.parent / "resources")

        payments = [
            ("university_fee", "پرداخت شهریه دانشگاه"),
            ("saas_purchase", "خرید سرویس‌های SaaS"),
            ("flight_hotel", "بلیط هواپیما / هتل"),
            ("fx_to_rial", "تبدیل درآمد ارزی به ریال"),
        ]
        for key, display in payments:
            desc, details = _load_text(resources, key)
            self.add_button(display, callback=ProductDetailMessage(navigation, display, desc, details, service_key=key))

        self.add_button(label="⬅️ بازگشت", callback=navigation.goto_back)
        self.add_button(label="🏠 خانه", callback=navigation.goto_home)

    def update(self, context: Optional[CallbackContext[BT, UD, CD, BD]] = None) -> str:
        return "نوع پرداخت ارزی خود را انتخاب کنید:"


class ServicesMenuMessage(BaseMessage):
    LABEL = "خدمات ما 🛠️"

    def __init__(self, navigation: MyNavigationHandler):
        super().__init__(navigation, label=self.LABEL, notification=False)

        self.add_button("💳 گیفت‌کارت‌ها", callback=GiftCardsMenuMessage(navigation))
        self.add_button("🏦 حساب‌های بین‌المللی", callback=AccountsMenuMessage(navigation))
        self.add_button("💵 پرداخت‌های ارزی", callback=PaymentsMenuMessage(navigation))
        self.add_button(
            "✨ خدمات ویژه",
            callback=ProductDetailMessage(
                navigation,
                "خدمات ویژه",
                "تبدیل درآمد، کارت مجازی و خدمات اختصاصی.",
                "جزئیات خدمات ویژه به زودی اضافه می‌شود.",
                service_key="special_services",
            ),
        )

        self.add_button(label="⬅️ بازگشت", callback=navigation.goto_back)
        self.add_button(label="🏠 خانه", callback=navigation.goto_home)

    def update(self, context: Optional[CallbackContext[BT, UD, CD, BD]] = None) -> str:
        return "خدمات اصلی اصل‌پی را ببینید:"


class LearningMenuMessage(BaseMessage):
    LABEL = "آموزش و راهنما 📚"

    def __init__(self, navigation: MyNavigationHandler):
        super().__init__(navigation, label=self.LABEL, notification=False)
        self.add_button("آموزش خرید", callback=self._buy_guide, btype=ButtonType.MESSAGE)
        self.add_button("آموزش امنیت", callback=self._security_guide, btype=ButtonType.MESSAGE)
        self.add_button(label="⬅️ بازگشت", callback=navigation.goto_back)
        self.add_button(label="🏠 خانه", callback=navigation.goto_home)

    def _buy_guide(self) -> str:
        return "برای خرید: سرویس را انتخاب کنید → «🛒 سفارش» → پرداخت و ارسال رسید به ادمین."

    def _security_guide(self) -> str:
        return "نکته امنیتی: هرگز اطلاعات کامل کارت یا رمز یک‌بارمصرف را در چت عمومی ارسال نکنید."

    def update(self, context: Optional[CallbackContext[BT, UD, CD, BD]] = None) -> str:
        return "راهنماها و نکات امنیتی را مطالعه کنید."


class ContactMenuMessage(BaseMessage):
    LABEL = "پشتیبانی 👤"

    def __init__(self, navigation: MyNavigationHandler):
        super().__init__(navigation, label=self.LABEL, notification=False)
        self.add_button("ارسال پیام به پشتیبانی", callback=self._contact, btype=ButtonType.MESSAGE)
        self.add_button("تماس ادمین", callback=self._admin, btype=ButtonType.MESSAGE)
        self.add_button(label="⬅️ بازگشت", callback=navigation.goto_back)
        self.add_button(label="🏠 خانه", callback=navigation.goto_home)

    def _contact(self) -> str:
        return "پیام شما به پشتیبانی ارسال شد. در ساعات کاری پاسخ داده می‌شود."

    def _admin(self) -> str:
        return f"تماس فوری: {ADMIN_USER}"

    def update(self, context: Optional[CallbackContext[BT, UD, CD, BD]] = None) -> str:
        return "راه‌های ارتباط با پشتیبانی را انتخاب کنید."


class StartMessage(BaseMessage):
    LABEL = "start"

    def __init__(self, navigation: MyNavigationHandler, message_args: Optional[List[Any]] = None) -> None:
        super().__init__(navigation, label=self.LABEL, notification=True)

        self.add_button("آموزش و راهنما 📚", callback=LearningMenuMessage(navigation))
        self.add_button("خدمات ما 🛠️", callback=ServicesMenuMessage(navigation))
        self.add_button("پشتیبانی 👤", callback=ContactMenuMessage(navigation))

    def update(self, context: Optional[CallbackContext[BT, UD, CD, BD]] = None) -> str:
        return "🌍💳 Asll Pay | اصل‌پی 💳🌍\n\nبه ربات اصل‌پی خوش آمدید!\nاز منو گزینه موردنظر را انتخاب کنید."


# ========= Logger helper (optional, unchanged) =========
def init_logger(current_logger: str) -> logging.Logger:
    log_formatter = logging.Formatter(
        fmt="%(asctime)s [%(name)s] [%(levelname)s]  %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_formatter)
    _logger = logging.getLogger(current_logger)
    _logger.setLevel(logging.DEBUG)
    _logger.addHandler(console_handler)
    _logger.propagate = False
    return _logger
