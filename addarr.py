#!/usr/bin/env python3

import logging
import re
import math

import yaml

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Updater,
    CommandHandler,
    ConversationHandler,
    CallbackQueryHandler,
    MessageHandler,
    Filters,
)

from commons import checkId, authentication, format_bytes
from definitions import LANG_PATH
import radarr as radarr
import sonarr as sonarr
import logger

from config import config

__version__ = "0.3"

# Set up logging
logLevel = logging.DEBUG if config.get("debugLogging", False) else logging.INFO
logger = logger.getLogger("addarr", logLevel, config.get("logToConsole", False))
logger.debug(f"Addarr v{__version__} starting up...")

SERIE_MOVIE_AUTHENTICATED, READ_CHOICE, GIVE_OPTION, GIVE_PATHS, TSL_NORMAL = range(5)

updater = Updater(config["telegram"]["token"], use_context=True)
dispatcher = updater.dispatcher
lang = config["language"]

transcript = yaml.safe_load(open(LANG_PATH, encoding="utf8"))
transcript = transcript[lang]


def main():
    auth_handler_command = CommandHandler(config["entrypointAuth"], authentication)
    auth_handler_text = MessageHandler(
                            Filters.regex(
                                re.compile(r"^" + config["entrypointAuth"] + "$", re.IGNORECASE)
                            ),
                            authentication,
                        )
    allSeries_handler_command = CommandHandler(config["entrypointAllSeries"], allSeries)
    allSeries_handler_text = MessageHandler(
                            Filters.regex(
                                re.compile(r"^" + config["entrypointAllSeries"] + "$", re.IGNORECASE)
                            ),
                            allSeries,
                        )
    addMovieserie_handler = ConversationHandler(
        entry_points=[
            CommandHandler(config["entrypointAdd"], startSerieMovie),
            CommandHandler(transcript["Movie"], startSerieMovie),
            CommandHandler(transcript["Serie"], startSerieMovie),
            MessageHandler(
                Filters.regex(
                    re.compile(r'^' + config["entrypointAdd"] + '$', re.IGNORECASE)
                ),
                startSerieMovie,
            ),
        ],
        states={
            SERIE_MOVIE_AUTHENTICATED: [MessageHandler(Filters.text, choiceSerieMovie)],
            READ_CHOICE: [
                MessageHandler(
                    Filters.regex(f'^({transcript["Movie"]}|{transcript["Serie"]})$'),
                    searchSerieMovie,
                ),
                CallbackQueryHandler(searchSerieMovie, pattern=f'^({transcript["Movie"]}|{transcript["Serie"]})$')
            ],
            GIVE_OPTION: [
                CallbackQueryHandler(pathSerieMovie, pattern=f'({transcript["Add"]})'),
                MessageHandler(
                    Filters.regex(f'^({transcript["Add"]})$'), 
                    pathSerieMovie
                ),
                CallbackQueryHandler(nextOption, pattern=f'({transcript["Next result"]})'),
                MessageHandler(
                    Filters.regex(f'^({transcript["Next result"]})$'), 
                    nextOption
                ),
                MessageHandler(
                    Filters.regex(f'^({transcript["New"]})$'), 
                    startSerieMovie
                ),
                CallbackQueryHandler(startSerieMovie, pattern=f'({transcript["New"]})'),
            ],
            GIVE_PATHS: [
                CallbackQueryHandler(addSerieMovie, pattern="^(Path: )(.*)$"),
            ],
        },
        fallbacks=[
            CommandHandler("stop", stop),
            MessageHandler(Filters.regex("^(?i)Stop$"), stop),
            CallbackQueryHandler(stop, pattern=f"^(?i)Stop$"),
        ],
    )
    if config["transmission"]["enable"]:
        import transmission as transmission
        changeTransmissionSpeed_handler = ConversationHandler(
            entry_points=[
                CommandHandler(config["entrypointTransmission"], transmission.transmission),
                MessageHandler(
                    Filters.regex(
                        re.compile(
                            r"" + config["entrypointTransmission"] + "", re.IGNORECASE
                        )
                    ),
                    transmission.transmission,
                ),
            ],
            states={
                transmission.TSL_NORMAL: [
                    CallbackQueryHandler(transmission.changeSpeedTransmission),
                ]
            },
            fallbacks=[
                CommandHandler("stop", stop),
                MessageHandler(Filters.regex("^(Stop|stop)$"), stop),
            ],
        )
        dispatcher.add_handler(changeTransmissionSpeed_handler)

    dispatcher.add_handler(auth_handler_command)
    dispatcher.add_handler(auth_handler_text)
    dispatcher.add_handler(allSeries_handler_command)
    dispatcher.add_handler(allSeries_handler_text)
    dispatcher.add_handler(addMovieserie_handler)

    help_handler_command = CommandHandler(config["entrypointHelp"], help)
    dispatcher.add_handler(help_handler_command)

    logger.info(transcript["Start chatting"])
    updater.start_polling()
    updater.idle()


