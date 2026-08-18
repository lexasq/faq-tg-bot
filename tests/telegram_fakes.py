from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from telegram import Bot, CallbackQuery, Chat, Message, Update, User

FAKE_TOKEN = "123456:FAKEFAKEFAKEFAKEFAKEFAKEFAKEFAKEFAK"


class RecordingBot(Bot):
    """A telegram.Bot whose network-touching methods are overridden to
    just record what handlers tried to send, so tests never hit the
    real Telegram API (no token is available in this environment)."""

    def __init__(self) -> None:
        super().__init__(token=FAKE_TOKEN)
        # telegram.TelegramObject freezes attribute assignment after
        # __init__ unless the name starts with "_" — plain `self.sent = []`
        # would raise AttributeError here.
        self._sent: list[dict] = []
        self._edited: list[dict] = []
        self._documents: list[dict] = []
        self._answered_callbacks: list[dict] = []
        self._next_id = 1000

    @property
    def sent(self) -> list[dict]:
        return self._sent

    @property
    def edited(self) -> list[dict]:
        return self._edited

    @property
    def documents(self) -> list[dict]:
        return self._documents

    @property
    def answered_callbacks(self) -> list[dict]:
        return self._answered_callbacks

    async def send_document(self, chat_id, document, **kwargs):
        if hasattr(document, "input_file_content"):
            content = document.input_file_content
            filename = kwargs.get("filename") or document.filename
        elif hasattr(document, "read"):
            content = document.read()
            filename = kwargs.get("filename")
        else:
            content = document
            filename = kwargs.get("filename")
        self._documents.append({"chat_id": chat_id, "content": content, "filename": filename, "kwargs": kwargs})
        msg = Message(message_id=self._next_message_id(), date=datetime.utcnow(), chat=Chat(id=chat_id, type="private"))
        msg.set_bot(self)
        return msg

    def _next_message_id(self) -> int:
        self._next_id += 1
        return self._next_id

    async def send_message(self, chat_id, text, **kwargs):
        self._sent.append({"chat_id": chat_id, "text": text, "kwargs": kwargs})
        msg = Message(
            message_id=self._next_message_id(),
            date=datetime.utcnow(),
            chat=Chat(id=chat_id, type="private"),
            text=text,
        )
        msg.set_bot(self)
        return msg

    async def edit_message_text(self, text, chat_id=None, message_id=None, inline_message_id=None, **kwargs):
        self._edited.append({"text": text, "chat_id": chat_id, "message_id": message_id, "kwargs": kwargs})
        msg = Message(
            message_id=message_id or self._next_message_id(),
            date=datetime.utcnow(),
            chat=Chat(id=chat_id or 0, type="private"),
            text=text,
        )
        msg.set_bot(self)
        return msg

    async def edit_message_reply_markup(self, chat_id=None, message_id=None, inline_message_id=None, **kwargs):
        self._edited.append({"text": None, "chat_id": chat_id, "message_id": message_id, "kwargs": kwargs})
        msg = Message(
            message_id=message_id or self._next_message_id(),
            date=datetime.utcnow(),
            chat=Chat(id=chat_id or 0, type="private"),
        )
        msg.set_bot(self)
        return msg

    async def answer_callback_query(self, callback_query_id, text=None, **kwargs):
        self._answered_callbacks.append({"callback_query_id": callback_query_id, "text": text, "kwargs": kwargs})
        return True

    async def delete_message(self, chat_id, message_id, **kwargs):
        return True


def set_bot_identity(bot: RecordingBot, *, bot_id: int = 999, username: str = "test_faq_bot") -> None:
    # Bot.id/.username normally come from get_me() during Application
    # initialize(), which hits the network. Setting the private cache
    # directly gives handlers a usable identity without that call.
    bot._bot_user = User(id=bot_id, is_bot=True, first_name="TestBot", username=username)


def make_user(user_id: int = 1, name: str = "Admin") -> User:
    return User(id=user_id, first_name=name, is_bot=False)


def make_message(bot: RecordingBot, *, chat_id: int, user_id: int, text: str, message_id: int = 1) -> Message:
    chat = Chat(id=chat_id, type="private")
    msg = Message(message_id=message_id, date=datetime.utcnow(), chat=chat, from_user=make_user(user_id), text=text)
    msg.set_bot(bot)
    return msg


def make_update_for_message(bot: RecordingBot, *, chat_id: int, user_id: int, text: str, update_id: int = 1) -> Update:
    return Update(update_id=update_id, message=make_message(bot, chat_id=chat_id, user_id=user_id, text=text))


def make_update_for_group_message(
    bot: RecordingBot,
    *,
    chat_id: int,
    user_id: int,
    text: str,
    update_id: int = 1,
    message_id: int = 1,
    reply_to_message: Message | None = None,
    entities=None,
    message_thread_id: int | None = None,
    edit_date=None,
    user_is_bot: bool = False,
) -> Update:
    chat = Chat(id=chat_id, type="supergroup")
    from_user = User(id=user_id, first_name="U", is_bot=user_is_bot)
    msg = Message(
        message_id=message_id,
        date=datetime.utcnow(),
        chat=chat,
        from_user=from_user,
        text=text,
        reply_to_message=reply_to_message,
        entities=entities,
        message_thread_id=message_thread_id,
        edit_date=edit_date,
    )
    msg.set_bot(bot)
    return Update(update_id=update_id, message=msg)


def make_update_for_callback(
    bot: RecordingBot,
    *,
    chat_id: int,
    user_id: int,
    data: str,
    message_text: str = "",
    update_id: int = 1,
    callback_id: str = "cb1",
    chat_type: str = "private",
) -> Update:
    chat = Chat(id=chat_id, type=chat_type)
    user = make_user(user_id)
    msg = Message(message_id=1, date=datetime.utcnow(), chat=chat, from_user=user, text=message_text)
    msg.set_bot(bot)
    cq = CallbackQuery(id=callback_id, from_user=user, chat_instance="ci1", data=data, message=msg)
    cq.set_bot(bot)
    return Update(update_id=update_id, callback_query=cq)


def make_context(
    bot_data: dict, args: list[str] | None = None, bot: Bot | None = None, job_queue=None
) -> SimpleNamespace:
    return SimpleNamespace(
        user_data={}, bot_data=bot_data, chat_data={}, args=args or [], bot=bot, job_queue=job_queue
    )
