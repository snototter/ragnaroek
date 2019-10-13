#!/usr/bin/python
# coding=utf-8

"""
Telegram bot helheimr - controlling and querying our heating system.

Commands (formating for @botfather):

status - Statusabfrage
on - :high_brightness: Heizung einschalten
once - :high_brightness: Einmalig aufheizen
off - :snowflake: Heizung ausschalten
weather - :partly_sunny: Wetterbericht
details - Detaillierte Systeminformation
config - Heizungsprogramm einrichten
shutdown - System herunterfahren
help - Liste verfügbarer Befehle
"""


import datetime
import logging
import random
import telegram
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackQueryHandler
import traceback
import threading
import time

from . import common
from . import heating
from . import network_utils
from . import scheduling
from . import time_utils
from . import weather

#TODOs:
#TODO Unicode: black circle, medium black circle, bullet: \u23fa \u25cf \u2022
#TODO forecast icons (w.get_weather_code(), weather condition codes, check emoji, make mapping)
#TODO altmannschalter aktivieren fuer tepidarium (braucht wireshark session)
#TODO reminder alle config minuten, falls heizung laeuft (zB 12h)

# List of telegram emojis: 
# https://github.com/carpedm20/emoji/blob/master/emoji/unicode_codes.py
# https://k3a.me/telegram-emoji-list-codes-descriptions/


#FIXME for rewrite we need to adjust weather and co...
# from . import weather as hw



def _rand_flower():
    """Return a random flower emoji."""
    return random.choice([':sunflower:', ':hibiscus:', ':tulip:', ':rose:', ':cherry_blossom:'])


def _format_details_plug_states(plug_states, use_markdown=True, detailed_information=True):
    return '\n\u2022 ' + '\n\u2022 '.join([plug.format_message(use_markdown=use_markdown, detailed_information=detailed_information) for plug in plug_states])


def _format_msg_heating(is_heating, plug_states, use_markdown=True, use_emoji=True, include_state_details=False):
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
            ('.' if not include_state_details else ':') if not use_emoji else (' :thermometer:' if is_heating else ' :snowman:')
        )
    # #TODO later on, I probably only want to know the states if the plug states differ:
    # include_state_details = False
    # for i in range(1, len(plug_states)):
    #     if plug_states[i].on != plug_states[i-1].on:
    #         include_state_details = True
    #         break
    if include_state_details:
        txt += _format_details_plug_states(plug_states, use_markdown, include_state_details)
    return txt


