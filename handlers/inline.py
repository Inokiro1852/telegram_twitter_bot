from aiogram import Bot, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    BufferedInputFile,
    ChosenInlineResult,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQuery,
    InlineQueryResultArticle,
    InputMediaAnimation,
    InputMediaPhoto,
    InputMediaVideo,
    InputTextMessageContent,
    LinkPreviewOptions,
)

import handlers.bot_funcs as twitter
from config import config

router = Router()


@router.inline_query()
async def handle_all_inline_query(inline_query: InlineQuery) -> None:
    query = inline_query.query.strip()
    results = []
    reply_markup = None

    if 'https://x.com/' in query:
        results.clear()
        link = query.strip()
        link = link.split()
        message_text = '<i>Fetching tweet</i>'
        button_text = 'Fetching tweet...'

        if len(link) > 1 and (link[1] == 'r' or link[1] == 'р'):
            result_id = 'rr'
            reply_markup = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=button_text,
                            callback_data='loading',
                        )
                    ]
                ]
            )
            results.append(
                InlineQueryResultArticle(
                    id=result_id,
                    title='Fetch tweet',
                    description='with reversed reply',
                    input_message_content=InputTextMessageContent(
                        message_text=message_text,
                    ),
                    reply_markup=reply_markup,
                )
            )

            result_id = 'srr'
            reply_markup = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=button_text,
                            callback_data='loading',
                        )
                    ]
                ]
            )
            results.append(
                InlineQueryResultArticle(
                    id=result_id,
                    title='Fetch tweet',
                    description='with spoiler and reversed reply',
                    input_message_content=InputTextMessageContent(
                        message_text=message_text,
                    ),
                    reply_markup=reply_markup,
                )
            )
        else:
            result_id = 'none'
            reply_markup = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text=button_text, callback_data='loading')]
                ]
            )
            results.append(
                InlineQueryResultArticle(
                    id=result_id,
                    title='Fetch tweet',
                    description='default',
                    input_message_content=InputTextMessageContent(
                        message_text=message_text,
                    ),
                    reply_markup=reply_markup,
                )
            )
            result_id = 's'
            reply_markup = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=button_text,
                            callback_data='loading',
                        )
                    ]
                ]
            )
            results.append(
                InlineQueryResultArticle(
                    id=result_id,
                    title='Fetch tweet',
                    description='with spoiler',
                    input_message_content=InputTextMessageContent(
                        message_text=message_text,
                    ),
                    reply_markup=reply_markup,
                )
            )

            result_id = 'r'
            reply_markup = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=button_text,
                            callback_data='loading',
                        )
                    ]
                ]
            )
            results.append(
                InlineQueryResultArticle(
                    id=result_id,
                    title='Fetch tweet',
                    description='with reply',
                    input_message_content=InputTextMessageContent(
                        message_text=message_text,
                    ),
                    reply_markup=reply_markup,
                )
            )

            result_id = 'sr'
            reply_markup = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=button_text,
                            callback_data='loading',
                        )
                    ]
                ]
            )
            results.append(
                InlineQueryResultArticle(
                    id=result_id,
                    title='Fetch tweet',
                    description='with spoiler and reply',
                    input_message_content=InputTextMessageContent(
                        message_text=message_text,
                    ),
                    reply_markup=reply_markup,
                )
            )

    await inline_query.answer(
        results=results,
        cache_time=0,
        is_personal=True,
    )


