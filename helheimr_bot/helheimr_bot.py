#!/usr/bin/env python
"""
Telegram bot helheimr - controlling and querying our heating system.

Commands (for @botfather):
status - Report heater status.
on - Turn on heating.
off - Turn off heating.
help - List all commands.
"""

# import argparse
# import os
# import sys

#TODOs:
#TODO use logging
#TODO altmannschalter aktivieren fuer tepidarium (geht das via requests?)
#TODO deconz poll (timer + bei /status bzw nach /on, /off)
#TODO reminder alle config minuten, falls heizung laeuft (zB 12h)
#TODO plug mapping: tepidarium: (HTepidarium, human-readable Tepidarium), flat: (HWohnung, Wohnung)

import helheimr_utils as hu
import helheimr_deconz as hd

from emoji import emojize
import logging
import telegram
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters



#######################################################################
# Main bot workflow
class HelheimrBot:
    def __init__(self, api_token, authorized_ids, deconz_wrapper):
        self.api_token = api_token
        self.deconz_wrapper = deconz_wrapper
        # TODO check tulip, hibiscus, etc. https://k3a.me/telegram-emoji-list-codes-descriptions/

        self.bot = telegram.Bot(token=self.api_token)
        logging.getLogger().info(self.bot.get_me())

        self.updater = Updater(token=api_token, use_context=True)
        self.dispatcher = self.updater.dispatcher
        self.authorized_ids = authorized_ids
        self.user_filter = Filters.user(user_id=authorized_ids)

        
        start_handler = CommandHandler('start', self.cmd_start, self.user_filter)
        self.dispatcher.add_handler(start_handler)

        help_handler = CommandHandler('help', self.cmd_help, self.user_filter)
        self.dispatcher.add_handler(help_handler)

        status_handler = CommandHandler('status', self.cmd_status, self.user_filter)
        self.dispatcher.add_handler(status_handler)

        on_handler = CommandHandler('on', self.cmd_on, self.user_filter)
        self.dispatcher.add_handler(on_handler)

        off_handler = CommandHandler('off', self.cmd_off, self.user_filter)
        self.dispatcher.add_handler(off_handler)

        unknown_handler = MessageHandler(Filters.command, self.cmd_unknown, self.user_filter)
        self.dispatcher.add_handler(unknown_handler)

        unknown_handler = MessageHandler(Filters.text, self.cmd_unknown, self.user_filter)
        self.dispatcher.add_handler(unknown_handler)


    def start(self):
        self.updater.start_polling()
        for chat_id in self.authorized_ids:
            # Send startup message to all authorized users
            self.bot.send_message(chat_id=chat_id, text=emojize("I'm online. :sunflower:", use_aliases=True))
            

    def idle(self):
        self.updater.idle()


    def cmd_help(self, update, context):
        context.bot.send_message(chat_id=update.message.chat_id, text="*The following commands are known:*\n\n"
            "/status - Report heater status.\n"
            "/help - Show this help message.",
            parse_mode=telegram.ParseMode.MARKDOWN)

    
    def cmd_start(self, update, context):
        context.bot.send_message(chat_id=update.message.chat_id, text=emojize("I'm online. :blossom:", use_aliases=True))


    def cmd_status(self, update, context):
        status = self.deconz_wrapper.query_heating()
        txt = "*Heating:*\n" + '\n'.join(map(str, status))
        context.bot.send_message(chat_id=update.message.chat_id, text=txt,
            parse_mode=telegram.ParseMode.MARKDOWN)


    def cmd_on(self, update, context):
        self.deconz_wrapper.turn_on()
        self.cmd_status(update, context)


    def cmd_off(self, update, context):
        self.deconz_wrapper.turn_off()
        self.cmd_status(update, context)


    def cmd_unknown(self, update, context):
        if update.message.chat_id in self.authorized_ids:
            context.bot.send_message(chat_id=update.message.chat_id, text="Sorry, I didn't understand that command.")
        else:
            logging.getLogger().warn('Unauthorized access: by {} {} (user {}, id {})'.format(update.message.chat.first_name, update.message.chat.last_name, update.message.chat.username, update.message.chat_id))
            context.bot.send_message(chat_id=update.message.chat_id, text="Sorry, {} ({}) you're not authorized.".format(update.message.chat.first_name, update.message.chat_id))


def main():
    logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    api_token_telegram, api_token_deconz = hu.load_api_token()
    authorized_ids = hu.load_authorized_user_ids()
    config = hu.load_configuration()

    logger = logging.getLogger()
    logger.info('Authorized chat IDs: {}'.format(authorized_ids))
    logger.debug(config)
    deconz_wrapper = hd.DeconzWrapper(api_token_deconz, config)

    bot = HelheimrBot(api_token_telegram, authorized_ids, deconz_wrapper)
    bot.start()
    bot.idle()

    


if __name__ == '__main__':
    main()