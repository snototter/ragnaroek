#!/usr/bin/env python
"""
Telegram bot helheimr - controlling and querying our heating system.

Commands (formating for @botfather):
status - Statusabfrage
on - :sunny: Heizung einschalten
off - :snowflake: Heizung ausschalten
forecast - :partly_sunny: Wettervorhersage
details - Sehr detaillierte Statusmeldung
help - Liste verfügbarer Befehle
"""

# import argparse
# import os
# import sys
import datetime
import time
import traceback
import threading

#TODOs:
#TODO use logging
#TODO als service einrichten (python venv?)
#TODO forecast icons (w.get_weather_code(), weather condition codes, check emoji, make mapping)
#TODO update1: wird erledigt ... (...), sleep, update2  Status
#TODO temperature mapping < 8, 8-18, 18-28, 28+
#TODO pair temperature sensor
#TODO sicher j/n
#TODO laeuft schon...
#TODO altmannschalter aktivieren fuer tepidarium (braucht wireshark session)
#TODO deconz poll (timer + bei /status bzw nach /on, /off)
#TODO reminder alle config minuten, falls heizung laeuft (zB 12h)
#TODO gpio pins auslesen - raspbee hardware test ist nicht moeglich. alternative: deconz/phoscon sw check
#TODO status abfrage deconz: https://dresden-elektronik.github.io/deconz-rest-doc/configuration/#getfullstate

#TODO restart bot https://github.com/python-telegram-bot/python-telegram-bot/wiki/Code-snippets#simple-way-of-restarting-the-bot

# Telegram emojis: 
# https://github.com/carpedm20/emoji/blob/master/emoji/unicode_codes.py
# https://k3a.me/telegram-emoji-list-codes-descriptions/
# hibiscus
# fire
# sign_of_the_horns
# tulip
# rose
# wilted_flower
# cherry_blossom

import helheimr_utils as hu
import helheimr_weather as hw

import logging
import random
import telegram
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackQueryHandler

def _rand_flower():
    return random.choice([':sunflower:', ':hibiscus:', ':tulip:', ':rose:', ':cherry_blossom:'])

