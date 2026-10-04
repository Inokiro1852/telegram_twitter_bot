from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

router = Router()


@router.message(CommandStart())
async def hello(message: Message) -> None:
    await message.answer(f'Hello, {message.from_user.first_name}!')
