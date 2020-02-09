#!/usr/bin/python
# coding=utf-8
"""
Telegram bot helheimr - controlling and querying our heating system.

Commands (formating for @botfather):

aus - :snowflake: Heizung ausschalten
config - :clock8: Heizungsprogramm einrichten
details - Detaillierte Systeminformation
ein - :high_brightness: Heizung einschalten
einmal - :high_brightness: Einmalig aufheizen
fernwaerme - Fernwärmestatus
h - :high_brightness: Heizung umschalten
heizen - :high_brightness: Heizung einschalten
help - Liste verfügbarer Befehle
log - :wrench: Servicelog anzeigen
on - :high_brightness: Heizung einschalten
off - :snowflake: Heizung ausschalten
pause - Heizungsprogramme pausieren
progs - :wrench: Programme/Aufgaben auflisten
reboot - :wrench: PC neustarten
restart - :wrench: Service neustarten
rm - Heizungsprogramm löschen
shutdown - :wrench: PC herunterfahren
status - Statusabfrage
stop - :wrench: Heizungsservice beenden
temp - Aktueller Temperaturverlauf
update - :wrench: Repository aktualisieren
vorlauf - :high_brightness: Fernwärmevorlauf einschalten
wetter - :partly_sunny: Wetterbericht


Naming/language conventions:
Frequently used commands are in German (turning stuff on/off,
querying data, ...). System commands (shutting off, configuring
or deleting programs) are English.
"""

import datetime
import logging
import random
import traceback
import threading
import time

import telegram
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackQueryHandler

from . import common
from . import district_heating
from . import drawing
from . import heating
from . import network_utils
from . import scheduling
from . import temperature_log
from . import time_utils
from . import weather

#TODOs:
# * reminder alle config minuten, falls heizung laeuft (zB 12h)
# * The python bot api wrapper supports pattern matching, so
#   we might want to clean up the callback handler a bit:
#   https://stackoverflow.com/questions/51125356/proper-way-to-build-menus-with-python-telegram-bot

# List of telegram emojis:
# https://github.com/carpedm20/emoji/blob/master/emoji/unicode_codes.py
# https://k3a.me/telegram-emoji-list-codes-descriptions/

# Unicodes:
# black circle, medium black circle, bullet: \u23fa \u25cf \u2022
# small space \u200a


def _rand_flower():
    """Return a random flower emoji."""
    return random.choice([':sunflower:', ':hibiscus:', ':tulip:', ':rose:', ':cherry_blossom:'])


def format_details_plug_states(plug_states, use_markdown=True, detailed_information=True):
    # # (deprecated) raspbee.PlugState:
    # return '\n\u2022 ' + '\n\u2022 '.join([plug.format_message(use_markdown=use_markdown, detailed_information=detailed_information) for plug in plug_states])
    # # (replaced by) lpd433.DeviceState:
    return '\n\u2022 ' + '\n\u2022 '.join([plug.to_status_line() for plug in plug_states])


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
            ('.' if not include_state_details else ':') if not use_emoji else (' :thermometer:' if is_heating else ' :snowman:')
        )
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
            '\n\u2022 '.join(
                [st.format_message(
                    use_markdown=use_markdown, detailed_information=include_state_details)
                    for st in sensor_states]))


def get_bot_url(cfg):
    return 'https://t.me/' + cfg['telegram']['bot_name']


#######################################################################
# Main bot workflow