def stop(update, context):
    clearUserData(context)
    context.bot.send_message(
        chat_id=update.effective_message.chat_id, text=transcript["End"]
    )
    return ConversationHandler.END


def startSerieMovie(update : Update, context):
    if not checkId(update):
        context.bot.send_message(
            chat_id=update.effective_message.chat_id, text=transcript["Authorize"]
        )
        return SERIE_MOVIE_AUTHENTICATED

    if update.message is not None:
        reply = update.message.text.lower()
    elif update.callback_query is not None:
        reply = update.callback_query.data.lower()
    else:
        return SERIE_MOVIE_AUTHENTICATED

    if reply[1:] in [
        transcript["Serie"].lower(),
        transcript["Movie"].lower(),
    ]:
        logger.debug(
            f"User issued {reply} command, so setting user_data[choice] accordingly"
        )
        context.user_data.update(
            {
                "choice": transcript["Serie"]
                if reply[1:] == transcript["Serie"].lower()
                else transcript["Movie"]
            }
        )
    elif reply == transcript["New"].lower():
        logger.debug("User issued New command, so clearing user_data")
        clearUserData(context)
    
    context.bot.send_message(
        chat_id=update.effective_message.chat_id, text='\U0001F3F7 '+transcript["Title"]
    )
    return SERIE_MOVIE_AUTHENTICATED

def choiceSerieMovie(update, context):
    if not checkId(update):
        if (
            authentication(update, context) == "added"
        ):  # To also stop the beginning command
            return ConversationHandler.END
    elif update.message.text.lower() == "/stop".lower() or update.message.text.lower() == "stop".lower():
        return stop(update, context)
    else:
        if update.message is not None:
            reply = update.message.text
        elif update.callback_query is not None:
            reply = update.callback_query.data
        else:
            return SERIE_MOVIE_AUTHENTICATED

        if reply.lower() not in [
            transcript["Serie"].lower(),
            transcript["Movie"].lower(),
        ]:
            logger.debug(
                f"User entered a title {reply}"
            )
            context.user_data["title"] = reply

        if context.user_data.get("choice") in [
            transcript["Serie"],
            transcript["Movie"],
        ]:
            logger.debug(
                f"user_data[choice] is {context.user_data['choice']}, skipping step of selecting movie/series"
            )
            return searchSerieMovie(update, context)
        else:
            keyboard = [
                [
                    InlineKeyboardButton(
                        '\U0001F3AC '+transcript["Movie"],
                        callback_data=transcript["Movie"]
                    ),
                    InlineKeyboardButton(
                        '\U0001F4FA '+transcript["Serie"],
                        callback_data=transcript["Serie"]
                    ),
                ],
                [ InlineKeyboardButton(
                        '\U0001F50D '+transcript["New"],
                        callback_data=transcript["New"]
                    ),
                ]
            ]
            markup = InlineKeyboardMarkup(keyboard)
            update.message.reply_text(transcript["What is this?"], reply_markup=markup)
            return READ_CHOICE


