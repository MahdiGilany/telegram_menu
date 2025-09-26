#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Asll Pay — Telegram menu (complete version)
# Generated to implement full services menu for اصل‌پی with update_callback support

import os
import datetime
import logging
from logging import Logger
from pathlib import Path
from typing import Any, Callable, Coroutine, List, Optional, Union

from telegram import InlineKeyboardMarkup, Message, ReplyKeyboardMarkup

try:
    from typing_extensions import TypedDict
except ImportError:
    from typing import TypedDict

from telegram.ext._callbackcontext import CallbackContext
from telegram.ext._utils.types import BD, BT, CD, UD

import telegram_menu
from telegram_menu import BaseMessage, ButtonType, MenuButton, NavigationHandler, TelegramMenuSession

ROOT_FOLDER = Path(__file__).parent

UnitTestDict = TypedDict("UnitTestDict", {"description": str, "input": str, "output": str})
TypePackageLogger = TypedDict("TypePackageLogger", {"package": str, "level": int})

class MyNavigationHandler(NavigationHandler):
    # async def goto_back(self) -> int:
    #     return await self.select_menu_button("⬅️ بازگشت")
    
    async def goto_back(self) -> int:
        """Do Go Back logic."""
        return await self.select_menu_button("Back")


class ActionAppMessage(BaseMessage):
    """Single action message."""

    LABEL = "action"

    def __init__(self, navigation: MyNavigationHandler, shared_content: Optional[str] = None) -> None:
        """Init ActionAppMessage class."""
        super().__init__(
            navigation,
            ActionAppMessage.LABEL,
            expiry_period=datetime.timedelta(seconds=5),
            inlined=True,
        )
        self.shared_content = shared_content

    def update(self) -> str:
        """Update message content."""
        content = self.shared_content or "تعریف نشده"
        return f"{content}"


class ProductDetailMessage(BaseMessage):
    """نمایش جزئیات یک محصول / سرویس به همراه دکمه سفارش"""

    def __init__(self, navigation: MyNavigationHandler, title: str, description: str, details: Optional[str] = None, sample_price: Optional[str] = None, update_callback: Optional[List[Callable]] = None):
        label = f"detail:{title}"
        super().__init__(navigation, label, notification=True)
        self.title = title
        self.description = description
        self.sample_price = sample_price

        # دکمه‌ها: سفارش، بازگشت، خانه
        self.add_button(label="🛒 سفارش", callback=self.action_order)
        self.add_button(label="ℹ️ جزئیات", callback=ActionAppMessage(navigation, details))
        self.add_button(label="⬅️ بازگشت", callback=navigation.goto_back)
        self.add_button(label="🏠 خانه", callback=navigation.goto_home)

        if isinstance(update_callback, list):
            update_callback.append(self.app_update_display)

    async def app_update_display(self) -> None:
        edited = await self.edit_message()
        if edited:
            self.is_alive()

    def update(self) -> str:
        out = f"<b>{self.title}</b>\n\n{self.description}\n"
        if self.sample_price:
            out += f"\n<b>قیمت تقریبی:</b> {self.sample_price}\n"
        out += "\nبرای سفارش دکمه '🛒 سفارش' را بزنید."
        return out

    def action_order(self, *args):
        return f"سفارش برای '{self.title}' ثبت شد. لطفاً اطلاعات پرداخت را ارسال کنید یا با پشتیبانی تماس بگیرید."