async def send_tweet(bot, message_id, tweet, caption, spoiler, reply, reverse_reply):
    reply_markup = None
    if reply and tweet.get('quote', {}):
        link = tweet.get('quote', {}).get('url')
        reply_markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text='Reply', switch_inline_query_current_chat=link
                    )
                ]
            ]
        )
    elif reverse_reply:
        link = reverse_reply
        reply_markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text='Reply', switch_inline_query_current_chat=link
                    )
                ]
            ]
        )
    if tweet.get('media', {}).get('videos', []):
        video_info = tweet['media']['videos'][0]
        if video_info.get('type') == 'gif':
            gif = InputMediaAnimation(
                media=video_info['url'], caption=caption, has_spoiler=spoiler
            )
            if spoiler:
                await bot.send_animation(config.dump_chat_id, video_info['url'])
            await bot.edit_message_media(
                media=gif, inline_message_id=message_id, reply_markup=reply_markup
            )
        else:
            video = InputMediaVideo(
                media=video_info['url'], caption=caption, has_spoiler=spoiler
            )
            if spoiler:
                await bot.send_video(config.dump_chat_id, video_info['url'])
            await bot.edit_message_media(
                media=video, inline_message_id=message_id, reply_markup=reply_markup
            )
    elif tweet.get('media', {}).get('photos', []):
        if len(tweet['media']['photos']) > 1:
            urls = [photo['url'] for photo in tweet['media']['photos']]
            glued_img_buffer = await twitter.glue_images(urls)
            buffered_img = BufferedInputFile(
                glued_img_buffer.getvalue(), filename='image.jpeg'
            )
            photo_msg = await bot.send_photo(config.dump_chat_id, buffered_img)
            photo_url = photo_msg.photo[-1].file_id
            photo_input = InputMediaPhoto(
                media=photo_url, caption=caption, has_spoiler=spoiler
            )
        else:
            photo_url = tweet['media']['photos'][0]['url']
            photo_input = InputMediaPhoto(
                media=photo_url, caption=caption, has_spoiler=spoiler
            )
        try:
            if spoiler:
                await bot.send_photo(config.dump_chat_id, photo_url)
            await bot.edit_message_media(
                media=photo_input,
                inline_message_id=message_id,
                reply_markup=reply_markup,
            )
        except TelegramBadRequest:
            photo = await twitter.fetch_bytes(tweet['media']['photos'][0]['url'])
            photo_input = InputMediaPhoto(
                media=BufferedInputFile(photo, filename='image.jpeg'),
                caption=caption,
                has_spoiler=spoiler,
            )
            await bot.edit_message_media(
                media=photo_input,
                inline_message_id=message_id,
                reply_markup=reply_markup,
            )
    else:
        await bot.edit_message_text(
            text=caption,
            inline_message_id=message_id,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
            reply_markup=reply_markup,
        )


@router.chosen_inline_result()
async def inline_result(chosen_result: ChosenInlineResult, bot: Bot):
    if not chosen_result.inline_message_id:
        return
    elif chosen_result.query.startswith('https://x.com/'):
        link = chosen_result.query.strip()
        link = link.split()[0]
        pos = link.find('/video/')
        if pos != -1:
            link = link[:pos]
        pos = link.find('/photo/')
        if pos != -1:
            link = link[:pos]
        data = chosen_result.result_id
        spoiler = False
        reply = False
        reverse_reply = False
        if data == 's':
            spoiler = True
        elif data == 'r':
            reply = True
        elif data == 'sr':
            spoiler = True
            reply = True
        elif data == 'rr':
            reply = True
            reverse_reply = True
        elif data == 'srr':
            reply = True
            reverse_reply = True
            spoiler = True
        response = await twitter.get_twitter_data(link)
        if response and not isinstance(response, str):
            tweet = response['status']
        elif response and isinstance(response, str):
            await bot.edit_message_text(
                text=f'Error: {response}',
                inline_message_id=chosen_result.inline_message_id,
            )
            return
        else:
            await bot.edit_message_text(
                text='Some error occurred',
                inline_message_id=chosen_result.inline_message_id,
            )
            return
        if not tweet.get('quote'):
            reverse_reply = False
        if reverse_reply and tweet.get('quote'):
            reverse_reply = link
            tweet = tweet.get('quote')
            link = tweet.get('url')
            caption = await twitter.get_tweet_caption(tweet, link, spoiler)
        else:
            caption = await twitter.get_tweet_caption(tweet, link, spoiler)
        await send_tweet(
            bot,
            chosen_result.inline_message_id,
            tweet,
            caption,
            spoiler,
            reply,
            reverse_reply,
        )