def searchSerieMovie(update, context):
    title = context.user_data["title"]

    if not context.user_data.get("choice"):
        choice = None
        if update.message is not None:
            choice = update.message.text
        elif update.callback_query is not None:
            choice = update.callback_query.data
        context.user_data["choice"] = choice
    
    choice = context.user_data["choice"]
    context.user_data["position"] = 0

    service = getService(context)

    position = context.user_data["position"]

    searchResult = service.search(title)
    if searchResult:
        context.user_data["output"] = service.giveTitles(searchResult)

        keyboard = [
                [
                    InlineKeyboardButton(
                        '\U00002795 '+transcript["Add"],
                        callback_data=transcript["Add"]
                    ),
                ],[
                    InlineKeyboardButton(
                        '\U000023ED '+transcript["Next result"],
                        callback_data=transcript["Next result"]
                    ),
                ],[
                    InlineKeyboardButton(
                        '\U0001F5D1 '+transcript["New"],
                        callback_data=transcript["New"]
                    ),
                ],[
                    InlineKeyboardButton(
                        '\U0001F6D1 '+transcript["Stop"],
                        callback_data=transcript["Stop"]
                    ),
                ],
            ]
        markup = InlineKeyboardMarkup(keyboard)
        context.bot.send_message(
            chat_id=update.effective_message.chat_id,
            text=transcript[choice.lower()]["This"],
        )
        context.bot.sendPhoto(
            chat_id=update.effective_message.chat_id,
            photo=context.user_data["output"][position]["poster"],
        )
        text = f"{context.user_data['output'][position]['title']} ({context.user_data['output'][position]['year']})"
        context.bot.send_message(
            chat_id=update.effective_message.chat_id, text=text, reply_markup=markup
        )
        return GIVE_OPTION
    else:
        context.bot.send_message(
            chat_id=update.effective_message.chat_id, text=transcript["No results"],
        )
        clearUserData(context)
        return ConversationHandler.END


def nextOption(update, context):
    position = context.user_data["position"] + 1
    context.user_data["position"] = position

    choice = context.user_data["choice"]

    if position < len(context.user_data["output"]):
        keyboard = [
                [
                    InlineKeyboardButton(
                        '\U00002795 '+transcript[choice.lower()]["Add"],
                        callback_data=transcript[choice.lower()]["Add"]
                    ),
                ],[
                    InlineKeyboardButton(
                        '\U000023ED '+transcript["Next result"],
                        callback_data=transcript["Next result"]
                    ),
                ],[
                    InlineKeyboardButton(
                        '\U0001F5D1 '+transcript["New"],
                        callback_data=transcript["New"]
                    ),
                ],[
                    InlineKeyboardButton(
                        '\U0001F6D1 '+transcript["Stop"],
                        callback_data=transcript["Stop"]
                    ),
                ],
            ]
        markup = InlineKeyboardMarkup(keyboard)

        context.bot.send_message(
            chat_id=update.effective_message.chat_id,
            text=transcript[choice.lower()]["This"],
        )
        context.bot.sendPhoto(
            chat_id=update.effective_message.chat_id,
            photo=context.user_data["output"][position]["poster"],
        )
        text = (
            context.user_data["output"][position]["title"]
            + " ("
            + str(context.user_data["output"][position]["year"])
            + ")"
        )
        context.bot.send_message(
            chat_id=update.effective_message.chat_id, text=text, reply_markup=markup
        )
        return GIVE_OPTION
    else:
        context.bot.send_message(
            chat_id=update.effective_message.chat_id,
            text=transcript["Last result"]
        )
        clearUserData(context)
        return ConversationHandler.END


def pathSerieMovie(update, context):
    service = getService(context)
    paths = service.getRootFolders()
    context.user_data.update({"paths": [p["path"] for p in paths]})
    if len(paths) == 1:
        # There is only 1 path, so use it!
        logger.debug("Only found 1 path, so proceeding with that one...")
        context.user_data["path"] = paths[0]["path"]
        return addSerieMovie(update, context)
    logger.debug("Found multiple paths: "+str(paths))

    keyboard = []
    for p in paths:
        free = format_bytes(p['freeSpace'])
        keyboard += [[
            InlineKeyboardButton(
                f"Path: {p['path']}, Free: {free}",
                callback_data=f"Path: {p['path']}"
            ),
        ]]
    markup = InlineKeyboardMarkup(keyboard)

    context.bot.send_message(
        chat_id=update.effective_message.chat_id,
        text=transcript["Select a path"],
        reply_markup=markup,
    )
    return GIVE_PATHS