class HelheimrBot:
    # Identifiers used in message callbacks
    # Do not use colons here, as we use this to distinguish callback
    # types (the following) and callback parameters!
    CALLBACK_TURN_ON_OFF_CANCEL = '0'
    CALLBACK_TURN_ON_CONFIRM = '1'
    CALLBACK_TURN_OFF_CONFIRM = '2'
    CALLBACK_TURN_ON_ONCE_CONFIRM = '3'
    CALLBACK_CONFIG_CANCEL = '4'
    CALLBACK_CONFIG_CONFIRM = '5'
    CALLBACK_CONFIG_REMOVE_TYPE_SELECT = '6'
    CALLBACK_CONFIG_REMOVE_JOB_SELECT = '7'
    CALLBACK_PAUSE_CONFIRM_TOGGLE = '8'
    CALLBACK_PAUSE_CANCEL = '9'
    CALLBACK_DISTRICTHEATING_TURN_ON_CANCEL = 'dh0'
    CALLBACK_DISTRICTHEATING_TURN_ON_CONFIRM = 'dh1'
    CALLBACK_SYSTEM_CANCEL = 'sys0'
    CALLBACK_SYSTEM_POWEROFF = 'sys1'
    CALLBACK_SYSTEM_REBOOT = 'sys2'
    CALLBACK_SERVICE_CANCEL = 'svc0'
    CALLBACK_SERVICE_RESTART = 'svc1'

    # Markdown: uses bold, italics and monospace (to prevent interpreting numbers as phone numbers...)
    USE_MARKDOWN = True

    # Self-explanatory?
    USE_EMOJI = True

    # Prevent errors when sending large temperature logs
    MESSAGE_MAX_LENGTH = 4096

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
        if any([cid not in self._authorized_ids for cid in self._broadcast_ids]):
            raise ValueError("[HelheimrBot] Error: Not all broadcast IDs are authorized. Double-check telegram's configuration file.")

        logging.getLogger().info(
            '[HelheimrBot] Will accept connections from chat IDs: [{}]. Broadcast messages to: [{}]'.format(
                ','.join(map(str, self._authorized_ids)),
                ','.join(map(str, self._broadcast_ids))))

        self._is_modifying_heating = False   # Indicate that one user currently wants to change something
        self._shutdown_message_sent = False  # Indicate whether we already sent the good bye message (in case shutdown() is called multiple times)
        self._is_restarting = False          # Indicate whether the user triggered a service restart (no goodbye status message should be sent)

        self._updater = Updater(token=self._api_token, use_context=True)
        self._dispatcher = self._updater.dispatcher

        # Test telegram token/connection
        self._bot = self._updater.bot
        try:
            me = self._bot.get_me()
            logging.getLogger().info(
                '[HelheimrBot] Successfully contacted Telegram API, I am @{} (Name: {}, ID: {}).'.format(
                    me['username'], me['first_name'], me['id']))
        except:
            err_msg = traceback.format_exc(limit=3)
            logging.getLogger().error(
                '[HelheimrBot] Error while querying myself:\n' +
                err_msg)

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
        # For convenience, both German and English
        help_handler = CommandHandler('hilfe', self.__cmd_help, self._user_filter)
        self._dispatcher.add_handler(help_handler)

        status_handler = CommandHandler('status', self.__cmd_status, self._user_filter)
        self._dispatcher.add_handler(status_handler)

        detail_handler = CommandHandler('details', self.__cmd_details, self._user_filter)
        self._dispatcher.add_handler(detail_handler)
        # For convenience, add abbreviation
        detail_handler = CommandHandler('d', self.__cmd_details, self._user_filter)
        self._dispatcher.add_handler(detail_handler)

        on_handler = CommandHandler('on', self.__cmd_on, self._user_filter)
        self._dispatcher.add_handler(on_handler)
        # For convenience, both German and English
        on_handler = CommandHandler('ein', self.__cmd_on, self._user_filter)
        self._dispatcher.add_handler(on_handler)
        # and with an additional name...
        on_handler = CommandHandler('heizen', self.__cmd_on, self._user_filter)
        self._dispatcher.add_handler(on_handler)

        off_handler = CommandHandler('off', self.__cmd_off, self._user_filter)
        self._dispatcher.add_handler(off_handler)
        # For convenience, both German and English
        off_handler = CommandHandler('aus', self.__cmd_off, self._user_filter)
        self._dispatcher.add_handler(off_handler)

        toggle_handler = CommandHandler('h', self.__cmd_toggle_heating, self._user_filter)
        self._dispatcher.add_handler(toggle_handler)

        stop_handler = CommandHandler('stop', self.__cmd_stop, self._user_filter)
        self._dispatcher.add_handler(stop_handler)

        cfg_handler = CommandHandler('config', self.__cmd_configure, self._user_filter)
        self._dispatcher.add_handler(cfg_handler)

        forecast_handler = CommandHandler('wetter', self.__cmd_weather, self._user_filter)
        self._dispatcher.add_handler(forecast_handler)

        heat_once_handler = CommandHandler('einmal', self.__cmd_once, self._user_filter)
        self._dispatcher.add_handler(heat_once_handler)
        # For convenience, both German and English
        heat_once_handler = CommandHandler('once', self.__cmd_once, self._user_filter)
        self._dispatcher.add_handler(heat_once_handler)

        pause_handler = CommandHandler('pause', self.__cmd_pause, self._user_filter)
        self._dispatcher.add_handler(pause_handler)

        rm_task_handler = CommandHandler('rm', self.__cmd_rm, self._user_filter)
        self._dispatcher.add_handler(rm_task_handler)

        temp_task_handler = CommandHandler('temp', self.__cmd_temp, self._user_filter)
        self._dispatcher.add_handler(temp_task_handler)
        # For convenience, add abbreviation
        temp_task_handler = CommandHandler('t', self.__cmd_temp, self._user_filter)
        self._dispatcher.add_handler(temp_task_handler)

        job_list_handler = CommandHandler('progs', self.__cmd_list_jobs, self._user_filter)
        self._dispatcher.add_handler(job_list_handler)

        log_handler = CommandHandler('log', self.__cmd_service_log, self._user_filter)
        self._dispatcher.add_handler(log_handler)

        dh_start_handler = CommandHandler('vorlauf', self.__cmd_start_district_heating, self._user_filter)
        self._dispatcher.add_handler(dh_start_handler)

        dh_query_handler = CommandHandler('fernwaerme', self.__cmd_query_district_heating, self._user_filter)
        self._dispatcher.add_handler(dh_query_handler)

        # TODO remove this handler once we're done testing ;-)
        debug_handler = CommandHandler('debug', self.__cmd_debug, self._user_filter)
        self._dispatcher.add_handler(debug_handler)

        update_handler = CommandHandler('update', self.__cmd_update, self._user_filter)
        self._dispatcher.add_handler(update_handler)

        reboot_handler = CommandHandler('reboot', self.__cmd_reboot, self._user_filter)
        self._dispatcher.add_handler(reboot_handler)

        poweroff_handler = CommandHandler('shutdown', self.__cmd_poweroff, self._user_filter)
        self._dispatcher.add_handler(poweroff_handler)

        restart_handler = CommandHandler('restart', self.__cmd_restart, self._user_filter)
        self._dispatcher.add_handler(restart_handler)

        # Callback handler to provide inline keyboard (user must confirm/cancel on/off/etc. commands)
        self._dispatcher.add_handler(CallbackQueryHandler(self.__callback_handler))

        # Filter unknown commands and text!
        unknown_handler = MessageHandler(Filters.command, self.__cmd_unknown, self._user_filter)
        self._dispatcher.add_handler(unknown_handler)
        unknown_handler = MessageHandler(Filters.text, self.__cmd_unknown, self._user_filter)
        self._dispatcher.add_handler(unknown_handler)

    def __safe_send(self, chat_id, text, parse_mode=telegram.ParseMode.MARKDOWN):
        """
        Exception-safe message sending.
        Especially needed for callback queries - we got a lot of exceptions
        whenever users edited a previously sent command/message.
        """
        try:
            if len(text) > type(self).MESSAGE_MAX_LENGTH:
                text = text[:type(self).MESSAGE_MAX_LENGTH]
            self._bot.send_message(chat_id=chat_id, text=common.emo(text), parse_mode=parse_mode)
            return True
        except:
            err_msg = traceback.format_exc(limit=3)
            logging.getLogger().error(
                '[HelheimrBot] Error while sending message to chat ID {}.\n'.format(chat_id) +
                err_msg + '\n\nMessage text was:\n' + text)
            self._is_modifying_heating = False  # Reset flag to allow editing again
        return False

    def __safe_photo_send(self, chat_id, image_buffer, **kwargs):
        try:
            self._bot.send_photo(chat_id, photo=image_buffer, **kwargs)
            return True
        except:
            err_msg = traceback.format_exc(limit=3)
            logging.getLogger().error(
                '[HelheimrBot] Error while sending image to chat ID {}.\n'.format(chat_id) +
                err_msg)
            # self._is_modifying_heating = False # Reset flag to allow editing again
        return False

    def __safe_message_reply(self, update, text, reply_markup, parse_mode=telegram.ParseMode.MARKDOWN):
        """Exception-safe editing of messages."""
        try:
            update.message.reply_text(common.emo(text), reply_markup=reply_markup, parse_mode=parse_mode)
            return True
        except:
            err_msg = traceback.format_exc(limit=3)
            logging.getLogger().error(
                '[HelheimrBot] Error while sending reply message:\n' +
                err_msg + '\n\nMessage text was:\n' + text)
            self._is_modifying_heating = False  # Reset flag to allow editing again
        return False

    def __safe_edit_callback_query(self, query, text, parse_mode=telegram.ParseMode.MARKDOWN):
        try:
            query.edit_message_text(text=common.emo(text), parse_mode=parse_mode)
            return True
        except:
            err_msg = traceback.format_exc(limit=3)
            logging.getLogger().error(
                '[HelheimrBot] Error while editing callback query text:\n' +
                err_msg + '\n\nMessage text was:\n' + text)
            self._is_modifying_heating = False  # Reset flag to allow editing again
        return False

    def __safe_edit_message_text(self, query, txt, reply_markup=None, parse_mode=telegram.ParseMode.MARKDOWN):
        try:
            self._bot.edit_message_text(
                chat_id=query.message.chat_id,
                message_id=query.message.message_id, text=common.emo(txt),
                reply_markup=reply_markup, parse_mode=parse_mode)
            return True
        except:
            err_msg = traceback.format_exc(limit=3)
            logging.getLogger().error(
                '[HelheimrBot] Error while editing message text:\n' +
                err_msg + '\n\nMessage text was:\n' + txt)
            self._is_modifying_heating = False  # Reset flag to allow editing again
        return False

    def __safe_chat_action(self, chat_id, action=telegram.ChatAction.TYPING):
        try:
            self._bot.send_chat_action(chat_id=chat_id, action=action)
            return True
        except:
            err_msg = traceback.format_exc()
            logging.getLogger().error(
                '[HelheimrBot] Error while sending chat action to chat ID {}\n'.format(chat_id) + err_msg)
        return False

    def __cmd_help(self, update, context):
        txt = """*Liste verfügbarer Befehle:*
/status - Statusabfrage.
/details oder /d - Detaillierte Systeminformation.
/progs - Liste aller Programme & Aufgaben.

/ein oder /heizen oder /on
    :thermometer: Heizung einschalten.
    Mit Temperatur: /on `21.7c`
    Mit Hysterese: /on `21c` `1c`
    Mit Heizdauer: /on `1.5h`
    Temperatur & Dauer: /on `23c` `2h`
    Alles: /on `22c` `0.5c` `1.5h`

/h Heizung umschalten.

/einmal oder /once - :thermometer: Einmalig
    auf bestimmte Temperatur aufheizen.

/aus oder /off - :snowflake: Heizung ausschalten.

/pause - Heizungsprogramme pausieren.

/temp oder /t - Temperaturverlauf.
    Letzter Tag: /temp
    Letzten N Messungen: /temp 15
    Alle gespeicherten: /temp -1
    Zusätzlich als Tabelle: /temp t

/wetter - :partly_sunny: Wetterbericht.

/fernwaerme - Ferwärmestatus.

/vorlauf - 1\u200ah Fernwärmevorlauf.

/config S D [T H] - Heizungsprogramm
    konfigurieren.
    Startzeit + Dauer: /config 6:00 2h
    Zusätzlich Temperatur: /config 6:00 23c 2h
    Zusätzlich Hysterese: /config 6:00 20c 0.5c 3h

/rm - Heizungsprogramm löschen.

/reboot - PC neustarten.

/shutdown - PC herunterfahren.

/log oder /log N - Log anzeigen.

/stop - Heizungsservice beenden.

/update - Repository aktualisieren
    und Service neustarten.

/restart - Heizungsservice neustarten.

/hilfe oder /help - Diese Hilfe."""
        self.__safe_send(update.message.chat_id, txt)

    def __cmd_start(self, update, context):
        self.__safe_send(
            update.message.chat_id,
            "Hallo! {:s}\n\n/help zeigt dir eine Liste verfügbarer Befehle an.".format(_rand_flower()))

    def __query_status(self, chat_id, detailed_report=True):
        # Query heating status
        is_heating, plug_states = self._heating.query_heating_state()
        txt = format_msg_heating(
            is_heating, plug_states,
            use_markdown=type(self).USE_MARKDOWN,
            use_emoji=type(self).USE_EMOJI,
            include_state_details=detailed_report)

        if is_heating:
            res = self._heating.residual_heating_time
            if res is None:
                txt += '\nDauerheizen ist eingestellt!'
            else:
                txt += '\nRestzeit: {}'.format(time_utils.format_timedelta(res, small_space=True))

        paused = self._heating.is_paused
        if paused:
            txt += '\n\nHeizungsprogramme sind aktuell pausiert!'

        # Query temperatures
        sensors = self._heating.query_temperature()
        txt += '\n\n' + format_msg_temperature(
            sensors,
            use_markdown=type(self).USE_MARKDOWN,
            use_emoji=type(self).USE_EMOJI,
            include_state_details=detailed_report)

        if chat_id is None:
            return txt
        else:
            # Give user the opportunity to easily switch on/off:
            txt += '\n\nHeizung /{:s}\u200aschalten?'.format(
                'aus' if is_heating else 'ein')
            if paused:
                txt += '\nProgramme über /pause wieder aktivieren?'
            self.__safe_send(chat_id, txt)

    def __cmd_status(self, update, context):
        self.__query_status(update.message.chat_id, detailed_report=False)

    def __cmd_details(self, update, context):
        self.__safe_chat_action(update.message.chat_id, action=telegram.ChatAction.TYPING)
        msg = list()
        msg.append(self.__query_status(None, detailed_report=True))

        msg.append('')
        _, txt = network_utils.ConnectionTester.instance().list_known_connection_states(use_markdown=True)
        msg.append(txt)

        msg.append('')
        msg.append(scheduling.HelheimrScheduler.instance().list_jobs(use_markdown=True))

        # Add general process info
        proc_info = common.proc_info()
        cpu_info = common.cpu_info()
        msg.append('')
        msg.append('*Systeminfo:*')
        msg.append('\u2022 PID: `{}`'.format(proc_info.pid))
        msg.append('\u2022 Speicherverbrauch: `{:.1f}`\u200aMB'.format(proc_info.mem_usage_mb))
        msg.append('\u2022 CPU Last (`1/5/15`): `{:d}`\u200a%, `{:d}`\u200a%, `{:d}`\u200a%'.format(
            int(cpu_info.load_avg_1), int(cpu_info.load_avg_5), int(cpu_info.load_avg_15)))
        msg.append('\u2022 CPU Taktung (c/min/max): `{:d}` (`{:d}`-`{:d}`)'.format(
            int(cpu_info.cpu_freq_current), int(cpu_info.cpu_freq_min), int(cpu_info.cpu_freq_max)))
        if cpu_info.cpu_temperature is not None:
            msg.append('\u2022 CPU Temperatur: `{:.1f}`\u200a°'.format(cpu_info.cpu_temperature))
        # Append (pretty) uptime
        s, txt = common.shell_exec_command('uptime -p')
        if s:
            msg.append('\u2022 {:s}'.format(txt.capitalize()))
        #TODO Add system info (mem/uptime/disk_usage), check:
        # https://pypi.org/project/psutil/
        # https://psutil.readthedocs.io/en/latest/#recipes/
        # https://stackoverflow.com/a/556411 os.times
        txt = '\n'.join(msg)
        self.__safe_send(update.message.chat_id, txt)

    def __cmd_toggle_heating(self, update, context):
        # Check if another user is currently sending an on/off command:
        if self._is_modifying_heating:
            self.__safe_send(
                update.message.chat_id,
                'Heizungsstatus wird gerade von einem anderen Chat geändert.\n\nBitte versuche es in ein paar Sekunden nochmal.')
            return
        # Set flag to prevent other users from concurrently modifying heating
        self._is_modifying_heating = True
        is_heating, _ = self._heating.query_heating_state()
        if is_heating:
            msg = 'Heizung ist ein, möchtest du sie ausschalten?'
            keyboard = [[
                telegram.InlineKeyboardButton("Ja", callback_data=type(self).CALLBACK_TURN_OFF_CONFIRM),
                telegram.InlineKeyboardButton("Nein", callback_data=type(self).CALLBACK_TURN_ON_OFF_CANCEL)]]
        else:
            msg = 'Heizung ist aus, möchtest du sie einschalten?'
            self._config_temperature = None
            self._config_hysteresis = None
            self._config_duration = None
            keyboard = [[
                telegram.InlineKeyboardButton("Ja", callback_data=type(self).CALLBACK_TURN_ON_CONFIRM),
                telegram.InlineKeyboardButton("Nein", callback_data=type(self).CALLBACK_TURN_ON_OFF_CANCEL)]]
        reply_markup = telegram.InlineKeyboardMarkup(keyboard)
        self._is_modifying_heating = self.__safe_message_reply(
            update, msg, reply_markup=reply_markup)

    def __cmd_on(self, update, context):
        # Check if another user is currently sending an on/off command:
        if self._is_modifying_heating:
            self.__safe_send(
                update.message.chat_id,
                'Heizungsstatus wird gerade von einem anderen Chat geändert.\n\nBitte versuche es in ein paar Sekunden nochmal.')
            return
        # Set flag to prevent other users from concurrently modifying heating
        self._is_modifying_heating = True

        # Parse optional parameters
        temperature = None
        hysteresis = 0.5
        duration = None
        try:
            for a in context.args:
                if a[-1] == 'c':
                    val = float(a[:-1].replace(',', '.'))
                    if temperature is None:
                        temperature = val
                    else:
                        hysteresis = val
                elif a[-1] == 'h':
                    h = float(a[:-1].replace(',', '.'))
                    hours = int(h)
                    minutes = int((h - hours) * 60)
                    duration = datetime.timedelta(hours=hours, minutes=minutes)
        except:
            self._is_modifying_heating = False
            self.__safe_send(
                update.message.chat_id, 'Fehler beim Auslesen der Parameter!',
                parse_mode=telegram.ParseMode.MARKDOWN)
            return

        # Sanity check of configured parameter:
        is_sane, err = heating.Heating.sanity_check(
            heating.HeatingRequest.MANUAL, temperature, hysteresis, duration)
        if not is_sane:
            self._is_modifying_heating = False
            self.__safe_send(
                update.message.chat_id,
                'Falsche Parameter: {}'.format(err), parse_mode=telegram.ParseMode.MARKDOWN)
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

        keyboard = [[
            telegram.InlineKeyboardButton("Ja, sicher!", callback_data=type(self).CALLBACK_TURN_ON_CONFIRM),
            telegram.InlineKeyboardButton("Nein", callback_data=type(self).CALLBACK_TURN_ON_OFF_CANCEL)]]

        reply_markup = telegram.InlineKeyboardMarkup(keyboard)
        self._is_modifying_heating = self.__safe_message_reply(
            update, msg, reply_markup=reply_markup)

    def __cmd_once(self, update, context):
        # Check if another user is currently sending an on/off command:
        if self._is_modifying_heating:
            self.__safe_send(
                update.message.chat_id,
                'Heizungsstatus wird gerade von einem anderen Chat geändert.\nBitte versuche es in ein paar Sekunden nochmal.')
            return
        self._is_modifying_heating = True

        temp_buttons = [telegram.InlineKeyboardButton('{:d}\u200a°'.format(t),
            callback_data=type(self).CALLBACK_TURN_ON_ONCE_CONFIRM + ':{:d}'.format(t)) for t in [19, 21, 23, 25]]
        keyboard = [temp_buttons,  # First row
            [telegram.InlineKeyboardButton("Abbrechen", callback_data=type(self).CALLBACK_TURN_ON_OFF_CANCEL)]]

        reply_markup = telegram.InlineKeyboardMarkup(keyboard)
        self._is_modifying_heating = self.__safe_message_reply(
            update, "Bitte Temperatur auswählen:", reply_markup=reply_markup)

    def __cmd_start_district_heating(self, update, context):
        # Check if another user is currently modifying something:
        if self._is_modifying_heating:
            self.__safe_send(
                update.message.chat_id,
                'Heizungsstatus wird gerade von einem anderen Chat geändert.\nBitte versuche es in ein paar Sekunden nochmal.')
            return
        self._is_modifying_heating = True

        btns = district_heating.DistrictHeating.instance().get_buttons(as_int=True)
        temp_buttons = [telegram.InlineKeyboardButton(b[0],
            callback_data=type(self).CALLBACK_DISTRICTHEATING_TURN_ON_CONFIRM + ':{:d}'.format(b[1]))
            for b in btns]
        keyboard = [
            temp_buttons,  # First row
            [telegram.InlineKeyboardButton(
                "Abbrechen", callback_data=type(self).CALLBACK_DISTRICTHEATING_TURN_ON_CANCEL)]]

        reply_markup = telegram.InlineKeyboardMarkup(keyboard)
        self._is_modifying_heating = self.__safe_message_reply(
            update, "Vorlauftemperatur auswählen:", reply_markup=reply_markup)

    def __cmd_query_district_heating(self, update, context):
        self.__safe_chat_action(update.message.chat_id, action=telegram.ChatAction.TYPING)
        success, msg = district_heating.DistrictHeating.instance().query_heating(use_markdown=True)
        if not success:
            msg = ':bangbang: ' + msg
        else:
            msg += '\n\nEinstellungen sind über /vorlauf möglich.'
        self.__safe_message_reply(update, msg, reply_markup=None)

    def __cmd_off(self, update, context):
        # Check if another user is currently sending an on/off command:
        if self._is_modifying_heating:
            self.__safe_send(
                update.message.chat_id,
                'Heizungsstatus wird gerade von einem anderen Chat geändert.\nBitte versuche es in ein paar Sekunden nochmal.')
            return
        self._is_modifying_heating = True

        # Check if already off
        is_heating, plug_states = self._heating.query_heating_state()
        if not is_heating:
            self._is_modifying_heating = False
            self.__safe_send(
                update.message.chat_id,
                'Heizung ist schon *aus* :snowman:\n' + format_details_plug_states(
                    plug_states, use_markdown=True, detailed_information=False))
        else:
            keyboard = [[
                telegram.InlineKeyboardButton("Ja, sicher!", callback_data=type(self).CALLBACK_TURN_OFF_CONFIRM + ':' + ':'.join(context.args)),
                telegram.InlineKeyboardButton("Nein", callback_data=type(self).CALLBACK_TURN_ON_OFF_CANCEL)]]

            reply_markup = telegram.InlineKeyboardMarkup(keyboard)
            # Set flag to prevent other users from concurrently modifying
            # heating system via telegram (only if sending text succeeded)
            self._is_modifying_heating = self.__safe_message_reply(
                update, 'Heizung wirklich ausschalten?', reply_markup)

    def __cmd_pause(self, update, context):
        # Check if another user is currently sending an on/off command:
        if self._is_modifying_heating:
            self.__safe_send(
                update.message.chat_id,
                'Heizungsstatus wird gerade von einem anderen Chat geändert.\nBitte versuche es in ein paar Sekunden nochmal.')
            return
        self._is_modifying_heating = True

        paused = self._heating.is_paused

        msg = 'Heizungsprogramme pausieren?' if not paused else 'Heizungsprogramme aktivieren?'

        keyboard = [[
            telegram.InlineKeyboardButton("Ja", callback_data=type(self).CALLBACK_PAUSE_CONFIRM_TOGGLE),
            telegram.InlineKeyboardButton("Abbrechen", callback_data=type(self).CALLBACK_PAUSE_CANCEL)]]

        reply_markup = telegram.InlineKeyboardMarkup(keyboard)
        # Set flag to prevent other users from concurrently modifying
        # heating system via telegram (only if sending text succeeded)
        self._is_modifying_heating = self.__safe_message_reply(update, msg, reply_markup)

    def __callback_handler(self, update, context):
        if not self._is_modifying_heating:
            logging.getLogger().error(
                '[HelheimrBot] __calback_handler called with _is_modifying_heating = False!')
            self.__safe_send(
                update.query.chat_id,
                ':bangbang: Fehler: _is_modifying_heating wurde in der Zwischenzeit zurückgesetzt!')
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
                target_temperature=self._config_temperature,
                temperature_hysteresis=self._config_hysteresis,
                duration=self._config_duration)

            if not success:
                self.__safe_edit_callback_query(query, ':bangbang: Fehler: ' + txt)
            else:
                self.__safe_edit_callback_query(query, 'Heizung wurde eingeschaltet.')
            self._is_modifying_heating = False

        elif response == type(self).CALLBACK_TURN_OFF_CONFIRM:
            self._heating.stop_heating(query.from_user.first_name)
            self.__safe_edit_callback_query(query, 'Heizung wurde ausgeschaltet.')
            self._is_modifying_heating = False

        elif response == type(self).CALLBACK_TURN_ON_ONCE_CONFIRM:
            temperature = float(tokens[1])
            success, txt = self._heating.start_heating(
                heating.HeatingRequest.MANUAL,
                query.from_user.first_name,
                target_temperature=temperature,
                temperature_hysteresis=0.2,
                duration=None,
                reach_temperature_only_once=True)

            if not success:
                self.__safe_edit_callback_query(query, ':bangbang: Fehler: ' + txt)
            else:
                current_temperature = heating.Heating.instance().query_temperature_for_heating()
                if current_temperature is None:
                    txt = ':bangbang: Aktuelle Temperatur kann nicht abgefragt werden! Versuche, Heizung einzuschalten - bitte überprüfen!'
                else:
                    if current_temperature >= temperature:
                        txt = 'Es hat bereits {}\u200a°'.format(
                            common.format_num('.1f', current_temperature, use_markdown=True))
                    else:
                        txt = 'Heize einmalig auf {}\u200a°'.format(
                            common.format_num('.1f', temperature, use_markdown=True))
                        txt += ', aktuell: {}\u200a°'.format(
                            common.format_num('.1f', current_temperature, use_markdown=True))
                self.__safe_edit_callback_query(query, txt)
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

        elif response == type(self).CALLBACK_CONFIG_REMOVE_TYPE_SELECT:
            # Don't change modifying heating!
            jobs = scheduling.HelheimrScheduler.instance().get_job_teasers(use_markdown=False)
            job_type = tokens[1]
            txt, reply_markup = self.__rm_helper_keyboard_job_select(jobs, job_type)
            self._is_modifying_heating = self.__safe_edit_message_text(query, txt, reply_markup=reply_markup)

        elif response == type(self).CALLBACK_CONFIG_REMOVE_JOB_SELECT:
            uid = tokens[1]
            self._is_modifying_heating = False
            removed = scheduling.HelheimrScheduler.instance().remove_job(uid)
            if removed is None:
                self.__safe_edit_callback_query(
                    query, 'Fehler beim Entfernen, bitte Logs überprüfen.')
            else:
                self.__safe_edit_callback_query(
                    query, "Programm ({:s}) wurde entfernt.".format(removed.teaser(use_markdown=True)))

        elif response == type(self).CALLBACK_PAUSE_CONFIRM_TOGGLE:
            is_paused = self._heating.toggle_pause(query.from_user.first_name)
            msg = 'Heizungsprogramme sind pausiert.' if is_paused else 'Heizungsprogramme sind wieder aktiviert.'
            self.__safe_edit_callback_query(query, msg)
            self._is_modifying_heating = False

        elif response == type(self).CALLBACK_PAUSE_CANCEL:
            self.__safe_edit_callback_query(query, 'Ok, dann ein andermal.')
            self._is_modifying_heating = False

        elif response == type(self).CALLBACK_DISTRICTHEATING_TURN_ON_CANCEL:
            self.__safe_edit_callback_query(query, 'Ok, dann ein andermal.')
            self._is_modifying_heating = False

        elif response == type(self).CALLBACK_DISTRICTHEATING_TURN_ON_CONFIRM:
            request_type = tokens[1]
            success, txt = district_heating.DistrictHeating.instance().start_heating(request_type)
            if not success:
                self.__safe_edit_callback_query(query, ':bangbang: Fehler: ' + txt)
            else:
                self.__safe_edit_callback_query(query, 'Fernwärme wurde eingeschaltet.\n\nStatusabfrage über /fernwaerme möglich.')
            self._is_modifying_heating = False

        elif response == type(self).CALLBACK_SYSTEM_CANCEL:
            self._is_modifying_heating = False
            self.__safe_edit_callback_query(query, 'Ok, dann ein andermal.')

        elif response == type(self).CALLBACK_SYSTEM_POWEROFF:
            self._is_modifying_heating = False
            self.__poweroff_helper(query)

        elif response == type(self).CALLBACK_SYSTEM_REBOOT:
            self._is_modifying_heating = False
            self.__reboot_helper(query)

        elif response == type(self).CALLBACK_SERVICE_CANCEL:
            self._is_modifying_heating = False
            self.__safe_edit_callback_query(query, 'Ok, dann ein andermal.')

        elif response == type(self).CALLBACK_SERVICE_RESTART:
            self.__safe_message_reply(update, 'Service wird jetzt neugestartet...',
                reply_markup=None)
            # Restart after a short delay
            time.sleep(1.5)
            # Prevent sending the shutdown message
            self._is_restarting = True
            success, txt = common.shell_restart_service()
            if not success:
                logging.getLogger().error('[HelheimrBot] Could not restart service: ' + txt)
                self.__safe_message_reply(update, 'Fehler beim Service-Neustart: ' + txt, reply_markup=None)

    def __rm_helper_keyboard_type_select(self):
        keyboard = [
            [telegram.InlineKeyboardButton('Heizungsprogramme',
                callback_data=type(self).CALLBACK_CONFIG_REMOVE_TYPE_SELECT + ':' + 'heating_jobs')],
            [telegram.InlineKeyboardButton('Andere Aufgaben',
                callback_data=type(self).CALLBACK_CONFIG_REMOVE_TYPE_SELECT + ':' + 'non_heating_jobs')],
            [telegram.InlineKeyboardButton('Abbrechen', callback_data=type(self).CALLBACK_CONFIG_CANCEL)]]
        return 'Bitte Typ auswählen:', telegram.InlineKeyboardMarkup(keyboard)

    def __rm_helper_keyboard_job_select(self, jobs, job_type):
        qstr = 'Welches Programm soll gelöscht werden?' \
            if job_type == 'heating_jobs' else 'Welche Aufgabe soll gelöscht werden?'
        keyboard = list()
        for uid, teaser in jobs[job_type]:
            keyboard.append([telegram.InlineKeyboardButton('[{:d}] {:s}'.format(uid, teaser),
                callback_data=type(self).CALLBACK_CONFIG_REMOVE_JOB_SELECT + ':' + str(uid), parse_mode=telegram.ParseMode.MARKDOWN)])
        # Always include a 'cancel' option
        keyboard.append([telegram.InlineKeyboardButton(
            "Abbrechen", callback_data=type(self).CALLBACK_CONFIG_CANCEL)])
        # Send menu to user:
        return qstr, telegram.InlineKeyboardMarkup(keyboard)

    def __cmd_rm(self, update, context):
        """Removes a scheduled task."""
        if self._is_modifying_heating:
            self.__safe_send(
                update.message.chat_id,
                'Heizungsstatus wird gerade von einem anderen Chat geändert.\nBitte versuche es in ein paar Sekunden nochmal.')
            return
        # If we have both heating and non-heating jobs, present the user a
        # two-level menu (first, select the type, then the task)
        self._is_modifying_heating = True
        jobs = scheduling.HelheimrScheduler.instance().get_job_teasers(use_markdown=False)
        heating_jobs = jobs['heating_jobs']
        non_heating_jobs = jobs['non_heating_jobs']
        if len(heating_jobs) > 0 and len(non_heating_jobs) > 0:
            txt, reply_markup = self.__rm_helper_keyboard_type_select()
        else:
            selected_type = None
            if len(heating_jobs) > 0:
                selected_type = 'heating_jobs'
            elif len(non_heating_jobs) > 0:
                selected_type = 'non_heating_jobs'
            else:
                self._is_modifying_heating = False
                self.__safe_send(update.message.chat_id, 'Derzeit sind weder Programme noch Aufgaben gespeichert.')
                return
            txt, reply_markup = self.__rm_helper_keyboard_job_select(jobs, selected_type)
        self._is_modifying_heating = self.__safe_message_reply(update, txt, reply_markup)

    def __cmd_configure(self, update, context):
        """Configures a new heating program."""
        if self._is_modifying_heating:
            self.__safe_send(
                update.message.chat_id,
                'Heizungsstatus wird gerade von einem anderen Chat geändert.\nBitte versuche es in ein paar Sekunden nochmal.')
            return

        at_time = None
        temperature = None
        hysteresis = 0.5
        duration = None
        for a in context.args:
            if a[-1] == 'c':
                val = float(a[:-1].replace(',', '.'))
                if temperature is None:
                    temperature = val
                else:
                    hysteresis = val
            elif ':' in a:
                tokens = a.split(':')
                if len(tokens) != 2:
                    self.__safe_send(
                        update.message.chat_id,
                        'Fehler: Startzeit muss als HH:MM angegeben werden!')
                    return
                at_time = '{:02d}:{:02d}'.format(int(tokens[0]), int(tokens[1]))
            elif a[-1] == 'h':
                h = float(a[:-1].replace(',', '.'))
                hours = int(h)
                minutes = int((h - hours) * 60)
                duration = datetime.timedelta(hours=hours, minutes=minutes)

        if at_time is None or duration is None:
            self.__safe_send(update.message.chat_id,
                'Fehler: du musst sowohl die Startzeit (z.B. 06:00) als auch eine Dauer (z.B. 2.5h) angeben!')
            return

        is_sane, err = heating.Heating.sanity_check(heating.HeatingRequest.SCHEDULED, temperature, hysteresis, duration)
        if not is_sane:
            self._is_modifying_heating = False
            self.__safe_send(update.message.chat_id, 'Falsche Parameter: {}'.format(err), parse_mode=telegram.ParseMode.MARKDOWN)
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
        """Sends the weather report/forecast."""
        self.__safe_chat_action(update.message.chat_id, action=telegram.ChatAction.TYPING)
        try:
            report = weather.WeatherForecastOwm.instance().report()
            forecast = weather.WeatherForecastOwm.instance().forecast()
            if report is None or forecast is None:
                self.__safe_send(update.message.chat_id, ':bangbang: *Fehler* beim Einholen des Wetterberichts. Bitte Log überprüfen.')
            else:
                msg = list()
                if report is not None:
                    msg.append(report.format_message(use_markdown=type(self).USE_MARKDOWN, use_emoji=type(self).USE_EMOJI))
                if forecast is not None:
                    msg.append('')
                    msg.append(forecast.format_message(use_markdown=type(self).USE_MARKDOWN, use_emoji=type(self).USE_EMOJI))
                txt = '\n'.join(msg)
                self.__safe_send(update.message.chat_id, txt)
        except:
            # This will be a formating error (maybe some fields were not set, etc.)
            # I keep this exception handling as long as I don't know what pyowm returns exactly for every weather condition
            err_msg = traceback.format_exc()
            logging.getLogger().error('[HelheimrBot] Error while querying weather report/forecast:\n' + err_msg)
            self.__safe_send(update.message.chat_id, 'Fehler während der Wetterabfrage:\n\n' + err_msg)

    def __cmd_temp(self, update, context):
        """Renders the temperature curve."""
        num_entries = None
        render_table = False
        draw_marker = False
        for arg in context.args:
            if arg.lower() == 't' or arg.lower() == 'tab' or arg.lower() == 'table':
                render_table = True
            elif arg.lower() == 'x' or arg.lower() == 'marker':
                draw_marker = True
            else:
                if 'd' in arg or 'h' in arg or 'm' in arg:
                    num_entries = arg
                else:
                    try:
                        num_entries = int(arg)
                    except:
                        self.__safe_send(
                            update.message.chat_id,
                            ':bangbang: Parameterfehler: Anzahl der Messungen muss eine Ganzzahl sein!')
                        return
        if render_table:
            msg = temperature_log.TemperatureLog.instance().format_table(num_entries)
            max_len = type(self).MESSAGE_MAX_LENGTH - 8
            if len(msg) > max_len:
                msg = msg[:max_len]  # most recent rows are on top (!)
            self.__safe_send(update.message.chat_id, '```\n' + msg + '\n```')

        # Get temperature plot
        img_buf = drawing.plot_temperature_curves(
            1024, 768, temperature_log.TemperatureLog.instance().recent_readings(num_entries),
            return_mem=True, xkcd=True, reverse=True, draw_marker=draw_marker,
            name_mapping=temperature_log.TemperatureLog.instance().name_mapping)
        if img_buf is None:
            self.__safe_send(update.message.chat_id,
                ':bangbang: Fehler beim Erstellen der Temperaturverlaufsgrafik, bitte Log überprüfen.')
        else:
            self.__safe_photo_send(
                update.message.chat_id, img_buf,
                caption='Temperaturverlauf', disable_notification=True)

    def __cmd_list_jobs(self, update, context):
        """Lists all scheduled tasks."""
        txt = scheduling.HelheimrScheduler.instance().list_jobs(use_markdown=True)
        self.__safe_message_reply(update, txt, reply_markup=None)

    def __cmd_unknown(self, update, context):
        """Handles any unknown command or text sent by users."""
        if update.message.chat_id in self._authorized_ids:
            self.__safe_send(update.message.chat_id, "Das habe ich nicht verstanden. :thinking_face:")
        else:
            logging.getLogger().warn(
                '[HelheimrBot] Unauthorized access: by {} {} (user {}, id {})'.format(
                    update.message.chat.first_name, update.message.chat.last_name,
                    update.message.chat.username, update.message.chat_id))
            self.__safe_send(
                update.message.chat_id,
                "Hallo {} ({}), du bist (noch) nicht autorisiert. :flushed_face:".format(
                    update.message.chat.first_name, update.message.chat_id))

    def __cmd_stop(self, update, context):
        """Handles /stop, i.e. shut down the heating service."""
        if self._is_modifying_heating:
            self.__safe_send(update.message.chat_id,
                'Heizungsstatus wird gerade von einem anderen Chat geändert.\nBitte versuche es in ein paar Sekunden nochmal.')
            return
        thread = threading.Thread(target=self.shutdown)
        thread.daemon = True
        thread.start()

    def __reboot_helper(self, query):
        """Helper function to reboot the PC (and gracefully
        shut down the service from a different thread)."""
        logging.getLogger().info('[HelheimrBot] User {} requested system reboot.'.format(query.from_user.first_name))
        self.__safe_edit_callback_query(query, 'Raspberry wird in 1\u200amin neugestartet.')

        success, txt = common.shell_shutdown('-r', '+1')
        if not success:
            logging.getLogger().error('[HelheimrBot] Error rebooting the pi. ' + txt)
            self.__safe_edit_callback_query(query, 'Fehler beim Neustarten. ' + txt)
        else:
            thread = threading.Thread(target=self.shutdown)
            thread.daemon = True
            thread.start()

    def __cmd_reboot(self, update, context):
        """Reboots the PC."""
        if self._is_modifying_heating:
            self.__safe_send(update.message.chat_id,
                'Heizungsstatus wird gerade von einem anderen Chat geändert.\nBitte versuche es in ein paar Sekunden nochmal.')
            return
        self._is_modifying_heating = True
        keyboard = [[telegram.InlineKeyboardButton("Ja, sicher!", callback_data=type(self).CALLBACK_SYSTEM_REBOOT),
                 telegram.InlineKeyboardButton("Abbrechen", callback_data=type(self).CALLBACK_SYSTEM_CANCEL)]]
        self._is_modifying_heating = self.__safe_message_reply(
            update, 'Raspberry wirklich neustarten?',
            reply_markup=telegram.InlineKeyboardMarkup(keyboard))

    def __poweroff_helper(self, query):
        """Helper function to power off and shut down the service
        in a separate thread."""
        logging.getLogger().info(
            '[HelheimrBot] User {} requested system shutdown (power-off).'.format(
                query.from_user.first_name))
        self.__safe_edit_callback_query(query, 'Raspberry wird in 1\u200amin heruntergefahren.')

        success, txt = common.shell_shutdown('-r', '+1')
        if not success:
            logging.getLogger().error('[HelheimrBot] Error shutting down the pi. ' + txt)
            self.__safe_edit_callback_query(query, 'Fehler beim Herunterfahren. ' + txt)
        else:
            thread = threading.Thread(target=self.shutdown)
            thread.daemon = True
            thread.start()

    def __cmd_poweroff(self, update, context):
        """Powers off the PC."""
        if self._is_modifying_heating:
            self.__safe_send(update.message.chat_id,
                'Heizungsstatus wird gerade von einem anderen Chat geändert.\nBitte versuche es in ein paar Sekunden nochmal.')
            return
        self._is_modifying_heating = True
        keyboard = [[telegram.InlineKeyboardButton("Ja, sicher!", callback_data=type(self).CALLBACK_SYSTEM_POWEROFF),
                 telegram.InlineKeyboardButton("Abbrechen", callback_data=type(self).CALLBACK_SYSTEM_CANCEL)]]
        self._is_modifying_heating = self.__safe_message_reply(
            update, 'Raspberry wirklich herunterfahren?',
            reply_markup=telegram.InlineKeyboardMarkup(keyboard))

    def __cmd_restart(self, update, context):
        """Restarts the heating service."""
        if self._is_modifying_heating:
            self.__safe_send(update.message.chat_id,
                'Heizungsstatus wird gerade von einem anderen Chat geändert.\nBitte versuche es in ein paar Sekunden nochmal.')
            return
        self._is_modifying_heating = True
        keyboard = [[telegram.InlineKeyboardButton("Ja, sicher!", callback_data=type(self).CALLBACK_SERVICE_RESTART),
                 telegram.InlineKeyboardButton("Abbrechen", callback_data=type(self).CALLBACK_SERVICE_CANCEL)]]
        self._is_modifying_heating = self.__safe_message_reply(
            update, 'Raspberry wirklich neustarten?',
            reply_markup=telegram.InlineKeyboardMarkup(keyboard))

    def __cmd_service_log(self, update, context):
        """Return the last N log entries."""
        num_lines = 10
        if len(context.args) > 0:
            try:
                num_lines = common.check_positive_int(context.args[0])
            except:
                self.__safe_send(update.message.chat_id, 'Parameterfehler: Linienanzahl muss eine positive Ganzzahl sein!')
                return

        success, txt = common.shell_service_log(num_lines)
        if success:
            # Clip the most recent messages if log would be too long:
            if len(txt) > type(self).MESSAGE_MAX_LENGTH:
                txt = txt[-type(self).MESSAGE_MAX_LENGTH:]
            self.__safe_send(update.message.chat_id, txt, parse_mode=None)
        else:
            self.__safe_send(update.message.chat_id, 'Fehler beim Auslesen des Logs. ' + txt)

        # Send separate message which only lists [Heating] messages
        success, txt = common.shell_heating_log(num_lines)
        if success:
            # Clip the most recent messages if log would be too long:
            header = 'Heizungsmeldungen:\n\n'
            max_len = type(self).MESSAGE_MAX_LENGTH - len(header)
            if len(txt) > max_len:
                txt = txt[-max_len:]
            self.__safe_send(update.message.chat_id, txt, parse_mode=None)
        else:
            self.__safe_send(update.message.chat_id, 'Fehler beim Auslesen des Heizungslogs. ' + txt)

    def __cmd_update(self, update, context):
        """Perform git update"""
        self.__safe_chat_action(update.message.chat_id, action=telegram.ChatAction.TYPING)
        success, txt = common.shell_update_repository()
        if not success:
            logging.getLogger().error('[HelheimrBot] Could not update git repository: ' + txt)
            self.__safe_message_reply(update, 'Fehler beim Aktualisieren des git Repos: ' + txt, reply_markup=None)
        else:
            # Restart service
            logging.getLogger().info('[HelheimrBot] Restarting service now...')
            self.__safe_message_reply(update, 'Repo wurde aktualisiert:\n\n```\n{:s}\n```\nService wird jetzt neugestartet...'.format(txt),
                reply_markup=None)

            # ... after a short delay
            time.sleep(1.5)

            # Prevent sending the shutdown message
            self._is_restarting = True

            success, txt = common.shell_restart_service()
            if not success:
                logging.getLogger().error('[HelheimrBot] Could not restart service: ' + txt)
                self.__safe_message_reply(update, 'Fehler beim Service-Neustart: ' + txt, reply_markup=None)

    def __cmd_debug(self, update, context):
        """Debugging via telegram..."""
        if len(context.args) > 0:
            s, txt = common.shell_exec_command(' '.join(context.args))
            self.__safe_send(update.message.chat_id, 'Command succeeded: {}, Output:\n{}'.format(s, txt))
        else:
            _, txt1 = common.shell_pwd()
            _, txt2 = common.shell_whoami()
            _, txt3 = common.shell_uptime()
            self.__safe_send(update.message.chat_id, 'User "{}"\npwd: "{}"\nuptime: {}'.format(txt2, txt1, txt3))

    def start(self):
        """Handle /start - welcome message."""
        # Start polling messages from telegram servers
        self._updater.start_polling(
            poll_interval=self._poll_interval,
            timeout=self._timeout, bootstrap_retries=self._bootstrap_retries)
        # Send startup message to all authorized users
        status_txt = self.__query_status(None, detailed_report=False)
        self.broadcast_message("Hallo, ich bin online. {:s}\n\n{:s}".format(
                    _rand_flower(), status_txt))

    def broadcast_message(self, txt):
        """Send given message to all authorized chat IDs."""
        for chat_id in self._broadcast_ids:
            self.__safe_send(chat_id, common.emo(txt))

    def __shutdown_helper(self):
        """Helper to shutdown this service - should be run from a
        different thread, see
        https://github.com/python-telegram-bot/python-telegram-bot/issues/801
        """
        logging.getLogger().info("[HelheimrBot] Stopping telegram updater...")
        self._updater.stop()
        self._updater.is_idle = False
        logging.getLogger().info("[HelheimrBot] Telegram bot has been shut down.")
        self._heating.shutdown()

    def shutdown(self):
        """Initiates the shutdown sequence."""
        if not self._updater.running:
            return
        if not self._shutdown_message_sent:
            self._shutdown_message_sent = True
            if not self._is_restarting:
                # Send shutdown message (unless the service is just restarting)
                status_txt = self.__query_status(None, detailed_report=True)
                self.broadcast_message("Heizungsservice wird beendet, bis bald.\n\n{:s}".format(
                            status_txt))

            self.__shutdown_helper()

    def __idle(self):
        """Blocking call to run the updater's event loop."""
        self._updater.idle()
        logging.getLogger().info("[HelheimrBot] Telegram updater's idle() terminated")
