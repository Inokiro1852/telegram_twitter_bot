import asyncio
import html
import random
import re
from io import BytesIO

import aiohttp
from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import BufferedInputFile, LinkPreviewOptions, Message
from aiogram.utils.media_group import MediaGroupBuilder
from PIL import Image

router = Router()


async def get_twitter_data(tweet: str, max_retries: int = 2, delay: float = 1.0):
    api_url = tweet.replace('https://x.com', 'https://api.fxtwitter.com')
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


async def get_tweet_caption(tweet, link, spoiler):
    text = tweet.get('text') or ''
    text_range = tweet.get('raw_text', {}).get('display_text_range')
    if text_range:
        text = text[text_range[0] :]
    text = html.escape(text)
    author_name = tweet.get('author', {}).get('name')
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


def __stitch_images(image_data_list):
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
    quality = 100
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


async def glue_images(links) -> BytesIO:
    if isinstance(links, list) and len(links) > 1:
        async with aiohttp.ClientSession() as session:
            tasks = [session.get(url) for url in links]
            responses = await asyncio.gather(*tasks)

            image_data_list = []
            for resp in responses:
                if isinstance(resp, aiohttp.ClientResponse) and resp.status == 200:
                    image_data_list.append(await resp.read())

        if not image_data_list:
            return None

        return await asyncio.to_thread(__stitch_images, image_data_list)
    else:
        return None


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
                asyncio.sleep(attempt + 1)

    return None


async def send_tweet(tweet, message, caption, spoiler, glue, reply: bool = False):
    if isinstance(message, list):
        message = message[0]
    sent = None
    if tweet.get('media', {}).get('videos', []):
        video_info = tweet['media']['videos'][0]
        video_url = video_info['url']
        if video_info.get('type') == 'gif':
            sent = (
                await message.answer_animation(
                    animation=video_url,
                    caption=caption,
                    has_spoiler=spoiler,
                    parse_mode=ParseMode.HTML,
                )
                if not reply
                else await message.reply_animation(
                    animation=video_url,
                    caption=caption,
                    has_spoiler=spoiler,
                    parse_mode=ParseMode.HTML,
                )
            )
        else:
            try:
                sent = (
                    await message.answer_video(
                        video=video_url,
                        caption=caption,
                        has_spoiler=spoiler,
                        parse_mode=ParseMode.HTML,
                    )
                    if not reply
                    else await message.reply_video(
                        video=video_url,
                        caption=caption,
                        has_spoiler=spoiler,
                        parse_mode=ParseMode.HTML,
                    )
                )
            except TelegramBadRequest:
                video = await fetch_bytes(video_url)
                sent = (
                    await message.answer_video(
                        video=BufferedInputFile(video, filename='video.mp4'),
                        caption=caption,
                        has_spoiler=spoiler,
                        parse_mode=ParseMode.HTML,
                    )
                    if not reply
                    else await message.reply_video(
                        video=BufferedInputFile(video, filename='video.mp4'),
                        caption=caption,
                        has_spoiler=spoiler,
                        parse_mode=ParseMode.HTML,
                    )
                )

    elif tweet.get('media', {}).get('photos', []):
        if glue and len(tweet['media']['photos']) > 1:
            urls = [photo['url'] for photo in tweet['media']['photos']]
            glued_img_buffer = await glue_images(urls)
            input_img = BufferedInputFile(
                glued_img_buffer.getvalue(), filename='image.jpeg'
            )
            sent = (
                await message.answer_photo(
                    photo=input_img,
                    caption=caption,
                    has_spoiler=spoiler,
                    parse_mode=ParseMode.HTML,
                )
                if not reply
                else await message.reply_photo(
                    photo=input_img,
                    caption=caption,
                    has_spoiler=spoiler,
                    parse_mode=ParseMode.HTML,
                )
            )
        else:
            media_builder = MediaGroupBuilder(caption=caption)
            for photo in tweet['media']['photos']:
                media_builder.add_photo(
                    media=photo['url'],
                    has_spoiler=spoiler,
                )
            try:
                sent = (
                    await message.answer_media_group(
                        media=media_builder.build(),
                        parse_mode=ParseMode.HTML,
                    )
                    if not reply
                    else await message.reply_media_group(
                        media=media_builder.build(),
                        parse_mode=ParseMode.HTML,
                    )
                )
            except TelegramBadRequest:
                photo = await fetch_bytes(tweet['media']['photos'][0]['url'])
                sent = (
                    await message.answer_photo(
                        BufferedInputFile(photo, filename='image.jpeg'),
                        caption=caption,
                        has_spoiler=spoiler,
                        parse_mode=ParseMode.HTML,
                    )
                    if not reply
                    else await message.reply_photo(
                        BufferedInputFile(photo, filename='image.jpeg'),
                        caption=caption,
                        has_spoiler=spoiler,
                        parse_mode=ParseMode.HTML,
                    )
                )

    else:
        sent = (
            await message.answer(
                text=caption,
                parse_mode=ParseMode.HTML,
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )
            if not reply
            else await message.reply(
                text=caption,
                parse_mode=ParseMode.HTML,
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )
        )
    return sent


@router.message(F.text)
async def fixing_twitter_links(message: Message):
    message_text = message.text
    message_text = message_text.strip()
    pattern = r'(?<!\S)([dDдД](\d+))(?!\S)'
    search = re.search(pattern, message_text)
    if search and message.from_user.id != 8636035849 and not message.forward_from:
        number = int(search.groups()[1])
        number = min(number, 9999)
        number = max(number, 2)
        message_text = f'<code>(d{number})</code>: {random.randint(1, number)}'
        await message.reply(message_text)
        return
    message_text = message_text.split()
    if 'https://x.com' in message_text[0]:
        link = message_text[0]
        pos = link.find('/video/')
        if pos != -1:
            link = link[:pos]
        pos = link.find('/photo/')
        if pos != -1:
            link = link[:pos]
        response = await get_twitter_data(link)
        if not response:
            return
        tweet = response['tweet']
        spoiler = False
        glue = False
        reply = False
        reverse_reply = False
        for parameter in message_text[1:]:
            if parameter == 's' or parameter == 'с':
                spoiler = True
            if parameter == 'r' or parameter == 'р':
                reply = True
            if parameter == 'rr' or parameter == 'рр':
                reverse_reply = True
            if parameter == 'g' or parameter == 'к':
                glue = True
        if reverse_reply and tweet.get('quote', {}):
            tweet_reply = tweet.get('quote', {})
            link2 = tweet.get('quote', {}).get('url')
            caption = await get_tweet_caption(tweet_reply, link2, spoiler)
            sent = await send_tweet(
                tweet_reply, message, caption, spoiler, glue, reply=False
            )

            caption = await get_tweet_caption(tweet, link, spoiler)
            await send_tweet(tweet, sent, caption, spoiler, glue, reply=True)
        else:
            caption = await get_tweet_caption(tweet, link, spoiler)
            sent = await send_tweet(tweet, message, caption, spoiler, glue, reply=False)
            if reply and tweet.get('quote', {}):
                tweet = tweet.get('quote', {})
                link2 = tweet.get('url')
                caption = await get_tweet_caption(tweet, link2, spoiler)
                await send_tweet(tweet, sent, caption, spoiler, glue, reply=True)
        await message.delete()