def addSerieMovie(update, context):
    position = context.user_data["position"]
    choice = context.user_data["choice"]
    idnumber = context.user_data["output"][position]["id"]

    if not context.user_data.get("path"):
        # Path selection should be in the update message
        path = None
        if update.callback_query is not None:
            try_path = update.callback_query.data.replace("Path: ", "").strip()
            if try_path in context.user_data.get("paths", {}):
                context.user_data["path"] = try_path
                path = try_path
        if path is None:
            logger.debug(
                f"Callback query [{update.callback_query.data.replace('Path: ', '').strip()}] doesn't match any of the paths. Sending paths for selection..."
            )
            return pathSerieMovie(update, context)

    path = context.user_data["path"]
    service = getService(context)

    if not service.inLibrary(idnumber):
        if service.addToLibrary(idnumber, path):
            context.bot.send_message(
                chat_id=update.effective_message.chat_id,
                text=transcript[choice.lower()]["Success"],
            )
            clearUserData(context)
            return ConversationHandler.END
        else:
            context.bot.send_message(
                chat_id=update.effective_message.chat_id,
                text=transcript[choice.lower()]["Failed"],
            )
            clearUserData(context)
            return ConversationHandler.END
    else:
        context.bot.send_message(
            chat_id=update.effective_message.chat_id,
            text=transcript[choice.lower()]["Exist"],
        )
        clearUserData(context)
        return ConversationHandler.END

def allSeries(update, context):
    if not checkId(update):
        if (
            authentication(update, context) == "added"
        ):  # To also stop the beginning command
            return ConversationHandler.END
    else:
        result = sonarr.allSeries()
        string = ""
        for serie in result:
            string += "• " \
            + serie["title"] \
            + " (" \
            + str(serie["year"]) \
            + ")" \
            + "\n" \
            + "        status: " \
            + serie["status"] \
            + "\n" \
            + "        monitored: " \
            + str(serie["monitored"]).lower() \
            + "\n"
        
        #max length of a message is 4096 chars
        if len(string) <= 4096:
            context.bot.send_message(
                chat_id=update.effective_message.chat_id,
                text=string,
            )
        #split string if longer then 4096 chars
        else: 
            neededSplits = math.ceil(len(string) / 4096)
            positionNewLine = []
            index = 0
            while index < len(string): #Get positions of newline, so that the split will happen after a newline
                i = string.find("\n", index)
                if i == -1:
                    return positionNewLine
                positionNewLine.append(i)
                index+=1

            #split string at newline closest to maxlength
            stringParts = []
            lastSplit = timesSplit = 0
            i = 4096
            while i > 0 and len(string)>4096: 
                if timesSplit < neededSplits:
                    if i+lastSplit in positionNewLine:
                        stringParts.append(string[0:i])
                        string = string[i+1:]
                        timesSplit+=1
                        lastSplit = i
                        i = 4096
                i-=1
            stringParts.append(string)

            #print every substring
            for subString in stringParts:
                context.bot.send_message(
                chat_id=update.effective_message.chat_id,
                text=subString,
            )
        return ConversationHandler.END

def getService(context):
    if context.user_data.get("choice") == transcript["Serie"]:
        return sonarr
    elif context.user_data.get("choice") == transcript["Movie"]:
        return radarr
    else:
        raise ValueError(
            f"Cannot determine service based on unknown or missing choice: {context.user_data.get('choice')}."
        )

def help(update, context):
    context.bot.send_message(
        chat_id=update.effective_message.chat_id, text=transcript["Help"].format(
            config["entrypointHelp"],
            config["entrypointAuth"],
            config["entrypointAdd"],
            'serie',
            'movie',
            config["entrypointAllSeries"],
            config["entrypointTransmission"],
        )
    )
    return ConversationHandler.END


def clearUserData(context):
    logger.debug(
        "Removing choice, title, position, paths, and output from context.user_data..."
    )
    for x in [
        x
        for x in ["choice", "title", "position", "output", "paths", "path"]
        if x in context.user_data.keys()
    ]:
        context.user_data.pop(x)


if __name__ == "__main__":
    main()