#######################################################################
# Main bot workflow
class HelheimrBot:
    WAIT_TIME_HEATING_TOGGLE = 3

    CALLBACK_TURN_ON_OFF_CANCEL = '0'
    CALLBACK_TURN_ON_CONFIRM = '2'
    CALLBACK_TURN_OFF_CONFIRM = '4'

    USE_MARKDOWN = True
    USE_EMOJI = True

    def __init__(self, bot_cfg, controller):
        self.controller = controller # The controller takes care of "everything" (turn heating on/off, query states/weather, etc.)

        # Telegram API configuration
        self.api_token = bot_cfg['telegram']['api_token']
        self.poll_interval = bot_cfg['telegram']['poll_interval']
        self.timeout = bot_cfg['telegram']['timeout']
        self.bootstrap_retries = bot_cfg['telegram']['bootstrap_retries']

        # Who is allowed to text me?
        self.authorized_ids = bot_cfg['telegram']['authorized_ids']

        self.logger = logging.getLogger()
        self.logger.info('HelheimrBot is accepting connections from chat IDs: {}'.format(','.join(map(str, self.authorized_ids))))


        self.is_modifying_heating = False # Indicate that one user currently wants to change something
        self.shutdown_message_sent = False

        self.updater = Updater(token=self.api_token, use_context=True)
        self.dispatcher = self.updater.dispatcher

        # Test telegram token/connection
        self.bot = self.updater.bot
        self.logger.info('HelheimrBot querying myself:\n{}'.format(self.bot.get_me()))
        
        #######################################################################
        # Register command handlers
        self.user_filter = Filters.user(user_id=self.authorized_ids)

        start_handler = CommandHandler('start', self.cmd_start, self.user_filter)
        self.dispatcher.add_handler(start_handler)

        help_handler = CommandHandler('help', self.cmd_help, self.user_filter)
        self.dispatcher.add_handler(help_handler)

        status_handler = CommandHandler('status', self.cmd_status, self.user_filter)
        self.dispatcher.add_handler(status_handler)

        detail_handler = CommandHandler('details', self.cmd_details, self.user_filter)
        self.dispatcher.add_handler(detail_handler)

        on_handler = CommandHandler('on', self.cmd_on, self.user_filter)
        self.dispatcher.add_handler(on_handler)

        off_handler = CommandHandler('off', self.cmd_off, self.user_filter)
        self.dispatcher.add_handler(off_handler)

        # Callback handler to provide inline keyboard (user must confirm/cancel on/off/etc. commands)
        self.dispatcher.add_handler(CallbackQueryHandler(self.callback_handler))

        forecast_handler = CommandHandler('forecast', self.cmd_forecast, self.user_filter)
        self.dispatcher.add_handler(forecast_handler)

        # Filter unknown commands and text!
        unknown_handler = MessageHandler(Filters.command, self.cmd_unknown, self.user_filter)
        self.dispatcher.add_handler(unknown_handler)
        unknown_handler = MessageHandler(Filters.text, self.cmd_unknown, self.user_filter)
        self.dispatcher.add_handler(unknown_handler)


    def start(self):
        self.updater.start_polling(poll_interval=self.poll_interval,
            timeout=self.timeout, bootstrap_retries=self.bootstrap_retries)

        for chat_id in self.authorized_ids:
            # Send startup message to all authorized users
            status_txt = self.query_status(None)
            self.bot.send_message(chat_id=chat_id, 
                text=hu.emo("Hallo, ich bin online. {:s}\n\n{:s}".format(
                    _rand_flower(), status_txt)),
                parse_mode=telegram.ParseMode.MARKDOWN)
            

    def idle(self):
        """Blocking call to run the updater's event loop."""
        self.updater.idle()


    def _shutdown(self): # Should be run from a different thread (https://github.com/python-telegram-bot/python-telegram-bot/issues/801)
        self.updater.stop()
        self.updater.is_idle = False


    def stop(self):
        if not self.shutdown_message_sent:
            self.shutdown_message_sent = True
            # Send shutdown message
            for chat_id in self.authorized_ids:
                # Send startup message to all authorized users
                status_txt = self.query_status(None)
                self.bot.send_message(chat_id=chat_id, 
                    text=hu.emo("Ich werde ausgeschalten, bis bald. {:s}\n\n{:s}".format(
                        _rand_flower(), status_txt)),
                    parse_mode=telegram.ParseMode.MARKDOWN)
            threading.Thread(target=self._shutdown).start()


    def cmd_help(self, update, context):
        txt = """*Liste verfügbarer Befehle:*\n\n  /status - Statusabfrage.\n
  /on - :sunny: Heizung einschalten.\n
  /off - :snowflake: Heizung ausschalten.\n\n
  /forecast - :partly_sunny: Wettervorhersage.\n
  /details - Sehr detaillierte Statusmeldung.\n
  /help - Diese Hilfemeldung."""
        context.bot.send_message(chat_id=update.message.chat_id, text=hu.emo(txt),
            parse_mode=telegram.ParseMode.MARKDOWN)

    
    def cmd_start(self, update, context):
        context.bot.send_message(chat_id=update.message.chat_id, 
            text=hu.emo("Hallo! {:s}\n\n/help zeigt dir eine Liste verfügbarer Befehle an.".format(_rand_flower())))


    def query_status(self, chat_id, detailed_report=False):
        # Query heating status
        is_heating, plug_states = self.controller.query_heating_state()
        txt = hu.format_msg_heating(is_heating, plug_states, 
            use_markdown=type(self).USE_MARKDOWN, 
            use_emoji=type(self).USE_EMOJI,
            include_state_details=detailed_report)

        # Query temperatures
        sensors = self.controller.query_temperature()
        txt += '\n\n' + hu.format_msg_temperature(sensors,
            use_markdown=type(self).USE_MARKDOWN, 
            use_emoji=type(self).USE_EMOJI,
            include_state_details=detailed_report)

        if chat_id is None:
            return txt
        else:
            self.bot.send_message(chat_id=chat_id, text=hu.emo(txt),
                parse_mode=telegram.ParseMode.MARKDOWN)


    def cmd_status(self, update, context):
        self.query_status(update.message.chat_id)


    def cmd_details(self, update, context):
        self.query_status(update.message.chat_id, detailed_report=True)


    def cmd_on(self, update, context):#FIXME
        logging.getLogger().info('TODO parse message args: add to response + special delimiter {}'.format('\n'.join(context.args)))
        # Check if another user is currently sending an on/off command:
        if self.is_modifying_heating:
            self.context.bot.send_message(chat_id=update.message.chat_id, 
                text='Heizungsstatus wird gerade von einem anderen Chat geändert.\n\nBitte versuche es in ein paar Sekunden nochmal.',
                parse_mode=telegram.ParseMode.MARKDOWN)
            return
        self.is_modifying_heating = True # Set flag to prevent other users from concurrently modifying heating

        # Check if already heating
        is_heating, plug_states = self.controller.query_heating_state()

        if is_heating:
            self.is_modifying_heating = False
            txt = '*Heizung* läuft schon :sunny:\n' + hu.format_details_plug_states(plug_states)
            context.bot.send_message(
                chat_id=update.message.chat_id, 
                text=hu.emo(txt), 
                parse_mode=telegram.ParseMode.MARKDOWN)
        else:
            # If not, ask for confirmation
            # self.is_modifying_heating = True # Set flag to prevent other users from concurrently modifying heating
            keyboard = [[telegram.InlineKeyboardButton("Ja, sicher!", 
                    callback_data=type(self).CALLBACK_TURN_ON_CONFIRM + ':' + ':'.join(context.args)),
                 telegram.InlineKeyboardButton("Nein", callback_data=type(self).CALLBACK_TURN_ON_OFF_CANCEL)]]

            reply_markup = telegram.InlineKeyboardMarkup(keyboard)
            update.message.reply_text('Heizung wirklich einschalten?', reply_markup=reply_markup)


    def cmd_off(self, update, context):#FIXME
        # Check if another user is currently sending an on/off command:
        if self.is_modifying_heating:
            self.bot.send_message(chat_id=update.message.chat_id, 
                text='Heizungsstatus wird gerade von einem anderen Chat geändert.\nBitte versuche es in ein paar Sekunden nochmal.',
                parse_mode=telegram.ParseMode.MARKDOWN)
            return

        # Check if already off
        is_heating, status = self.controller.query_heating_state()
        if not is_heating:
            self.bot.send_message(chat_id=update.message.chat_id, 
                text=hu.emo('Heizung ist schon *aus* :snowman:\n' + '\n'.join(map(str, status))),
                parse_mode=telegram.ParseMode.MARKDOWN)
        else:
            self.is_modifying_heating = True # Set flag to prevent other users from concurrently modifying heating
            keyboard = [[telegram.InlineKeyboardButton("Ja, sicher!", callback_data=type(self).CALLBACK_TURN_OFF_CONFIRM + ':' + ':'.join(context.args)),
                 telegram.InlineKeyboardButton("Nein", callback_data=type(self).CALLBACK_TURN_ON_OFF_CANCEL)]]

            reply_markup = telegram.InlineKeyboardMarkup(keyboard)
            update.message.reply_text('Heizung wirklich ausschalten?', reply_markup=reply_markup)

