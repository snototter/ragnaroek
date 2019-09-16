#!/usr/bin/python
# coding=utf-8

"""
Telegram bot helheimr - controlling and querying our heating system.

Commands (formating for @botfather):
status - Statusabfrage
on - :sunny: Heizung einschalten
off - :snowflake: Heizung ausschalten
forecast - :partly_sunny: Wettervorhersage
details - Detaillierte Systeminformation
config - Heizungsprogramm einrichten
shutdown - System herunterfahren
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
#TODO botfather & help: heizung ein = thermo emo statt sonne
#TODO botfather cmd aktualisieren
#TODO Unicode: black circle, medium black circle, bullet: \u23fa \u25cf \u2022
#TODO als service einrichten (python venv?)
#TODO forecast icons (w.get_weather_code(), weather condition codes, check emoji, make mapping)
#TODO altmannschalter aktivieren fuer tepidarium (braucht wireshark session)
#TODO reminder alle config minuten, falls heizung laeuft (zB 12h)
#TODO shutdown: raspberry herunterfahren!

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


def format_details_plug_states(plug_states, use_markdown=True, detailed_information=True):
    return '\n\u2022 ' + '\n\u2022 '.join([plug.format_message(use_markdown=use_markdown, detailed_information=detailed_information) for plug in plug_states])


def format_msg_heating(is_heating, plug_states, use_markdown=True, use_emoji=True, include_state_details=False):
    if is_heating is None:
        return '{}{}Fehler{} beim Abfragen der Heizung!'.format(
                ':bangbang: ' if use_emoji else '',
                '*' if use_markdown else '',
                '*' if use_markdown else ''
            )

    txt = '{}Heizung{} ist {}{}'.format(
            '*' if use_markdown else '',
            '*' if use_markdown else '',
            'ein' if is_heating else 'aus',
            ('.' if not include_state_details else ':') if not use_emoji else (' :sunny:' if is_heating else ' :snowman:')
        )
    # #TODO later on, I probably only want to know the states if the plug states differ:
    # include_state_details = False
    # for i in range(1, len(plug_states)):
    #     if plug_states[i].on != plug_states[i-1].on:
    #         include_state_details = True
    #         break
    if include_state_details:
        txt += format_details_plug_states(plug_states, use_markdown, include_state_details)
    return txt


def format_msg_temperature(sensor_states, use_markdown=True, use_emoji=True, include_state_details=False):
    if sensor_states is None:
        return '{}{}Fehler{} beim Abfragen der Thermometer!'.format(
                ':bangbang: ' if use_emoji else '',
                '*' if use_markdown else '',
                '*' if use_markdown else ''
            )
    return '{}Aktuelle Temperatur:{}\n\u2022 {}'.format(
            '*' if use_markdown else '',
            '*' if use_markdown else '',
            '\n\u2022 '.join([st.format_message(use_markdown=use_markdown, detailed_information=include_state_details) for st in sensor_states]))

#######################################################################
# Main bot workflow
class HelheimrBot:
    WAIT_TIME_HEATING_TOGGLE = 3

    CALLBACK_TURN_ON_OFF_CANCEL = '0'
    CALLBACK_TURN_ON_CONFIRM = '1'
    CALLBACK_TURN_OFF_CONFIRM = '2'
    CALLBACK_CONFIG_CANCEL = '3'
    CALLBACK_CONFIG_CONFIRM = '4'


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
        self.logger.info('HelheimrBot querying myself: {}'.format(self.bot.get_me()))
        
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

        shutdown_handler = CommandHandler('shutdown', self.cmd_shutdown, self.user_filter)
        self.dispatcher.add_handler(shutdown_handler)

        cfg_handler = CommandHandler('config', self.cmd_configure, self.user_filter)
        self.dispatcher.add_handler(cfg_handler)

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
        # Start polling messages from telegram servers
        self.updater.start_polling(poll_interval=self.poll_interval,
            timeout=self.timeout, bootstrap_retries=self.bootstrap_retries)
        # Send startup message to all authorized users
        status_txt = self.query_status(None)
        self.broadcast_message("Hallo, ich bin online. {:s}\n\n{:s}".format(
                    _rand_flower(), status_txt))


    def broadcast_message(self, txt):
        """Send given message to all authorized chat IDs."""
        for chat_id in self.authorized_ids:
            self.bot.send_message(chat_id=chat_id, 
                text=hu.emo(txt),
                parse_mode=telegram.ParseMode.MARKDOWN)
            

    def idle(self):
        """Blocking call to run the updater's event loop."""
        self.updater.idle()


    def _shutdown(self): 
        # Should be run from a different thread (https://github.com/python-telegram-bot/python-telegram-bot/issues/801)
        self.updater.stop()
        self.updater.is_idle = False

    def _shutdown_controller(self):
        # Should be run from a different thread
        time.sleep(3)
        self.controller.shutdown()


    def cmd_shutdown(self, update, context):
        threading.Thread(target=self._shutdown_controller, daemon=True).start()


    def stop(self):
        if not self.shutdown_message_sent:
            self.shutdown_message_sent = True
            # Send shutdown message
            for chat_id in self.authorized_ids:
                # Send startup message to all authorized users
                status_txt = self.query_status(None)
                self.bot.send_message(chat_id=chat_id, 
                    text=hu.emo("System wird heruntergefahren, bis bald.\n\n{:s}".format(
                        status_txt)),
                    parse_mode=telegram.ParseMode.MARKDOWN)
            threading.Thread(target=self._shutdown).start()


    def cmd_help(self, update, context):
        txt = """*Liste verfügbarer Befehle:*
/status - Statusabfrage.

/on - :sunny: Heizung einschalten.
  nur Temperatur: /on `21.7c`
  Hysterese: /on `21c` `1c`
  nur Heizdauer: /on `1.5h`
  Temperatur und Dauer: /on `23c` `2h`
  Alles: /on `22c` `0.5c` `1.5h`

/off - :snowflake: Heizung ausschalten.
/forecast - :partly_sunny: Wettervorhersage.
/details - Detaillierte Systeminformation.

/config - Heizungsprogramm einstellen.
  Uhrzeit + Dauer: /config 6:00 2h
  Zusätzlich Temperatur: /config 6:00 23c 2h
  Zusätzlich Hysterese: /config 6:00 20c 0.5c 3h

/shutdown - System herunterfahren.
/help - Diese Hilfemeldung."""
        context.bot.send_message(chat_id=update.message.chat_id, text=hu.emo(txt),
            parse_mode=telegram.ParseMode.MARKDOWN)

    
    def cmd_start(self, update, context):
        context.bot.send_message(chat_id=update.message.chat_id, 
            text=hu.emo("Hallo! {:s}\n\n/help zeigt dir eine Liste verfügbarer Befehle an.".format(_rand_flower())))


    def query_status(self, chat_id, detailed_report=False):
        # Query heating status
        is_heating, plug_states = self.controller.query_heating_state()
        txt = format_msg_heating(is_heating, plug_states, 
            use_markdown=type(self).USE_MARKDOWN, 
            use_emoji=type(self).USE_EMOJI,
            include_state_details=detailed_report)

        # Query temperatures
        sensors = self.controller.query_temperature()
        txt += '\n\n' + format_msg_temperature(sensors,
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
        context.bot.send_chat_action(chat_id=update.message.chat_id, action=telegram.ChatAction.TYPING)
        txt = self.controller.query_detailed_status()
        context.bot.send_message(
            chat_id=update.message.chat_id, 
            text=hu.emo(txt), 
            parse_mode=telegram.ParseMode.MARKDOWN)
        #self.query_status(update.message.chat_id, detailed_report=True)


    def cmd_on(self, update, context):
        # Check if another user is currently sending an on/off command:
        if self.is_modifying_heating:
            context.bot.send_message(chat_id=update.message.chat_id, 
                text='Heizungsstatus wird gerade von einem anderen Chat geändert.\n\nBitte versuche es in ein paar Sekunden nochmal.',
                parse_mode=telegram.ParseMode.MARKDOWN)
            return
        self.is_modifying_heating = True # Set flag to prevent other users from concurrently modifying heating

        # Check if already heating
        is_heating, plug_states = self.controller.query_heating_state()

        if is_heating:
            self.is_modifying_heating = False
            txt = '*Heizung* läuft schon :sunny:\n' + format_details_plug_states(plug_states, use_markdown=True, detailed_information=False)
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


    def cmd_off(self, update, context):
        # Check if another user is currently sending an on/off command:
        if self.is_modifying_heating:
            self.bot.send_message(chat_id=update.message.chat_id, 
                text='Heizungsstatus wird gerade von einem anderen Chat geändert.\nBitte versuche es in ein paar Sekunden nochmal.',
                parse_mode=telegram.ParseMode.MARKDOWN)
            return

        # Check if already off
        is_heating, plug_states = self.controller.query_heating_state()
        if not is_heating:
            self.bot.send_message(chat_id=update.message.chat_id, 
                text=hu.emo('Heizung ist schon *aus* :snowman:\n' + format_details_plug_states(plug_states, use_markdown=True, detailed_information=False)),
                parse_mode=telegram.ParseMode.MARKDOWN)
        else:
            self.is_modifying_heating = True # Set flag to prevent other users from concurrently modifying heating
            keyboard = [[telegram.InlineKeyboardButton("Ja, sicher!", callback_data=type(self).CALLBACK_TURN_OFF_CONFIRM + ':' + ':'.join(context.args)),
                 telegram.InlineKeyboardButton("Nein", callback_data=type(self).CALLBACK_TURN_ON_OFF_CANCEL)]]

            reply_markup = telegram.InlineKeyboardMarkup(keyboard)
            update.message.reply_text('Heizung wirklich ausschalten?', reply_markup=reply_markup)


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
            hysteresis = 0.5
            duration = None
            for idx in range(1, len(tokens)):
                t = tokens[idx].lower()
                if t.endswith('c'): # Temperature
                    val = float(t[:-1].replace(',','.'))
                    # The first ##c sets the temperature, the second ##c sets the hysteresis
                    if temperature is None:
                        temperature = val
                    else:
                        hysteresis = val
                elif t.endswith('h'):
                    h = float(t[:-1].replace(',','.'))
                    hours = int(h)
                    minutes = int((h - hours) * 60)
                    duration = datetime.timedelta(hours=hours, minutes=minutes)

            
            success, txt = self.controller.turn_on_manually(target_temperature=temperature,
                temperature_hysteresis=hysteresis,
                duration=duration,
                created_by=query.from_user.first_name)
            if not success:
                query.edit_message_text(text=hu.emo(':bangbang: Fehler: ' + txt))
            else:
                query.edit_message_text(text='Wird erledigt...')
                context.bot.send_chat_action(chat_id=query.from_user.id, action=telegram.ChatAction.TYPING)
                time.sleep(type(self).WAIT_TIME_HEATING_TOGGLE)
                status_txt = self.query_status(None)
                query.edit_message_text(text=hu.emo(status_txt), parse_mode=telegram.ParseMode.MARKDOWN)
            self.is_modifying_heating = False

        elif response == type(self).CALLBACK_TURN_OFF_CONFIRM:
            success, txt = self.controller.turn_off_manually(query.from_user.first_name)
            if not success:
                query.edit_message_text(text='Fehler, konnte Heizung nicht ausschalten:\n\n' + txt)
            else:
                query.edit_message_text(text='Wird erledigt...')
                context.bot.send_chat_action(chat_id=query.from_user.id, action=telegram.ChatAction.TYPING)
                time.sleep(type(self).WAIT_TIME_HEATING_TOGGLE)
                status_txt = self.query_status(None)
                query.edit_message_text(text=hu.emo(status_txt), parse_mode=telegram.ParseMode.MARKDOWN)
            self.is_modifying_heating = False


    def cmd_configure(self, update, context):
        at_time = None
        temperature = None
        hysteresis = None
        duration = None
        for a in context.args:
            if a[-1] == 'c':
                val = float(a[:-1].replace(',','.'))
                if temperature is None:
                    temperature = val
                else:
                    hysteresis = val
            elif ':' in a:
                at_time = a
            elif a[-1] == 'h':
                h = float(a[:-1].replace(',','.'))
                hours = int(h)
                minutes = int((h - hours) * 60)
                duration = datetime.timedelta(hours=hours, minutes=minutes)
        #TODO make callback!!! CALLBACK_CONFIG_CANCEL CALLBACK_CONFIG_CONFIRM!!!
        context.bot.send_message(chat_id=update.message.chat_id, text='Korrekt? Um {}, {}°+/-{}° für {}'.format(at_time, temperature, hysteresis, duration))

    def cmd_forecast(self, update, context):
        try:
            forecast = self.controller.query_weather_forecast()
            if forecast is None:
                context.bot.send_message(chat_id=update.message.chat_id, text=hu.emo(
                    ':bangbang: *Fehler* beim Abfragen des Wetterberichts. Log überprüfen!'
                    ),parse_mode=telegram.ParseMode.MARKDOWN)
            else:
                context.bot.send_message(chat_id=update.message.chat_id, text=hu.emo(
                    forecast.format_message(use_markdown=True, use_emoji=True)),
                    parse_mode=telegram.ParseMode.MARKDOWN)
        except:
            # This will be a formating error (maybe some fields were not set, etc.)
            # I keep this exception handling as long as I don't know what pyowm returns exactly for every weather condition
            err_msg = traceback.format_exc()
            logging.getLogger().error('Error while querying weather report/forecast:\n' + err_msg)
            context.bot.send_message(chat_id=update.message.chat_id, text='Fehler während der Wetterabfrage:\n\n' + err_msg)



    def cmd_unknown(self, update, context):
        if update.message.chat_id in self.authorized_ids:
            context.bot.send_message(chat_id=update.message.chat_id, text=hu.emo("Das habe ich nicht verstanden. :thinking_face:"))
        else:
            logging.getLogger().warn('Unauthorized access: by {} {} (user {}, id {})'.format(update.message.chat.first_name, update.message.chat.last_name, update.message.chat.username, update.message.chat_id))
            context.bot.send_message(chat_id=update.message.chat_id, text=hu.emo("Hallo {} ({}), du bist (noch) nicht autorisiert. :flushed_face:").format(update.message.chat.first_name, update.message.chat_id))


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


# if __name__ == '__main__':
#     main()
