import logging
import re

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

twitter_pattern = r'https://(?:www\.)?(?:x|twitter)\.com/[\w]+/status/(\d+)'
bluesky_pattern = r'https://(?:www\.)?bsky\.app/profile/([\w\-\.]+)/post/(\w+)'


logger = logging.getLogger(__name__)

DEFAULT_VARIANTS = [
    ('none', 'default'),
    ('s', 'with spoiler'),
    ('r', 'with reply'),
    ('sr', 'with spoiler and reply'),
]

REVERSE_VARIANTS = [
    ('rr', 'with reversed reply'),
    ('srr', 'with spoiler and reversed reply'),
]


@router.inline_query()
async def handle_all_inline_query(inline_query: InlineQuery) -> None:
    query = inline_query.query.strip()
    results = []

    if re.match(twitter_pattern, query, re.IGNORECASE) or re.match(
        bluesky_pattern, query, re.IGNORECASE
    ):
        parts = query.split()
        message_text = '<i>Fetching tweet</i>'
        button_text = 'Fetching tweet...'
        reversed_mode = len(parts) > 1 and parts[1] in ('r', 'р')
        variants = REVERSE_VARIANTS if reversed_mode else DEFAULT_VARIANTS

        for result_id, description in variants:
            results.append(
                InlineQueryResultArticle(
                    id=result_id,
                    title='Fetch tweet',
                    description=description,
                    input_message_content=InputTextMessageContent(
                        message_text=message_text,
                    ),
                    reply_markup=InlineKeyboardMarkup(
                        inline_keyboard=[
                            [
                                InlineKeyboardButton(
                                    text=button_text,
                                    callback_data='loading',
                                )
                            ]
                        ]
                    ),
                )
            )

    await inline_query.answer(
        results=results,
        cache_time=0,
        is_personal=True,
    )


async def send_tweet(
    bot, message_id, tweet, caption, spoiler, reply, reverse_reply, reply_link
):
    reply_markup = None
    # Dumping media with spoiler is needed, because telegram doesn't want to do it without hashing first
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
        link = reply_link
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
            try:
                await bot.edit_message_media(
                    media=video, inline_message_id=message_id, reply_markup=reply_markup
                )
            except TelegramBadRequest:
                logger.info('Bad Request')
                video_bytes = await twitter.fetch_bytes(video_info['url'])
                if not video_bytes:
                    await bot.edit_message_text(
                        text='Some error occurred',
                        inline_message_id=message_id,
                    )
                    return
                msg = await bot.send_video(
                    config.dump_chat_id, BufferedInputFile(video_bytes, 'video.mp4')
                )
                video = InputMediaVideo(
                    media=msg.video.file_id, caption=caption, has_spoiler=spoiler
                )
                await bot.edit_message_media(
                    media=video, inline_message_id=message_id, reply_markup=reply_markup
                )
    elif tweet.get('media', {}).get('photos', []):
        if len(tweet['media']['photos']) > 1:
            urls = [photo['url'] for photo in tweet['media']['photos']]
            glued_img_buffer = await twitter.glue_images(urls)
            if not glued_img_buffer:
                await bot.edit_message_text(
                    text='Some error occurred',
                    inline_message_id=message_id,
                )
                return
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
            if spoiler and not len(tweet['media']['photos']) > 1:
                await bot.send_photo(config.dump_chat_id, photo_url)
            await bot.edit_message_media(
                media=photo_input,
                inline_message_id=message_id,
                reply_markup=reply_markup,
            )
        except TelegramBadRequest:
            logger.info('Bad Request')
            photo = await twitter.fetch_bytes(tweet['media']['photos'][0]['url'])
            msg = await bot.send_photo(
                config.dump_chat_id, BufferedInputFile(photo, 'image.jpeg')
            )
            photo_input = InputMediaPhoto(
                media=msg.photo[-1].file_id,
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
    query = chosen_result.query.strip()
    link_match = re.match(twitter_pattern, query, re.IGNORECASE) or re.match(
        bluesky_pattern, query, re.IGNORECASE
    )
    if not link_match:
        return
    link = link_match.group(0)
    data = chosen_result.result_id

    spoiler = data in ('s', 'sr', 'srr')
    reply = data in ('r', 'sr')
    reverse_reply = data in ('rr', 'srr')
    try:
        response = await twitter.get_twitter_data(link)
        if not response or 'status' not in response:
            await bot.edit_message_text(
                text='Some error occurred',
                inline_message_id=chosen_result.inline_message_id,
            )
            return
        tweet = response['status']
        reply_link = ''
        if not tweet.get('quote'):
            reverse_reply = False
        if reverse_reply and tweet.get('quote'):
            reply_link = link
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
            reply_link,
        )
    except Exception:
        logger.error('Some error occurred.')
        await bot.edit_message_text(
            text='Some error occurred.',
            inline_message_id=chosen_result.inline_message_id,
        )