#TODO cmd_details plug+reachable, sensors+battery
    def callback_handler(self, update, context):
        query = update.callback_query
        tokens = query.data.split(':')
        response = tokens[0]
        
        if response == type(self).CALLBACK_TURN_ON_OFF_CANCEL:
            query.edit_message_text(text='Ok, dann ein andermal.')
            self.is_modifying_heating = False

        elif response == type(self).CALLBACK_TURN_ON_CONFIRM:
            # Parse optional parameters
            temperature = None
            duration = None
            for idx in range(1, len(tokens)):
                t = tokens[idx].lower()
                if t.endswith('c'): # Temperature
                    temperature = float(t[:-1])
                elif t.endswith('h'):
                    h = float(t[:-1])
                    hours = int(h)
                    minutes = int((h - hours) * 60)
                    duration = datetime.timedelta(hours=hours, minutes=minutes)
                    #FIXME document in help and botfather!
            
            #FIXME params
            success, txt = self.controller.turn_on_manually()
            if not success:
                query.edit_message_text(text=hu.emo(':bangbang: Fehler, konnte Heizung nicht eingeschaltet werden:\n\n' + txt))
            else:
                query.edit_message_text(text='Wird erledigt...TODO"{}", "{}"'.format(temperature, duration))
                context.bot.send_chat_action(chat_id=query.from_user.id, action=telegram.ChatAction.TYPING)
                time.sleep(type(self).WAIT_TIME_HEATING_TOGGLE)
                status_txt = self.query_status(None)
                query.edit_message_text(text=hu.emo(status_txt), parse_mode=telegram.ParseMode.MARKDOWN)
            self.is_modifying_heating = False

        elif response == type(self).CALLBACK_TURN_OFF_CONFIRM:
            #FIXME params
            success, txt = self.controller.turn_off_manually()
            if not success:
                query.edit_message_text(text='Fehler, konnte Heizung nicht ausschalten:\n\n' + txt)
            else:
                query.edit_message_text(text='Wird erledigt...')
                context.bot.send_chat_action(chat_id=query.from_user.id, action=telegram.ChatAction.TYPING)
                time.sleep(type(self).WAIT_TIME_HEATING_TOGGLE)
                status_txt = self.query_status(None)
                query.edit_message_text(text=status_txt, parse_mode=telegram.ParseMode.MARKDOWN)
            self.is_modifying_heating = False


    def cmd_forecast(self, update, context):
        #FIXME
        try:
            forecast = self.controller.query_weather_forecast()
            # forecast = self.weather_forecast.query()
            context.bot.send_message(chat_id=update.message.chat_id, text=hu.emo(forecast),
                parse_mode=telegram.ParseMode.MARKDOWN)
        except:
            err_msg = traceback.format_exc()
            context.bot.send_message(chat_id=update.message.chat_id, text='Fehler während der Wetterabfrage:\n\n' + err_msg)



    def cmd_unknown(self, update, context):
        if update.message.chat_id in self.authorized_ids:
            context.bot.send_message(chat_id=update.message.chat_id, text=hu.emo("Das habe ich nicht verstanden. :thinking:"))
        else:
            logging.getLogger().warn('Unauthorized access: by {} {} (user {}, id {})'.format(update.message.chat.first_name, update.message.chat.last_name, update.message.chat.username, update.message.chat_id))
            context.bot.send_message(chat_id=update.message.chat_id, text=hu.emo("Hallo {} ({}), du bist (noch) nicht autorisiert. :flushed:").format(update.message.chat.first_name, update.message.chat_id))


# def main():
#     logging.basicConfig(level=logging.INFO, #logging.DEBUG,
#                     format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        
#     ctrl_cfg = hu.load_configuration('configs/ctrl.cfg')
#     deconz_wrapper = hr.RaspBeeWrapper(ctrl_cfg)

#     weather_cfg = hu.load_configuration('configs/owm.cfg')
#     weather_forecast = hw.WeatherForecastOwm(weather_cfg)

#     bot_cfg = hu.load_configuration('configs/bot.cfg')
    
#     bot = HelheimrBot(bot_cfg, deconz_wrapper, weather_forecast)
#     bot.start()
#     bot.idle()
#     #TODO support: /schedule (list scheduled tasks, save to disk, load from disk)


# if __name__ == '__main__':
#     main()