class GiftCardsMenuMessage(BaseMessage):
    LABEL = "💳 گیفت‌کارت‌ها"

    def __init__(self, navigation: MyNavigationHandler, update_callback: Optional[List[Callable]] = None):
        super().__init__(navigation, GiftCardsMenuMessage.LABEL, notification=False)

        products = [
            (
                "Apple Gift Card",
                "گیفت‌کارت اپل — قابل استفاده در App Store و Apple ID.",
                "جزئیات Apple Gift Card به زودی اضافه می‌شود.",
                "از 10 تا 200 دلار"
            ),
            (
                "Google Play",
                "گیفت‌کارت گوگل‌پلی — شارژ حساب گوگل‌پلی.",
                "جزئیات Google Play به زودی اضافه می‌شود.",
                "از 10 تا 100 دلار"
            ),
            (
                "PlayStation",
                "گیفت‌کارت پلی‌استیشن — شارژ کیف پول PSN.",
                "جزئیات PlayStation به زودی اضافه می‌شود.",
                "از 10 تا 100 دلار"
            ),
            (
                "Xbox",
                "گیفت‌کارت ایکس‌باکس — شارژ کیف پول Xbox.",
                "جزئیات Xbox به زودی اضافه می‌شود.",
                "از 10 تا 100 دلار"
            ),
            (
                "Steam",
                "گیفت‌کارت استیم — برای خرید بازی‌ها و آیتم‌ها.",
                "جزئیات Steam به زودی اضافه می‌شود.",
                "از 5 تا 100 دلار"
            ),
            (
                "Prepaid Master/Visa",
                "کارت‌های پیش‌پرداخت مستر/ویزا — قابل استفاده در وب‌سایت‌هایی که کارت‌های بین‌المللی قبول می‌کنند.",
                "جزئیات Prepaid Master/Visa به زودی اضافه می‌شود.",
                "متغیر"
            )
        ]

        for title, desc, details, price in products:
            self.add_button(
                label=title,
                callback=ProductDetailMessage(navigation, title, desc, details, price, update_callback)
            )

        self.add_button(label="⬅️ بازگشت", callback=navigation.goto_back)
        self.add_button(label="🏠 خانه", callback=navigation.goto_home)

        if isinstance(update_callback, list):
            update_callback.append(self.app_update_display)

    async def app_update_display(self) -> None:
        edited = await self.edit_message()
        if edited:
            self.is_alive()

    def update(self) -> str:
        return "یکی از گیفت‌کارت‌های زیر را انتخاب کنید:"


class AccountsMenuMessage(BaseMessage):
    LABEL = "🏦 حساب‌های بین‌المللی"

    def __init__(self, navigation: MyNavigationHandler, update_callback: Optional[List[Callable]] = None):
        super().__init__(navigation, AccountsMenuMessage.LABEL, notification=False)

        # می‌تونید جزییات طولانی رو از فایل txt بخونید
        with open(os.path.join(Path(ROOT_FOLDER).parent, "resources", "paypal_details.txt"), "r", encoding="utf-8") as f:
            paypal_details = f.read()

        accounts = [
            (
                "PayPal",
                "باز و فعال‌سازی حساب پی‌پل — مناسب برای دریافت و ارسال ارز دلاری.",
                paypal_details,
                "خدمات افتتاح/فعالسازی"
            ),
            (
                "Wirex",
                "حساب و کارت‌های Wirex — امکانات ارزهای دیجیتال و کارت‌های فیزیکی.",
                "جزئیات Wirex به زودی اضافه می‌شود.",
                "متغیر"
            ),
            (
                "MasterCard ترکیه",
                "صدور کارت مسترکارت ترکیه — مناسب برای پرداخت‌های بین‌المللی و سرویس‌های محلی ترکیه.",
                "جزئیات MasterCard ترکیه به زودی اضافه می‌شود.",
                "متغیر"
            ),
            (
                "Wise (TransferWise)",
                "افتتاح حساب Wise برای انتقال ارزی و دریافت حواله‌های بین‌المللی.",
                "جزئیات Wise به زودی اضافه می‌شود.",
                "متغیر"
            )
        ]

        # تغییر در حلقه: حالا ۴ تا پارامتر می‌گیره (title, desc, details, price)
        for title, desc, details, price in accounts:
            self.add_button(
                label=title,
                callback=ProductDetailMessage(navigation, title, desc, details, price, update_callback)
            )

        self.add_button(label="⬅️ بازگشت", callback=navigation.goto_back)
        self.add_button(label="🏠 خانه", callback=navigation.goto_home)

        if isinstance(update_callback, list):
            update_callback.append(self.app_update_display)

    async def app_update_display(self) -> None:
        edited = await self.edit_message()
        if edited:
            self.is_alive()

    def update(self) -> str:
        return "کدام نوع حساب بین‌المللی را می‌خواهید؟"


