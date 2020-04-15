#!/usr/bin/python
# coding=utf-8
"""The broadcaster, taking care of broadcasting messages ;-)"""

import logging


#TODO telegram: send error to all authorized chats
class MessageBroadcaster:
    __instance = None

    @staticmethod
    def instance():
        """Returns the singleton."""
        if MessageBroadcaster.__instance is None:
            MessageBroadcaster()
        return MessageBroadcaster.__instance

    def __init__(self):
        """Virtually private constructor."""
        if MessageBroadcaster.__instance is not None:
            raise RuntimeError("MessageBroadcaster is a singleton!")
        MessageBroadcaster.__instance = self
        self._telegram_bot = None

    def set_telegram_bot(self, bot):
        self._telegram_bot = bot

    def error(self, message):
        self.__broadcast_message(message, 'error')

    def warning(self, message):
        self.__broadcast_message(message, 'warning')

    def info(self, message):
        self.__broadcast_message(message, 'info')

    # Aliases
    failure = error
    warn = warning
    information = info

    def __broadcast_message(self, text, msg_type):
        #TODO broadcast to display!!!
        if msg_type == 'info':
            telegram_msg = text
        elif msg_type == 'warning':
            telegram_msg = ':warning: ' + text
        elif msg_type == 'error':
            telegram_msg = ':bangbang: ' + text
        else:
            telegram_msg = 'Unknown message type ({}): {}'.format(msg_type, text)

        if self._telegram_bot is not None:
            self._telegram_bot.broadcast_message(telegram_msg)
        else:
            logging.getLogger().error('[MessageBroadcaster] Telegram bot is not available to broadcast:\n\n'
                                      + telegram_msg + '\n')
