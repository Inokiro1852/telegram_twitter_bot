import asyncio
import html
import logging
import re
from io import BytesIO

import aiohttp
from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import BufferedInputFile, LinkPreviewOptions, Message
from aiogram.utils.media_group import MediaGroupBuilder
from PIL import Image

router = Router()

logger = logging.getLogger(__name__)


twitter_pattern = r'https://(?:www\.)?(?:x|twitter)\.com/[\w]+/status/(\d+)'
bluesky_pattern = r'https://(?:www\.)?bsky\.app/profile/([\w\-\.]+)/post/(\w+)'


async def get_twitter_data(tweet: str, max_retries: int = 2, delay: float = 1.0):
    find_twitter = re.match(twitter_pattern, tweet, re.IGNORECASE)
    find_bluesky = re.match(bluesky_pattern, tweet, re.IGNORECASE)
    if find_twitter:
        api_url = f'https://api.fxtwitter.com/2/status/{find_twitter.group(1)}'
    elif find_bluesky:
        api_url = f'https://api.fxbsky.app/2/status/{find_bluesky.group(1)}/{find_bluesky.group(2)}'
    else:
        return None
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for attempt in range(max_retries + 1):
            try:
                async with session.get(api_url) as response:
                    if response.status == 200:
                        return await response.json()
                    if 400 <= response.status < 500 and response.status != 429:
                        return None
            except (aiohttp.ClientError, asyncio.TimeoutError):
                pass
            if attempt < max_retries:
                await asyncio.sleep(delay * (attempt + 1))
    return None


async def get_tweet_caption(tweet, link, spoiler, limit=1024):
    text = tweet.get('text') or ''
    text_range = tweet.get('raw_text', {}).get('display_text_range')
    if text_range:
        text = text[text_range[0] :]
    author_name = tweet.get('author', {}).get('name') or ''
    budget = limit - len(author_name) - 20
    if len(text) > budget:
        text = text[: budget - 1] + '...'
    text = html.escape(text)
    author_name = html.escape(author_name)
    caption = (
        (
            f'{author_name}:\n<tg-spoiler>{text}</tg-spoiler>\n\n<a href="{link}">link</a>'
            if text
            else f'{author_name}: <a href="{link}">link</a>'
        )
        if spoiler
        else (
            f'{author_name}:\n{text}\n\n<a href="{link}">link</a>'
            if text
            else f'{author_name}: <a href="{link}">link</a>'
        )
    )
    return caption


def _stitch_images(image_data_list):
    images = [Image.open(BytesIO(data)).convert('RGB') for data in image_data_list]
    if not images:
        return

    min_height = min(img.height for img in images)

    resized_images = []

    for img in images:
        if img.height != min_height:
            scale_ratio = min_height / img.height
            new_width = round(img.width * scale_ratio)

            img = img.resize((new_width, min_height), Image.Resampling.LANCZOS)

        resized_images.append(img)

    total_width = sum(img.width for img in resized_images)

    glued_img = Image.new('RGB', (total_width, min_height))

    x_offset = 0
    for img in resized_images:
        glued_img.paste(img, (x_offset, 0))
        x_offset += img.width

    max_dimension = 10000
    max_size = 10 * 1024 * 1024
    quality = 95
    width, height = glued_img.size

    if width + height >= max_dimension:
        scale_ratio = max_dimension / (width + height)
        new_width = int(width * scale_ratio)
        new_height = int(height * scale_ratio)

        glued_img = glued_img.resize((new_width, new_height), Image.Resampling.LANCZOS)

    while True:
        output = BytesIO()
        glued_img.save(output, format='JPEG', quality=quality, optimize=True)
        file_size = output.tell()

        if file_size <= max_size or quality <= 10:
            break

        quality -= 5

    output.seek(0)
    return output


async def glue_images(links) -> BytesIO | None:
    if not isinstance(links, list) or len(links) < 2:
        return None
    results = await asyncio.gather(*(fetch_bytes(link) for link in links))
    image_data_list = [data for data in results if data]
    if not image_data_list or len(image_data_list) != len(links):
        return None
    return await asyncio.to_thread(_stitch_images, image_data_list)


async def fetch_bytes(link: str, retries: int = 2) -> bytes:
    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        for attempt in range(retries + 1):
            try:
                async with session.get(link) as response:
                    if response.status == 200:
                        return await response.read()
                    if 400 <= response.status < 500 and response.status != 429:
                        return None
            except (aiohttp.ClientError, asyncio.TimeoutError):
                pass
            if attempt < retries:
                await asyncio.sleep(attempt + 1)

    return None