class PaymentsMenuMessage(BaseMessage):
    LABEL = "💵 پرداخت‌های ارزی"

    def __init__(self, navigation: MyNavigationHandler, update_callback: Optional[List[Callable]] = None):
        super().__init__(navigation, PaymentsMenuMessage.LABEL, notification=False)

        payments = [
            (
                "پرداخت شهریه دانشگاه",
                "پرداخت شهریه و fee اپلیکیشن برای دانشگاه‌ها و کالج‌های خارج از کشور.",
                "مدارک موردنیاز: اطلاعات دانشجویی + فاکتور دانشگاه. ⏳مدت زمان: ۱-۳ روز کاری.",
                "بسته به مبلغ"
            ),
            (
                "خرید سرویس‌های SaaS",
                "خرید اشتراک ChatGPT, Adobe, Canva, ... و سایر سرویس‌ها.",
                "مدارک موردنیاز: اکانت یا ایمیل. ⏳مدت زمان: فوری تا ۲۴ ساعت.",
                "بسته به سرویس"
            ),
            (
                "بلیط هواپیما / هتل",
                "پرداخت‌های بین‌المللی برای بلیط و هتل.",
                "مدارک موردنیاز: مشخصات رزرو. ⏳مدت زمان: همان روز.",
                "بسته به رزرو"
            ),
            (
                "تبدیل درآمد ارزی به ریال",
                "تبدیل درآمدهای ارزی ارسال شده به حساب شما به ریال.",
                "مدارک موردنیاز: اطلاعات حساب مقصد. ⏳مدت زمان: ۱ روز کاری.",
                "نرخ روز"
            )
        ]

        for title, desc, details, price in payments:
            self.add_button(
                label=title,
                callback=ProductDetailMessage(navigation, title, desc, details, price, update_callback)
            )

        self.add_button(label="⬅️ بازگشت", callback=navigation.goto_back)
        self.add_button(label="🏠 خانه", callback=navigation.goto_home)

        if isinstance(update_callback, list):
            update_callback.append(self.app_update_display)

    async def app_update_display(self) -> None:
        edited = await self.edit_message()
        if edited:
            self.is_alive()

    def update(self) -> str:
        return "نوع پرداخت ارزی خود را انتخاب کنید:"


class ServicesMenuMessage(BaseMessage):
    LABEL = "خدمات ما 🛠️"

    def __init__(self, navigation: MyNavigationHandler, update_callback: Optional[List[Callable]] = None):
        super().__init__(navigation, ServicesMenuMessage.LABEL, notification=False)

        gift_card = GiftCardsMenuMessage(navigation, update_callback)
        accounts = AccountsMenuMessage(navigation, update_callback)
        payments = PaymentsMenuMessage(navigation, update_callback)

        self.add_button(label="💳 گیفت‌کارت‌ها", callback=gift_card)
        self.add_button(label="🏦 حساب‌های بین‌المللی", callback=accounts)
        self.add_button(label="💵 پرداخت‌های ارزی", callback=payments)
        self.add_button(label="✨ خدمات ویژه",callback=ProductDetailMessage(navigation,"خدمات ویژه","تبدیل درآمد، کارت مجازی و خدمات اختصاصی.","جزئیات خدمات ویژه به زودی اضافه می‌شود.","متغیر",update_callback))

        self.add_button(label="⬅️ بازگشت", callback=navigation.goto_back)
        self.add_button(label="🏠 خانه", callback=navigation.goto_home)

        if isinstance(update_callback, list):
            update_callback.append(self.app_update_display)

    async def app_update_display(self) -> None:
        edited = await self.edit_message()
        if edited:
            self.is_alive()

    def update(self) -> str:
        return "خدمات اصلی اصل‌پی را ببینید:" 


