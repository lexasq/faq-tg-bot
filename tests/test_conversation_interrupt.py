"""Regression test for the "Категорія doesn't work" bug: python-telegram-
bot's ConversationHandler only consults entry_points when NO conversation
is currently tracked for a (chat, user) key. Every entry-card action
(Відповідь/Патерни/Категорія, /add, and the /review create/link actions)
shares one ConversationHandler, so an abandoned edit on one entry left
the user "stuck" in that state — tapping any OTHER entry-card button
matched nothing in the stuck state's own handlers and nothing in
entry_points either, so it was silently dropped with zero feedback.

This exercises admin_conversation.check_update() directly — the exact
method PTB's dispatcher calls to decide whether the handler claims an
update — rather than calling handler functions directly, since a direct
call bypasses PTB's conversation-state gating entirely and would not
have caught this bug.
"""
from app.handlers import admin_crud
from tests.telegram_fakes import RecordingBot, make_update_for_callback

CHAT_ID = 8008
USER_ID = CHAT_ID


def _stuck_key(bot):
    update = make_update_for_callback(bot, chat_id=CHAT_ID, user_id=USER_ID, data="ecedit:ans:aaaaaaa")
    return admin_crud.admin_conversation._get_key(update)


def test_category_button_is_dropped_while_stuck_in_another_edit_before_fix_would_fail():
    # sanity check: without a tracked conversation, the entry point matches
    bot = RecordingBot()
    fresh_update = make_update_for_callback(bot, chat_id=CHAT_ID, user_id=USER_ID, data="ecedit:cat:bbbbbbb")
    assert admin_crud.admin_conversation.check_update(fresh_update) is not None


def test_category_button_interrupts_a_stuck_answer_edit():
    bot = RecordingBot()
    key = _stuck_key(bot)
    # simulate: admin tapped "Відповідь" on entry A and never sent /done —
    # PTB is now tracking this user as being in EDIT_ANSWER
    admin_crud.admin_conversation._conversations[key] = admin_crud.EDIT_ANSWER

    category_tap = make_update_for_callback(bot, chat_id=CHAT_ID, user_id=USER_ID, data="ecedit:cat:bbbbbbb")
    result = admin_crud.admin_conversation.check_update(category_tap)

    del admin_crud.admin_conversation._conversations[key]
    assert result is not None, "Категорія tap must not be silently dropped while another edit is stuck"


def test_add_command_also_interrupts_a_stuck_edit():
    bot = RecordingBot()
    key = _stuck_key(bot)
    admin_crud.admin_conversation._conversations[key] = admin_crud.EDIT_PATTERNS

    from tests.telegram_fakes import make_update_for_message

    add_tap = make_update_for_message(bot, chat_id=CHAT_ID, user_id=USER_ID, text="/add")
    result = admin_crud.admin_conversation.check_update(add_tap)

    del admin_crud.admin_conversation._conversations[key]
    assert result is not None


def test_plain_text_while_stuck_is_still_consumed_by_the_active_state_not_a_fallback():
    # the fix must not turn fallbacks into a catch-all: plain text typed
    # while EDIT_ANSWER is active should still be handled by that state's
    # own MessageHandler (accumulated as an answer line), same as before
    bot = RecordingBot()
    key = _stuck_key(bot)
    admin_crud.admin_conversation._conversations[key] = admin_crud.EDIT_ANSWER

    from tests.telegram_fakes import make_update_for_message

    stray = make_update_for_message(bot, chat_id=CHAT_ID, user_id=USER_ID, text="just some text")
    check_result = admin_crud.admin_conversation.check_update(stray)
    matched_handler = check_result[2]

    del admin_crud.admin_conversation._conversations[key]
    assert matched_handler.callback is admin_crud.edit_answer_line