async def send_tweet(tweet, message, caption, spoiler, glue, reply: bool = False):
    answer_animation = message.reply_animation if reply else message.answer_animation
    answer_video = message.reply_video if reply else message.answer_video
    answer_photo = message.reply_photo if reply else message.answer_photo
    answer_media_group = (
        message.reply_media_group if reply else message.answer_media_group
    )
    answer_text = message.reply if reply else message.answer

    if tweet.get('media', {}).get('videos', []):
        video_info = tweet['media']['videos'][0]
        video_url = video_info['url']
        if video_info.get('type') == 'gif':
            try:
                sent = await answer_animation(
                    animation=video_url,
                    caption=caption,
                    has_spoiler=spoiler,
                    parse_mode=ParseMode.HTML,
                )
            except TelegramBadRequest:
                logger.info('BAD REQUEST')
                fetched_video = await fetch_bytes(video_url)
                if not fetched_video:
                    await message.reply('Some error occurred.')
                    return
                sent = await answer_video(
                    video=BufferedInputFile(fetched_video, filename='video.mp4'),
                    caption=caption,
                    has_spoiler=spoiler,
                    parse_mode=ParseMode.HTML,
                )
        else:
            try:
                sent = await answer_video(
                    video=video_url,
                    caption=caption,
                    has_spoiler=spoiler,
                    parse_mode=ParseMode.HTML,
                )
            except TelegramBadRequest:
                logger.info('BAD REQUEST')
                fetched_video = await fetch_bytes(video_url)
                if not fetched_video:
                    await message.reply('Some error occurred.')
                    return
                sent = await answer_video(
                    video=BufferedInputFile(fetched_video, filename='video.mp4'),
                    caption=caption,
                    has_spoiler=spoiler,
                    parse_mode=ParseMode.HTML,
                )

    elif tweet.get('media', {}).get('photos', []):
        urls = [photo['url'] for photo in tweet['media']['photos']]
        if glue and len(tweet['media']['photos']) > 1:
            glued_img_buffer = await glue_images(urls)
            if glued_img_buffer:
                input_img = BufferedInputFile(
                    glued_img_buffer.getvalue(), filename='image.jpeg'
                )
                sent = await answer_photo(
                    photo=input_img,
                    caption=caption,
                    has_spoiler=spoiler,
                    parse_mode=ParseMode.HTML,
                )
            else:
                sent = await answer_text(
                    text=caption,
                    parse_mode=ParseMode.HTML,
                    link_preview_options=LinkPreviewOptions(is_disabled=True),
                )
        else:

            def build_album(photos, caption, spoiler):
                builder = MediaGroupBuilder(caption=caption)
                for photo in photos:
                    builder.add_photo(
                        media=photo,
                        has_spoiler=spoiler,
                        parse_mode=ParseMode.HTML,
                    )
                return builder.build()

            try:
                sent = await answer_media_group(
                    media=build_album(urls, caption, spoiler),
                )
            except TelegramBadRequest:
                logger.info('BAD REQUEST')
                fetched_photos = await asyncio.gather(
                    *(fetch_bytes(url) for url in urls)
                )
                files = [
                    BufferedInputFile(file=photo, filename=f'photo_{i}.jpeg')
                    for i, photo in enumerate(fetched_photos)
                    if photo
                ]
                if not files:
                    await message.reply('Some error occurred.')
                    return

                sent = await answer_media_group(
                    media=build_album(files, caption, spoiler),
                )

    else:
        sent = await answer_text(
            text=caption,
            parse_mode=ParseMode.HTML,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
    return sent[0] if isinstance(sent, list) else sent


@router.message(F.text)
async def fixing_twitter_links(message: Message):
    message_text = message.text
    message_text = message_text.strip()
    message_text = message_text.split()
    link = message_text[0]
    link_match = re.match(twitter_pattern, link, re.IGNORECASE) or re.match(
        bluesky_pattern, link, re.IGNORECASE
    )
    if not link_match:
        return
    link = link_match.group(0)
    parameters = [parameter.lower() for parameter in message_text[1:]]
    logger.info(parameters)
    response = await get_twitter_data(link)
    # logger.info(response)
    if not response or 'status' not in response:
        await message.reply('Some error occurred.')
        return
    tweet = response['status']
    spoiler = any(parameter in ('s', 'с') for parameter in parameters)
    glue = any(parameter in ('g', 'к') for parameter in parameters)
    reply = any(parameter in ('r', 'р') for parameter in parameters)
    reverse_reply = any(parameter in ('rr', 'рр') for parameter in parameters)
    if reverse_reply and tweet.get('quote', {}):
        tweet_reply = tweet.get('quote', {})
        link2 = tweet.get('quote', {}).get('url')
        caption = await get_tweet_caption(tweet_reply, link2, spoiler)
        sent = await send_tweet(
            tweet_reply, message, caption, spoiler, glue, reply=False
        )
        if not sent:
            return
        caption = await get_tweet_caption(tweet, link, spoiler)
        await send_tweet(tweet, sent, caption, spoiler, glue, reply=True)
    else:
        caption = await get_tweet_caption(tweet, link, spoiler)
        sent = await send_tweet(tweet, message, caption, spoiler, glue, reply=False)
        if not sent:
            return
        if reply and tweet.get('quote', {}):
            tweet = tweet.get('quote', {})
            link2 = tweet.get('url')
            caption = await get_tweet_caption(tweet, link2, spoiler)
            await send_tweet(tweet, sent, caption, spoiler, glue, reply=True)
    try:
        await message.delete()
    except TelegramAPIError:
        pass