class LearningMenuMessage(BaseMessage):
    LABEL = "آموزش و راهنما 📚"

    def __init__(self, navigation: MyNavigationHandler, update_callback: Optional[List[Callable]] = None):
        super().__init__(navigation, LearningMenuMessage.LABEL, notification=False)
        self.add_button(label="آموزش خرید", callback=self.action_buy_guide)
        self.add_button(label="آموزش امنیت", callback=self.action_security_guide)
        self.add_button(label="⬅️ بازگشت", callback=navigation.goto_back)
        self.add_button(label="🏠 خانه", callback=navigation.goto_home)

        if isinstance(update_callback, list):
            update_callback.append(self.app_update_display)

    async def app_update_display(self) -> None:
        edited = await self.edit_message()
        if edited:
            self.is_alive()

    def update(self) -> str:
        return "راهنماها و نکات امنیتی را مطالعه کنید."

    def action_buy_guide(self, *args):
        return self.notify("برای خرید: سرویس موردنظر را انتخاب کنید → ثبت سفارش → ارسال اطلاعات پرداخت.")

    def action_security_guide(self, *args):
        return self.notify("نکته امنیتی: هرگز اطلاعات کامل کارت یا رمز یک‌‌بارمصرف را در چت عمومی ارسال نکنید.")


class ContactMenuMessage(BaseMessage):
    LABEL = "پشتیبانی 👤"

    def __init__(self, navigation: MyNavigationHandler, update_callback: Optional[List[Callable]] = None):
        super().__init__(navigation, ContactMenuMessage.LABEL, notification=False)
        self.add_button(label="ارسال پیام به پشتیبانی", callback=self.action_contact)
        self.add_button(label="تماس ادمین", callback=self.action_admin)
        self.add_button(label="⬅️ بازگشت", callback=navigation.goto_back)
        self.add_button(label="🏠 خانه", callback=navigation.goto_home)

        if isinstance(update_callback, list):
            update_callback.append(self.app_update_display)

    async def app_update_display(self) -> None:
        edited = await self.edit_message()
        if edited:
            self.is_alive()

    def update(self) -> str:
        return "راه‌های ارتباط با پشتیبانی را انتخاب کنید."

    def action_contact(self, *args):
        return self.notify("پیام شما به پشتیبانی ارسال شد. در ساعات کاری ظرف چند ساعت پاسخ خواهیم داد.")

    def action_admin(self, *args):
        return self.notify("برای تماس فوری: @AsllPayAdmin")


class StartMessage(BaseMessage):
    LABEL = "start"

    def __init__(self, navigation: MyNavigationHandler, message_args: Optional[List[Callable]] = None) -> None:
        super().__init__(navigation, StartMessage.LABEL)
        services = ServicesMenuMessage(navigation, message_args)
        learning = LearningMenuMessage(navigation, message_args)
        contact = ContactMenuMessage(navigation, message_args)

        self.add_button(label="آموزش و راهنما 📚", callback=learning)
        self.add_button(label="خدمات ما 🛠️", callback=services)
        self.add_button(label="پشتیبانی 👤", callback=contact)

        if isinstance(message_args, list):
            message_args.append(self.app_update_display)

    async def app_update_display(self) -> None:
        edited = await self.edit_message()
        if edited:
            self.is_alive()

    def update(self) -> str:
        return "🌍💳 Asll Pay | اصل پی 💳🌍\n\nبه ربات اصل‌پی خوش‌آمدید!\nخدمات را از منوی زیر انتخاب کنید."


def init_logger(current_logger) -> Logger:
    _packages: List[TypePackageLogger] = [
        {"package": "apscheduler", "level": logging.WARNING},
        {"package": "telegram_menu", "level": logging.DEBUG},
        {"package": current_logger, "level": logging.DEBUG},
    ]
    log_formatter = logging.Formatter(
        fmt="%(asctime)s [%(name)s] [%(levelname)s]  %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_formatter)
    _logger = logging.getLogger(current_logger)
    for _package in _packages:
        _logger = logging.getLogger(_package["package"])
        _logger.setLevel(_package["level"])
        _logger.addHandler(console_handler)
        _logger.propagate = False
    return _logger
