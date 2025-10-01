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
import time
import asyncio
import html
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Callable

from telegram import ReplyKeyboardMarkup

from telegram.ext._callbackcontext import CallbackContext
from telegram.ext._utils.types import BD, BT, CD, UD

from telegram_menu import BaseMessage, MenuButton, ButtonType
from telegram_menu import NavigationHandler as _BaseNav  # type: ignore

ROOT_FOLDER = Path(__file__).parent

# ========= App Config =========
ADMIN_USER = "@asll_pay"
ACCOUNT_NO = os.getenv("ASLLPAY_ACCOUNT_NO", "—")
ADMIN_CHAT_ID = 5375761406        # ← همین عددی که دادی
# ADMIN_CHAT_ID = 104101121        # ← همین عددی که دادی

# ========= Pricing =========
# strategy.type ∈ {"fixed","percent","psn_region","prepaid_tier","quote_needed"}
PRICING: Dict[str, Dict[str, Any]] = {
    # Gift Cards
    "apple_gift":   {"type": "percent", "percent": 5.0},
    "google_play":  {"type": "percent", "percent": 5.0},
    "playstation":  {"type": "psn_region"},
    "prepaid_card": {"type": "prepaid_tier"},
    "other_gift":   {"type": "percent", "percent": 5.0},  # ← جدید: سایر گیفت‌کارت‌ها

    # Accounts / Fixed
    "paypal":       {"type": "fixed", "amount": 40.0},
    "mastercard":   {"type": "fixed", "amount": 130.0},

    # Payments / Receipts
    "site_payment": {"type": "percent", "percent": 5.0},   # ← جدید: پرداخت در سایت مورد نظر (+۵٪)
    "fx_to_rial":   {"type": "percent", "percent": 5.0},   # ← تغییر از quote_needed به +۵٪

    # Others require quote
    "wirex":        {"type": "quote_needed"},
    "wise":         {"type": "quote_needed"},
    "university_fee": {"type": "quote_needed"},
    "saas_purchase":  {"type": "quote_needed"},
    "flight_hotel":   {"type": "quote_needed"},
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

async def _notify_admin_giftcard(
    bot,
    admin_chat_id: int,
    title: str,
    region_label: str,
    chosen_txt: str,
    final_txt: str,
    note_calc: str,
    user_chat_id: Optional[int],
    user_first: Optional[str] = None,
):
    username_str = None
    try:
        if user_chat_id:
            chat = await bot.get_chat(user_chat_id)
            if getattr(chat, "username", None):
                username_str = f"@{chat.username}"
            else:
                username_str = "(no-username)"
            if not user_first:
                user_first = getattr(chat, "first_name", None)
    except Exception:
        username_str = username_str or "(unknown)"
        user_first = user_first or "کاربر"

    if user_chat_id:
        user_link = f'<a href="tg://user?id={user_chat_id}">{html.escape(user_first or "کاربر")}</a>'
        user_tail = f" ({username_str}) id={user_chat_id}"
    else:
        user_link = html.escape(user_first or "کاربر")
        user_tail = f" ({username_str})"

    note_lines = [
        "🔔 پرداخت گیفت‌کارت ثبت شد",
        f"• سرویس: {html.escape(title)}",
        f"• ریجن: {region_label}",
        f"• مبلغ انتخابی: {chosen_txt}",
        f"• مبلغ پرداخت نهایی: {final_txt}",
        f"• توضیح محاسبه: {html.escape(note_calc)}" if note_calc else "",
        f"• کاربر: {user_link}{user_tail}",
    ]
    note_text = "\n".join([ln for ln in note_lines if ln])

    await bot.send_message(
        chat_id=admin_chat_id,
        text=note_text,
        parse_mode="HTML",
        disable_notification=False,
    )

async def _notify_admin_payment(
    bot,
    admin_chat_id: int,
    title: str,
    amount_txt: str,
    user_chat_id: Optional[int],
    user_first: Optional[str] = None,
):
    """
    username واقعی کاربر را با get_chat می‌گیرد تا قطعاً کامل باشد (مثل Mahdi749574).
    سپس پیام کامل را برای ادمین می‌فرستد.
    """
    username_str = None
    try:
        if user_chat_id:
            chat = await bot.get_chat(user_chat_id)  # ← Chat(username=..., first_name=..., ...)
            # chat.username بدون @ است؛ اگر None بود، لینک کاربر را می‌سازیم
            if getattr(chat, "username", None):
                username_str = f"@{chat.username}"
            else:
                username_str = "(no-username)"
            if not user_first:
                user_first = getattr(chat, "first_name", None)
    except Exception:
        # اگر get_chat خطا داد، حداقل چیزی نشان بدهیم
        username_str = username_str or "(unknown)"
        user_first = user_first or "کاربر"

    # لینک کلیک‌پذیر به پروفایل تلگرام کاربر
    if user_chat_id:
        user_link = f'<a href="tg://user?id={user_chat_id}">{html.escape(user_first or "کاربر")}</a>'
        user_tail = f" ({username_str}) id={user_chat_id}"
    else:
        user_link = html.escape(user_first or "کاربر")
        user_tail = f" ({username_str})"

    note_text = (
        "🔔 پرداخت جدید ثبت شد\n"
        f"• سرویس: {html.escape(title)}\n"
        f"• مبلغ: {amount_txt}\n"
        f"• کاربر: {user_link}{user_tail}"
    )

    await bot.send_message(
        chat_id=admin_chat_id,
        text=note_text,
        parse_mode="HTML",
        disable_notification=False,
    )

class OrderSummaryMessage(BaseMessage):
    """
    خلاصه نهایی سفارش (برای تمام سرویس‌های غیر گیفت‌کارت).
    دکمه‌ها مثل گیفت‌کارت‌ها فقط «✅ واریز کردم» و «⌛ هنوز واریز نکردم» هستند.
    بعد از «واریز کردم» هیچ منوی اضافه‌ای (سفارش مجدد/تماس با ادمین) نشان داده نمی‌شود؛
    فقط پیام تأیید نمایش داده می‌شود و state در حالت خلاصه باقی می‌ماند تا کاربر دوباره همین مسیر را برود.
    """
    def __init__(
        self,
        navigation: MyNavigationHandler,
        title: str,
        price_usd: Optional[float],
        note: str,
        service_key: str,
        base_amount: Optional[float] = None,
        extra: Optional[str] = None,  # محتوای «اطلاعات بیشتر» در صورت نیاز
    ):
        super().__init__(navigation, label=f"order_summary:{service_key}", inlined=True, notification=True)
        self.title = title
        self.price_usd = price_usd
        self.note = note
        self.service_key = service_key
        self.base_amount = base_amount
        self.extra = extra

        # فقط همین دو دکمه مثل جریان گیفت‌کارت‌ها
        self.keyboard = [
            [MenuButton("✅ واریز کردم", callback=self._mark_paid, btype=ButtonType.MESSAGE)],
            [MenuButton("⌛ هنوز واریز نکردم", callback=self._not_paid)],
        ]

    # ——— Actions: باید رشته برگردانند (برای inline buttons) ———
    def _mark_paid(self) -> str:
        amount_txt = _fmt_usd(self.price_usd) if self.price_usd is not None else "—"

        user_chat_id = getattr(self.navigation, "chat_id", None)
        user_first   = getattr(self.navigation, "first_name", None) or getattr(self.navigation, "user_first_name", None)

        # تسک async: username واقعی را می‌گیرد و پیام را برای ادمین می‌فرستد
        asyncio.create_task(_notify_admin_payment(
            self.navigation._bot,
            ADMIN_CHAT_ID,
            self.title,
            amount_txt,
            user_chat_id,
            user_first,
        ))

        tail = " همچنین مدارک مورد نیاز (از بخش «اطلاعات بیشتر») را هم برای ادمین ارسال کنید." if getattr(self, "extra", None) else ""
        return f"✅ دریافت شد. لطفاً رسید پرداخت را برای ادمین {ADMIN_USER} ارسال کنید.{tail}"

    def _not_paid(self) -> str:
        """اعلام عدم واریز: پیام راهنما، در حالت خلاصه می‌مانیم."""
        return "باشه! هر زمان پرداخت کردید، با «✅ واریز کردم» اطلاع بدهید و رسید را هم بفرستید."

    # ——— Render ———
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
        return "\n".join(lines)

class AmountSelectorInline(BaseMessage):
    """
    انتخاب مبلغ به‌صورت inline (بدون ساخت منوی جدید).
    نکته‌ی مهم: callback دکمه‌های inline باید «تابعی باشد که متن برمی‌گرداند»،
    و نباید آبجکت پیام برگردانیم (تا خطای JSON serialization پیش نیاید).
    این کلاس state داخلی را نگه می‌دارد و با update_callback پیام را رفرش می‌کند.
    """

    def __init__(
        self,
        navigation: MyNavigationHandler,
        title: str,
        service_key: str,
        denoms: List[int],
        region_prompt: bool = False,
        default_region: Optional[str] = None,
        update_callback: Optional[List[Callable]] = None,
    ):
        uniq = f"{service_key}:{default_region or 'ANY'}:{int(time.time())}"
        super().__init__(navigation, label=f"amount_selector:{uniq}", inlined=True, notification=False)

        self.title = title
        self.service_key = service_key
        self.denoms = denoms
        self.region_prompt = region_prompt
        self.region_selected: Optional[str] = default_region  # "US" | "OTHER" | None

        # State برای نمایش خلاصه/انتخاب مبلغ
        self.selected_amount: Optional[float] = None
        self._mode: str = "pick"           # "pick" | "summary"
        self._price: Optional[float] = None
        self._note: str = ""

        # ثبت update_callback تا بعد از هر اکشن بتونیم پیام رو refresh کنیم (مثل نمونه‌ی شما)
        self._update_callback = update_callback
        if isinstance(update_callback, list):
            update_callback.append(self.app_update_display)

    # ---- Hooks برای رفرش UI پس از اکشن‌ها ----
    async def app_update_display(self) -> None:
        if await self.edit_message():
            self.is_alive()

    # ---- Callbacks: Region selection ----
    def _make_set_region_cb(self, region_code: str):
        def _cb() -> str:
            self.region_selected = region_code
            self._mode = "pick"
            return "ریجن تنظیم شد. حالا مبلغ را انتخاب کنید."
        return _cb

    # ---- Callbacks: pick amount → compute & go summary (return TEXT only) ----
    def _pick_amount_cb(self, amount: float):
        def _cb() -> str:
            self.selected_amount = float(amount)
            self._price, self._note = compute_total(
                self.service_key,
                base_amount=self.selected_amount,
                region=self.region_selected if self.region_selected else None,
            )
            self._mode = "summary"
            # یک متن کوتاه برای نوتیف؛ UI با app_update_display رفرش می‌شود
            return f"✅ {_fmt_usd(self.selected_amount)} شما وارد شد."
        return _cb

    # ---- Callbacks: paid / not paid (return TEXT only) ----
    def _mark_paid(self) -> str:
        final_txt  = _fmt_usd(self._price) if self._price is not None else "—"
        chosen_txt = _fmt_usd(self.selected_amount) if self.selected_amount is not None else "—"
        if self.region_prompt:
            region_label = "🇺🇸 US" if self.region_selected == "US" else ("🌍 Other" if self.region_selected == "OTHER" else "—")
        else:
            region_label = "—"

        user_chat_id = getattr(self.navigation, "chat_id", None)
        user_first   = getattr(self.navigation, "first_name", None) or getattr(self.navigation, "user_first_name", None)

        # نوتیف ادمین با جزئیات گیفت‌کارت (یا هر سرویس درصدی)
        asyncio.create_task(_notify_admin_giftcard(
            self.navigation._bot,
            ADMIN_CHAT_ID,
            self.title,
            region_label,
            chosen_txt,
            final_txt,
            self._note or "",
            user_chat_id,
            user_first,
        ))

        # پیام اختصاصی بعد از واریز برای برخی سرویس‌ها
        if self.service_key == "site_payment":
            # تاکید: بعد از واریز، اطلاعات ورود سایت را بفرستند
            self._mode = "done"
            return (
                f"✅ دریافت شد. لطفاً رسید پرداخت را برای ادمین {ADMIN_USER} ارسال کنید.\n"
                "ℹ️ سپس <b>آدرس سایت، نام کاربری و رمز عبور</b> حساب‌تان در آن سایت را هم بفرستید تا پرداخت شما انجام شود."
            )
        if self.service_key == "fx_to_rial":
            # تاکید: روش انتقال ارزی و مرجع تراکنش
            self._mode = "done"
            return (
                f"✅ دریافت شد. لطفاً رسید پرداخت را برای ادمین {ADMIN_USER} ارسال کنید.\n"
                "ℹ️ لطفاً روش انتقال ارزی (مثلاً Swift/PayPal) و مرجع تراکنش را هم ارسال کنید تا تسویه ریالی انجام شود. "
                "کارمزد ۵٪ منظور می‌شود."
            )

        # سایر درصدی‌ها (مثل گیفت‌کارت‌ها)
        self._mode = "done"
        return f"✅ دریافت شد. لطفاً رسید پرداخت را برای ادمین {ADMIN_USER} ارسال کنید."

    def _not_paid(self) -> str:
        # بعد از ارسال پیام، حالت برگرده به انتخاب مبلغ
        self._mode = "pick"
        self.selected_amount = None
        self._price = None
        self._note = ""
        self.region_selected = None
        return "باشه! هر وقت پرداخت کردید، با «✅ واریز کردم» خبر بدید و رسید را هم بفرستید."

    # ---- Build amount buttons (callbacks are FUNCTIONS returning TEXT) ----
    def _build_amount_buttons(self) -> List[List[MenuButton]]:
        rows: List[List[MenuButton]] = []
        row: List[MenuButton] = []
        for d in self.denoms:
            btn = MenuButton(
                f"{d}$",
                callback=self._pick_amount_cb(float(d)),
                btype=ButtonType.NOTIFICATION
            )
            row.append(btn)
            if len(row) == 4:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        return rows

    # ---- Render UI ----
    def update(self, context: Optional[CallbackContext[BT, UD, CD, BD]] = None) -> str:
        # حالت خلاصه‌ی سفارش
        if self._mode == "summary":
            # دکمه‌های پرداخت
            self.keyboard = [
                [MenuButton("✅ واریز کردم", callback=self._mark_paid, btype=ButtonType.MESSAGE)],
                [MenuButton("⌛ هنوز واریز نکردم", callback=self._not_paid)],
            ]
            lines: List[str] = [f"<b>سفارش ثبت شد — {self.title}</b>"]
            if self.selected_amount is not None:
                lines.append(f"مبلغ انتخابی: {_fmt_usd(self.selected_amount)}")
            if self._price is not None:
                lines.append(f"<b>مبلغ پرداخت نهایی:</b> {_fmt_usd(self._price)} ({self._note})")
                lines.append(f"\n✅ لطفاً مبلغ فوق را به شماره‌حساب زیر واریز کنید:\n<b>{ACCOUNT_NO}</b>")
                lines.append(f"و سپس <b>رسید</b> را برای ادمین {ADMIN_USER} ارسال نمایید.")
            else:
                lines.append("⛳ برای ادامه با ادمین در ارتباط باشید.")
            return "\n".join(lines)

        # حالت انتخاب مبلغ
        keyboard: List[List[MenuButton]] = []
        if self.region_prompt and not self.region_selected:
            # انتخاب ریجن (دکمه‌ها «تابع» دارند که TEXT برمی‌گرداند)
            keyboard.append([
                MenuButton("🇺🇸 US", callback=self._make_set_region_cb("US")),
                MenuButton("🌍 Other", callback=self._make_set_region_cb("OTHER")),
            ])
        # دکمه‌های مبلغ
        keyboard.extend(self._build_amount_buttons())
        # راهنمای مبلغ دلخواه
        keyboard.append([MenuButton(
            "🔢 راهنمای مبلغ دلخواه",
            callback=lambda: "اگر مبلغ موردنظر در لیست نیست، عدد دلاری را به صورت متنی ارسال کنید یا با ادمین "
                             f"{ADMIN_USER} هماهنگ کنید."
        )])
        self.keyboard = keyboard

        # متن توضیحی
        lines = [f"انتخاب مبلغ — {self.title}"]
        if self.region_prompt:
            if self.region_selected == "US":
                lines.append("ریجن: 🇺🇸 آمریکا (~۵٪ زیر قیمت اسمی)")
            elif self.region_selected == "OTHER":
                lines.append("ریجن: 🌍 سایر کشورها (~۵٪ بالاتر از اسمی)")
            else:
                lines.append("لطفاً ریجن را انتخاب کنید، سپس مبلغ را انتخاب کنید.")
        lines.append("یکی از مبالغ متداول را انتخاب کنید یا راهنمای مبلغ دلخواه را بزنید.")
        return "\n".join(lines)


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
            return AmountSelectorInline(self.navigation, self.title, key, COMMON_DENOMS_SMALL, region_prompt=False)
        if strat == "psn_region":
            return AmountSelectorInline(self.navigation, self.title, key, COMMON_DENOMS_SMALL, region_prompt=True)
        if strat == "prepaid_tier":
            return AmountSelectorInline(self.navigation, self.title, key, PREPAID_DENOMS, region_prompt=False)

        # Fixed-price service → inline final summary immediately
        if strat == "fixed":
            price, note = compute_total(key)
            return OrderSummaryMessage(self.navigation, self.title, price, note, key)

        # Quote needed
        return OrderSummaryMessage(self.navigation, self.title, None, "قیمت‌گذاری این مورد نیاز به استعلام دارد.", key)

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
            ("other_gift", "سایر گیفت‌کارت‌ها ⭐"),  # ← جدید
        ]

        for key, display in products:
            desc, details = _load_text(resources, key)
            self.add_button(
                display,
                callback=ProductDetailMessage(navigation, display, desc, details, service_key=key),
            )

        self.add_button(label="⬅️ بازگشت", callback=navigation.goto_back, new_row=True)
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

        self.add_button(label="⬅️ بازگشت", callback=navigation.goto_back, new_row=True)
        self.add_button(label="🏠 خانه", callback=navigation.goto_home)

    def update(self, context: Optional[CallbackContext[BT, UD, CD, BD]] = None) -> str:
        return "کدام نوع حساب بین‌المللی را می‌خواهید؟"


class PaymentsMenuMessage(BaseMessage):
    LABEL = "💵 پرداخت/دریافت ارزی"  # ← تغییر عنوان

    def __init__(self, navigation: MyNavigationHandler):
        super().__init__(navigation, label=self.LABEL, notification=False)
        resources = (ROOT_FOLDER.parent / "resources")

        payments = [
            ("site_payment", "پرداخت در سایت مورد نظر"),   # ← جدید (درصدی +۵٪ با سِلکتور مبلغ)
            ("fx_to_rial", "تبدیل درآمد ارزی به ریال"),    # ← تبدیل، درصدی +۵٪
            # ("university_fee", "پرداخت شهریه دانشگاه"),
            # ("saas_purchase", "خرید سرویس‌های SaaS"),
            # ("flight_hotel", "بلیط هواپیما / هتل"),
        ]
        for key, display in payments:
            desc, details = _load_text(resources, key)
            self.add_button(display, callback=ProductDetailMessage(navigation, display, desc, details, service_key=key))

        self.add_button(label="⬅️ بازگشت", callback=navigation.goto_back, new_row=True)
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

        self.add_button(label="⬅️ بازگشت", callback=navigation.goto_back, new_row=True)
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
