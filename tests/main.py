#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Copyright Mahdi Gilany
#

"""telegram_menu demonstrator."""

from pathlib import Path

from telegram_menu import TelegramMenuSession
from tests.asll_pay_menu import MyNavigationHandler, StartMessage, init_logger

import os
from dotenv import load_dotenv

load_dotenv()

api_key = "8182446297:AAFVGVfi12xhxDaqxpUPkHPPTxy5A5Cnmz4"

def run() -> None:
    """Run the demo example."""
    logger = init_logger(__name__)

    logger.info(" >> Start the demo and wait forever, quit with CTRL+C...")
    session = TelegramMenuSession(api_key) 
    session.start(start_message_class=StartMessage, navigation_handler_class=MyNavigationHandler)


if __name__ == "__main__":
    run()