def _format_msg_temperature(sensor_states, use_markdown=True, use_emoji=True, include_state_details=False):
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
    WAIT_TIME_HEATING_TOGGLE = 1.5  # Time to wait after turning heating on/off before checking the heating state (to see if it actually responded)

    # Identifiers used in message callbacks
    CALLBACK_TURN_ON_OFF_CANCEL = '0'
    CALLBACK_TURN_ON_CONFIRM = '1'
    CALLBACK_TURN_OFF_CONFIRM = '2'
    CALLBACK_TURN_ON_ONCE_CONFIRM = '3'
    CALLBACK_CONFIG_CANCEL = '4'
    CALLBACK_CONFIG_CONFIRM = '5'

    USE_MARKDOWN = True
    USE_EMOJI = True
    

    def __init__(self, bot_cfg):
        self._heating = heating.Heating.instance()

        # Telegram API configuration
        self._api_token = bot_cfg['telegram']['api_token']
        self._poll_interval = bot_cfg['telegram']['poll_interval']
        self._timeout = bot_cfg['telegram']['timeout']
        self._bootstrap_retries = bot_cfg['telegram']['bootstrap_retries']

        # Who is allowed to text me?
        self._authorized_ids = bot_cfg['telegram']['authorized_ids']

        # Who will be notified of broadcast messages?
        self._broadcast_ids = bot_cfg['telegram']['broadcast_ids']

        # Sanity check
        if any([not cid in self._authorized_ids for cid in self._broadcast_ids]):
            raise ValueError("[HelheimrBot] Error: Not all broadcast IDs are authorized. Double-check telegram's configuration file.")

        logging.getLogger().info('HelheimrBot is initializing.\nAccept connections from chat IDs: {}\nBroadcast messages to: {}'.format(
            ','.join(map(str, self._authorized_ids)), 
            ','.join(map(str, self._broadcast_ids))))


        self._is_modifying_heating = False # Indicate that one user currently wants to change something
        self._shutdown_message_sent = False # Indicate whether we already sent the good bye message (in case shutdown() is called multiple times)

        self._updater = Updater(token=self._api_token, use_context=True)
        self._dispatcher = self._updater.dispatcher

        # Test telegram token/connection
        self._bot = self._updater.bot
        try:
            logging.getLogger().info('[HelheimrBot] querying myself: {}'.format(self._bot.get_me()))
        except:
            err_msg = traceback.format_exc()
            logging.getLogger().error('[HelheimrBot] Error while querying myself:\n' + err_msg)

        # Parameters to store configuration while waiting for user callback:
        self._config_at_time = None
        self._config_temperature = None
        self._config_hysteresis = None
        self._config_duration = None

        
        #######################################################################
        # Register command handlers
        self._user_filter = Filters.user(user_id=self._authorized_ids)

        start_handler = CommandHandler('start', self.__cmd_start, self._user_filter)
        self._dispatcher.add_handler(start_handler)

        help_handler = CommandHandler('help', self.__cmd_help, self._user_filter)
        self._dispatcher.add_handler(help_handler)

        status_handler = CommandHandler('status', self.__cmd_status, self._user_filter)
        self._dispatcher.add_handler(status_handler)

        detail_handler = CommandHandler('details', self.__cmd_details, self._user_filter)
        self._dispatcher.add_handler(detail_handler)

        on_handler = CommandHandler('on', self.__cmd_on, self._user_filter)
        self._dispatcher.add_handler(on_handler)

        off_handler = CommandHandler('off', self.__cmd_off, self._user_filter)
        self._dispatcher.add_handler(off_handler)

        shutdown_handler = CommandHandler('shutdown', self.__cmd_shutdown, self._user_filter)
        self._dispatcher.add_handler(shutdown_handler)

        cfg_handler = CommandHandler('config', self.__cmd_configure, self._user_filter)
        self._dispatcher.add_handler(cfg_handler)

        forecast_handler = CommandHandler('weather', self.__cmd_weather, self._user_filter)
        self._dispatcher.add_handler(forecast_handler)

        heat_once_handler = CommandHandler('once', self.__cmd_once, self._user_filter)
        self._dispatcher.add_handler(heat_once_handler)

        # Callback handler to provide inline keyboard (user must confirm/cancel on/off/etc. commands)
        self._dispatcher.add_handler(CallbackQueryHandler(self.__callback_handler))

        # Filter unknown commands and text!
        unknown_handler = MessageHandler(Filters.command, self.__cmd_unknown, self._user_filter)
        self._dispatcher.add_handler(unknown_handler)
        unknown_handler = MessageHandler(Filters.text, self.__cmd_unknown, self._user_filter)
        self._dispatcher.add_handler(unknown_handler)


    def __safe_send(self, chat_id, text, parse_mode=telegram.ParseMode.MARKDOWN):
        """Exception-safe message sending.
        Especially needed for callback queries - we got a lot of exceptions whenever users edited a previously sent command/message."""
        try:
            self._bot.send_message(chat_id=chat_id, text=common.emo(text), parse_mode=parse_mode)
            return True
        except:
            err_msg = traceback.format_exc()
            logging.getLogger().error('[HelheimrBot] Error while sending message to chat ID {}:\n'.format(chat_id) + err_msg + '\n\nMessage text was:\n' + text)
            self._is_modifying_heating = False # Reset this flag upon error (or we won't be able to change anything)
        return False


    def __safe_message_reply(self, update, text, reply_markup, parse_mode=telegram.ParseMode.MARKDOWN):
        """Exception-safe editing of messages."""
        try:
            update.message.reply_text(common.emo(text), reply_markup=reply_markup, parse_mode=parse_mode)
            return True
        except:
            err_msg = traceback.format_exc()
            logging.getLogger().error('[HelheimrBot] Error while sending reply message:\n' +\
                err_msg + '\n\nMessage text was:\n' + text)
            self._is_modifying_heating = False # Reset this flag upon error (or we won't be able to change anything)
        return False


    def __safe_edit_callback_query(self, query, text, parse_mode=telegram.ParseMode.MARKDOWN):
        try:
            query.edit_message_text(text=common.emo(text), parse_mode=parse_mode)
            return True
        except:
            err_msg = traceback.format_exc()
            logging.getLogger().error('[HelheimrBot] Error while editing callback query text:\n' +\
                err_msg + '\n\nMessage text was:\n' + text)
            self._is_modifying_heating = False # Reset this flag 
        return False


    def __safe_chat_action(self, chat_id, action=telegram.ChatAction.TYPING):
        try:
            self._bot.send_chat_action(chat_id=chat_id, action=action)
            return True
        except:
            err_msg = traceback.format_exc()
            logging.getLogger().error('[HelheimrBot] Error while sending chat action to chat ID {}\n'.format(chat_id) + err_msg)
        return False


    def __cmd_help(self, update, context):
        txt = """*Liste verfügbarer Befehle:*
/status - Statusabfrage.

/on - :thermometer: Heizung einschalten.
  nur Temperatur: /on `21.7c`
  Hysterese: /on `21c` `1c`
  nur Heizdauer: /on `1.5h`
  Temperatur und Dauer: /on `23c` `2h`
  Alles: /on `22c` `0.5c` `1.5h`

/once - :thermometer: Einmalig aufheizen.

/off - :snowflake: Heizung ausschalten.
/weather - :partly_sunny: Wetterbericht.
/details - Detaillierte Systeminformation.

/config - Heizungsprogramm einstellen.
  Uhrzeit + Dauer: /config 6:00 2h
  Zusätzlich Temperatur: /config 6:00 23c 2h
  Zusätzlich Hysterese: /config 6:00 20c 0.5c 3h

/shutdown - System herunterfahren.
/help - Diese Hilfemeldung."""
        self.__safe_send(update.message.chat_id, common.emo(txt))

    
    def __cmd_start(self, update, context):
        self.__safe_send(update.message.chat_id, 
            common.emo("Hallo! {:s}\n\n/help zeigt dir eine Liste verfügbarer Befehle an.".format(_rand_flower())))


    def __query_status(self, chat_id, detailed_report=True):
        # Query heating status
        is_heating, plug_states = self._heating.query_heating_state()
        txt = _format_msg_heating(is_heating, plug_states, 
            use_markdown=type(self).USE_MARKDOWN, 
            use_emoji=type(self).USE_EMOJI,
            include_state_details=detailed_report)

        # Query temperatures
        sensors = self._heating.query_temperature()
        txt += '\n\n' + _format_msg_temperature(sensors,
            use_markdown=type(self).USE_MARKDOWN, 
            use_emoji=type(self).USE_EMOJI,
            include_state_details=detailed_report)

        if chat_id is None:
            return txt
        else:
            self.__safe_send(chat_id, common.emo(txt))


    def __cmd_status(self, update, context):
        self.__query_status(update.message.chat_id)


    def __cmd_details(self, update, context):
        self.__safe_chat_action(update.message.chat_id, action=telegram.ChatAction.TYPING)
        msg = list()
        msg.append(self.__query_status(None, detailed_report=True))
        
        msg.append('')
        msg.append(network_utils.ConnectionTester.instance().list_known_connection_states(use_markdown=True))

        msg.append('')
        msg.append(scheduling.HelheimrScheduler.instance().list_jobs(use_markdown=True))
        txt = '\n'.join(msg)
        
        self.__safe_send(update.message.chat_id, common.emo(txt))



    def __cmd_on(self, update, context):
        # Check if another user is currently sending an on/off command:
        if self._is_modifying_heating:
            self.__safe_send(update.message.chat_id, 
                'Heizungsstatus wird gerade von einem anderen Chat geändert.\n\nBitte versuche es in ein paar Sekunden nochmal.')
            return
        self._is_modifying_heating = True # Set flag to prevent other users from concurrently modifying heating

        # Parse optional parameters
        temperature = None
        hysteresis = 0.5
        duration = None
        try:
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
        except:
            self._is_modifying_heating = False
            self.__safe_send(update.message.chat_id, 'Fehler beim Auslesen der Parameter!', parse_mode=telegram.ParseMode.MARKDOWN)
            return

        # Sanity check of configured parameter:
        is_sane, err = heating.Heating.sanity_check(heating.HeatingRequest.MANUAL, temperature, hysteresis, duration)
        if not is_sane:
            self._is_modifying_heating = False
            self.__safe_send(update.message.chat_id, 'Falsche Parameter: {}'.format(err), parse_mode=telegram.ParseMode.MARKDOWN)
            return
    
        self._config_duration = duration
        self._config_hysteresis = hysteresis
        self._config_temperature = temperature
        
        if duration is None:
            if temperature is None:
                msg = 'Heizung manuell einschalten.'
            else:
                msg = 'Auf {}\u200a\u00b1\u200a{}\u200a° heizen.'.format(
                    common.format_num('.1f', temperature, True),
                    common.format_num('.1f', hysteresis, True),
                )
        else:
            msg = time_utils.format_timedelta(duration)
            if temperature is None:
                msg += ' lang heizen.'
            else:
                msg += ' lang auf {}\u200a\u00b1\u200a{}\u200a° heizen.'.format(
                    common.format_num('.1f', temperature, True),
                    common.format_num('.1f', hysteresis, True),
                )
        msg += ' Bist du dir sicher?'

        keyboard = [[telegram.InlineKeyboardButton("Ja, sicher!", callback_data=type(self).CALLBACK_TURN_ON_CONFIRM),
                 telegram.InlineKeyboardButton("Nein", callback_data=type(self).CALLBACK_TURN_ON_OFF_CANCEL)]]

        reply_markup = telegram.InlineKeyboardMarkup(keyboard)
        self._is_modifying_heating = self.__safe_message_reply(update, 
            msg, reply_markup=reply_markup)


    def __cmd_once(self, update, context):
        # Check if another user is currently sending an on/off command:
        if self._is_modifying_heating:
            self.__safe_send(update.message.chat_id, 
                'Heizungsstatus wird gerade von einem anderen Chat geändert.\nBitte versuche es in ein paar Sekunden nochmal.')
            return
        self._is_modifying_heating = True


        temp_buttons = [telegram.InlineKeyboardButton('{:d}'.format(t), 
            callback_data=type(self).CALLBACK_TURN_ON_ONCE_CONFIRM + ':{:d}'.format(t)) for t in [19, 21, 23, 25]]
        keyboard = [temp_buttons, # First row
            [telegram.InlineKeyboardButton("Abbrechen", callback_data=type(self).CALLBACK_TURN_ON_OFF_CANCEL)]]

        reply_markup = telegram.InlineKeyboardMarkup(keyboard)
        self._is_modifying_heating = self.__safe_message_reply(update, 
            "Bitte Temperatur auswählen:", reply_markup=reply_markup)


    def __cmd_off(self, update, context):
        # Check if another user is currently sending an on/off command:
        if self._is_modifying_heating:
            self.__safe_send(update.message.chat_id, 
                'Heizungsstatus wird gerade von einem anderen Chat geändert.\nBitte versuche es in ein paar Sekunden nochmal.')
            return
        self._is_modifying_heating = True

        # Check if already off
        is_heating, plug_states = self._heating.query_heating_state()
        if not is_heating:
            self._is_modifying_heating = False
            self.__safe_send(update.message.chat_id, 
                common.emo('Heizung ist schon *aus* :snowman:\n' + _format_details_plug_states(plug_states, use_markdown=True, detailed_information=False)))
        else:
            keyboard = [[telegram.InlineKeyboardButton("Ja, sicher!", callback_data=type(self).CALLBACK_TURN_OFF_CONFIRM + ':' + ':'.join(context.args)),
                 telegram.InlineKeyboardButton("Nein", callback_data=type(self).CALLBACK_TURN_ON_OFF_CANCEL)]]

            reply_markup = telegram.InlineKeyboardMarkup(keyboard)
            # Set flag to prevent other users from concurrently modifying 
            # heating system via telegram (only if sending text succeeded)
            self._is_modifying_heating = self.__safe_message_reply(update, 
                'Heizung wirklich ausschalten?', reply_markup)

    

    def __callback_handler(self, update, context):
        if not self._is_modifying_heating:
            logging.getLogger().error('[HelheimrBot] __calback_handler called with _is_modifying_heating = False!')
            self.__safe_send(update.query.chat_id, common.emo(':bangbang: Fehler: _is_modifying_heating wurde in der Zwischenzeit zurückgesetzt!'))
        query = update.callback_query
        tokens = query.data.split(':')
        response = tokens[0]
        
        if response == type(self).CALLBACK_TURN_ON_OFF_CANCEL:
            self.__safe_edit_callback_query(query, 'Ok, dann ein andermal.')
            self._is_modifying_heating = False

        elif response == type(self).CALLBACK_TURN_ON_CONFIRM:
            success, txt = self._heating.start_heating(
                heating.HeatingRequest.MANUAL,
                query.from_user.first_name,
                target_temperature = self._config_temperature,
                temperature_hysteresis = self._config_hysteresis,
                duration = self._config_duration)

            if not success:
                self.__safe_edit_callback_query(query, common.emo(':bangbang: Fehler: ' + txt))
            else:
                # Show user we do something
                self.__safe_edit_callback_query(query, 'Wird erledigt...')
          
                self.__safe_chat_action(query.from_user.id, action=telegram.ChatAction.TYPING)
                time.sleep(type(self).WAIT_TIME_HEATING_TOGGLE)

                # Query heating after this short break
                status_txt = self.__query_status(None)
                self.__safe_edit_callback_query(query, common.emo(status_txt))
            self._is_modifying_heating = False

        elif response == type(self).CALLBACK_TURN_OFF_CONFIRM:
            self._heating.stop_heating(query.from_user.first_name)
            # Show user we do something
            self.__safe_edit_callback_query(query, 'Wird erledigt...')
            self.__safe_chat_action(query.from_user.id, action=telegram.ChatAction.TYPING)
            time.sleep(type(self).WAIT_TIME_HEATING_TOGGLE)

            # Query heating after this short break
            status_txt = self.__query_status(None)
            self.__safe_edit_callback_query(query, common.emo(status_txt))
            self._is_modifying_heating = False

        elif response == type(self).CALLBACK_TURN_ON_ONCE_CONFIRM:
            temperature = float(tokens[1])
            success, txt = self._heating.start_heating(
                heating.HeatingRequest.MANUAL,
                query.from_user.first_name,
                target_temperature = temperature,
                temperature_hysteresis = 0.2,
                duration = None,
                reach_temperature_only_once = True)

            if not success:
                self.__safe_edit_callback_query(query, common.emo(':bangbang: Fehler: ' + txt))
            else:
                # Show user we do something
                self.__safe_edit_callback_query(query, 'Wird erledigt...')
          
                self.__safe_chat_action(query.from_user.id, action=telegram.ChatAction.TYPING)
                time.sleep(type(self).WAIT_TIME_HEATING_TOGGLE)

                # Query heating after this short break
                status_txt = self.__query_status(None)
                self.__safe_edit_callback_query(query, common.emo(status_txt))
            self._is_modifying_heating = False

        elif response == type(self).CALLBACK_CONFIG_CANCEL:
            self.__safe_edit_callback_query(query, 'Ok, dann ein andermal.')
            self._is_modifying_heating = False

            self._config_at_time = None
            self._config_temperature = None
            self._config_hysteresis = None
            self._config_duration = None

        elif response == type(self).CALLBACK_CONFIG_CONFIRM:
            tokens = self._config_at_time.split(':')
            at_hour = int(tokens[0])
            at_minute, at_second = 0, 0
            if len(tokens) > 1:
                at_minute = int(tokens[1])
                if len(tokens) > 2:
                    at_second = int(tokens[2])
            
            res, msg = scheduling.HelheimrScheduler.instance().schedule_heating_job(
                query.from_user.first_name, 
                target_temperature=self._config_temperature, 
                temperature_hysteresis=self._config_hysteresis, 
                heating_duration=self._config_duration,
                day_interval=1, 
                at_hour=at_hour, at_minute=at_minute, at_second=at_second)
            if res:
                self.__safe_edit_callback_query(query, 'Neues Heizungsprogramm ist gespeichert.')
            else:
                self.__safe_edit_callback_query(query, 'Fehler! ' + msg)

            self._is_modifying_heating = False
            self._config_at_time = None
            self._config_temperature = None
            self._config_hysteresis = None
            self._config_duration = None


    def __cmd_configure(self, update, context):
        if self._is_modifying_heating:
            self.__safe_send(update.message.chat_id, 
                'Heizungsstatus wird gerade von einem anderen Chat geändert.\nBitte versuche es in ein paar Sekunden nochmal.')
            return

        at_time = None
        temperature = None
        hysteresis = 0.5
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


        if at_time is None or duration is None:
            self.__safe_send(update.message.chat_id, 
                'Fehler: du musst sowohl die Startzeit (z.B. 06:00) als auch eine Dauer (z.B. 2.5h) angeben!')
            return

        self._config_at_time = at_time
        self._config_temperature = temperature
        self._config_hysteresis = hysteresis
        self._config_duration = duration

        msg = 'Neues Programm: täglich um {:s}, {:s} für {:s}\nBist du dir sicher?'.format(
                at_time,
                'Heizung an' if temperature is None else ' heize auf {}\u200a\u00b1\u200a{}\u200a°'.format(
                    common.format_num('.1f', temperature), common.format_num('.1f', hysteresis)),
                time_utils.format_timedelta(duration))

        keyboard = [[telegram.InlineKeyboardButton("Ja, sicher!", callback_data=type(self).CALLBACK_CONFIG_CONFIRM),
                telegram.InlineKeyboardButton("Nein", callback_data=type(self).CALLBACK_CONFIG_CANCEL)]]

        self._is_modifying_heating = self.__safe_message_reply(update, msg, telegram.InlineKeyboardMarkup(keyboard))


    def __cmd_weather(self, update, context):
        self.__safe_chat_action(update.message.chat_id, action=telegram.ChatAction.TYPING)
        try:
            report = weather.WeatherForecastOwm.instance().query()
            forecast = weather.WeatherForecastOwm.instance().forecast()
            if report is None or forecast is None:
                self.__safe_send(update.message.chat_id, ':bangbang: *Fehler* beim Einholen des Wetterberichts. Bitte Log überprüfen.')
            else:
                msg = list()
                if report is not None:
                    msg.append(report.format_message(use_markdown = type(self).USE_MARKDOWN, use_emoji = type(self).USE_EMOJI))
                if forecast is not None:
                    msg.append('')
                    msg.append(forecast.format_message(use_markdown = type(self).USE_MARKDOWN, use_emoji = type(self).USE_EMOJI))
                txt = '\n'.join(msg)
                self.__safe_send(update.message.chat_id, txt)
        except:
            # This will be a formating error (maybe some fields were not set, etc.)
            # I keep this exception handling as long as I don't know what pyowm returns exactly for every weather condition
            err_msg = traceback.format_exc()
            logging.getLogger().error('[HelheimrBot] Error while querying weather report/forecast:\n' + err_msg)
            self.__safe_send(update.message.chat_id, 'Fehler während der Wetterabfrage:\n\n' + err_msg)

        # try:
        #     forecast = self.controller.query_weather_forecast()
        #     if forecast is None:
        #         context.bot.send_message(chat_id=update.message.chat_id, text=common.emo(
        #             ':bangbang: *Fehler* beim Abfragen des Wetterberichts. Log überprüfen!'
        #             ),parse_mode=telegram.ParseMode.MARKDOWN)
        #     else:
        #         context.bot.send_message(chat_id=update.message.chat_id, text=common.emo(
        #             forecast.format_message(use_markdown=True, use_emoji=True)),
        #             parse_mode=telegram.ParseMode.MARKDOWN)
        # except:
        



    def __cmd_unknown(self, update, context):
        if update.message.chat_id in self._authorized_ids:
            self.__safe_send(update.message.chat_id, common.emo("Das habe ich nicht verstanden. :thinking_face:"))
        else:
            logging.getLogger().warn('[HelheimrBot] Unauthorized access: by {} {} (user {}, id {})'.format(update.message.chat.first_name, update.message.chat.last_name, update.message.chat.username, update.message.chat_id))
            self.__safe_send(update.message.chat_id, common.emo("Hallo {} ({}), du bist (noch) nicht autorisiert. :flushed_face:").format(update.message.chat.first_name, update.message.chat_id))

    
    def __cmd_shutdown(self, update, context):
        threading.Thread(target=self.shutdown, daemon=True).start()


    def start(self):
        # Start polling messages from telegram servers
        self._updater.start_polling(poll_interval=self._poll_interval,
            timeout=self._timeout, bootstrap_retries=self._bootstrap_retries)
        # Send startup message to all authorized users
        status_txt = self.__query_status(None)
        self.broadcast_message("Hallo, ich bin online. {:s}\n\n{:s}".format(
                    _rand_flower(), status_txt))


    def broadcast_message(self, txt):
        """Send given message to all authorized chat IDs."""
        for chat_id in self._broadcast_ids:
            self.__safe_send(chat_id, common.emo(txt))


    def __shutdown_helper(self):
        # Should be run from a different thread (https://github.com/python-telegram-bot/python-telegram-bot/issues/801)
        logging.getLogger().info("[HelheimrBot] Stopping telegram updater...")
        self._updater.stop()
        self._updater.is_idle = False
        logging.getLogger().info("[HelheimrBot] Telegram bot has been shut down.")
        self._heating.shutdown()


    def shutdown(self):
        if not self._updater.running:
            return

        if not self._shutdown_message_sent:
            self._shutdown_message_sent = True
            # Send shutdown message
            status_txt = self.__query_status(None)
            
            self.broadcast_message("System wird heruntergefahren, bis bald.\n\n{:s}".format(
                        status_txt))
            
            self.__shutdown_helper()
            #threading.Thread(target=self._shutdown_helper).start()


    def __idle(self):
        """Blocking call to run the updater's event loop."""
        self._updater.idle()
        logging.getLogger().info("[HelheimrBot] Telegram updater's idle() terminated")


