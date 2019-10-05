#!/usr/bin/python
# coding=utf-8
"""The main controlling script."""

import os
import sys

from helu import heating

class MessageBroadcaster:
    def __init__(self, telegram_bot):
        self._telegram_bot = telegram_bot

    def error(self, message):
        self.__broadcast_message(text, 'error')

    def warning(self, message):
        self.__broadcast_message(text, 'warning')

    def info(self, message):
        self.__broadcast_message(text, 'info')

    def __broadcast_message(self, text, msg_type):
        #TODO broadcast to display!!!
        if msg_type == 'info':
            telegram_msg = text
        elif msg_type == 'warning':
            telegram_msg = ':warning: ' + text
        elif msg_type == 'error':
            telegram_msg = ':bangbang: ' + text
        else:
            raise RuntimeError('Invalid message type "{}"'.format(msg_type))

        self._telegram_bot.broadcast_message(telegram_msg)


def control_heating():
    telegram_bot = None

    message_broadcaster = MessageBroadcaster(telegram_bot)
    heating.Heating.init_instance(config, message_broadcaster)
    # load configs
    # set up bot, server, scheduler, heating, weather forecast
    #TODO:
    #message_broadcaster = ...
    pass


if __name__ == '__main__':
    control_heating()
