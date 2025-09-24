from telegram_menu import BaseMessage, TelegramMenuSession, NavigationHandler

API_KEY = "8182446297:AAFVGVfi12xhxDaqxpUPkHPPTxy5A5Cnmz4"

class StartMessage(BaseMessage):
    """Start menu, create all app sub-menus."""

    LABEL = "start"

    def __init__(self, navigation: NavigationHandler) -> None:
        """Init StartMessage class."""
        super().__init__(navigation, StartMessage.LABEL)

    def update(self) -> str:
        """Update message content."""
        return "Hello, world!"

TelegramMenuSession(API_KEY).start(StartMessage)



# import logging
# from telegram import Update
# from telegram.ext import Application, ApplicationBuilder, ContextTypes, CommandHandler


# logging.basicConfig(
#     format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
#     level=logging.INFO
# )

# async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     await context.bot.send_message(chat_id=update.effective_chat.id, text="I'm a bot, please talk to me!")

# if __name__ == '__main__':
#     # application = ApplicationBuilder().token(API_KEY).build()
#     application = Application.builder().token(API_KEY).build()
    
#     scheduler = application.job_queue.scheduler
#     start_handler = CommandHandler('start', start)
#     application.add_handler(start_handler)
    
#     application.run_polling()
#     print(scheduler.__dict__)
#     scheduler.start()
    
    