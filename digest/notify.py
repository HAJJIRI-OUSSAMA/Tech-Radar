"""Telegram delivery (roadmap 1.5).

Three message types, all first-class:
  - digest      the 3-7 items that cleared the bar
  - quiet       "nothing major today" — a FEATURE, not an absence (05_CONVENTIONS.md)
  - failure     the pipeline broke; says so loudly instead of looking like a quiet day

HTML parse mode, not Markdown: Telegram's MarkdownV2 requires escaping ~18 characters and
article titles are full of them ("C++", "[dead]", "a.b_c"). HTML needs exactly three.

Setup: talk to @BotFather -> /newbot -> copy the token. Then message your new bot once and
open https://api.telegram.org/bot<TOKEN>/getUpdates to find your chat id.
"""
from __future__ import annotations

import html
import logging
import os

import requests

log = logging.getLogger("digest.notify")

API = "https://api.telegram.org/bot{token}/sendMessage"
TIMEOUT = 20
MAX_LEN = 4096          # Telegram hard limit per message

ACTION_ICON = {"learn": "\U0001F4D6", "aware": "\U0001F441"}   # book / eye


def credentials() -> tuple[str, str] | None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return None
    return token, chat_id


def _esc(text: str) -> str:
    """Escape the three characters Telegram's HTML mode cares about."""
    return html.escape(str(text), quote=False)


_SOURCE_NAMES = {"hn": "HN", "lobsters": "Lobsters"}


def _source_label(item: dict) -> str:
    """Real source names + engagement, e.g. 'HN · 176 pts' or 'HN+Lobsters · 331 pts'.
    RSS items have engagement 0 by design, so they show a name with no count."""
    names = []
    for s in item["sources"]:
        prefix, _, rest = s.partition(":")
        names.append(rest if rest else _SOURCE_NAMES.get(prefix, prefix))
    label = "+".join(dict.fromkeys(names))  # dedupe, keep order
    eng = item.get("engagement", 0)
    if eng > 0:
        label += f" \u00b7 {eng} pts"
    return label


def format_digest(selected: list[dict]) -> str:
    """Render the digest. Kept pure so it can be tested without touching the network."""
    if not selected:
        return format_quiet()

    n = len(selected)
    lines = [f"<b>Tech Radar</b> \u2014 {n} item{'s' if n != 1 else ''}", ""]

    for item in selected:
        icon = ACTION_ICON.get(item["action"], "")
        title = _esc(item["title"])
        # Sources are more honest than a single 'source': cross-source agreement is signal.
        kinds = _source_label(item)        
        lines.append(
            f"{icon} <b>{item['score']}/10</b> \u00b7 <i>{_esc(item['category'])}</i>\n"
            f'<a href="{_esc(item["url"])}">{title}</a>\n'
            f"{_esc(item['why'])}\n"
            f"<code>{_esc(kinds)}</code>"
        )
        lines.append("")

    text = "\n".join(lines).strip()
    if len(text) > MAX_LEN:
        text = text[:MAX_LEN - 20].rsplit("\n", 1)[0] + "\n\u2026"
    return text


def format_quiet() -> str:
    """The quiet evening. Deliberately designed, not an error path."""
    return (
        "<b>Tech Radar</b>\n\n"
        "\U0001F7E2 Nothing major today.\n"
        "<i>Nothing cleared the bar \u2014 that is the correct outcome on a slow evening.</i>"
    )


def format_failure(reason: str) -> str:
    """A broken run must never be mistaken for a quiet one."""
    return (
        "<b>Tech Radar \u2014 run failed</b>\n\n"
        f"<code>{_esc(reason)[:500]}</code>\n\n"
        "<i>No digest today. This is a failure, not a quiet evening.</i>"
    )


def send(text: str, disable_preview: bool = True) -> bool:
    """Send one message. Returns success; never raises — delivery failure must not
    destroy a digest that was already computed and archived."""
    creds = credentials()
    if creds is None:
        log.warning("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set, skipping delivery")
        return False

    token, chat_id = creds
    try:
        resp = requests.post(
            API.format(token=token),
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": disable_preview,
            },
            timeout=TIMEOUT,
        )
        if resp.status_code != 200:
            # Telegram puts the actual reason in the body; the status alone is useless.
            log.error("telegram send failed (%s): %s", resp.status_code, resp.text[:300])
            return False
        log.info("telegram message delivered")
        return True
    except Exception as e:
        log.error("telegram send failed: %s", e)
        return False


def send_digest(selected: list[dict], dry_run: bool = False) -> bool:
    text = format_digest(selected)
    if dry_run:
        print("\n--- telegram preview (not sent) ---")
        print(text)
        print("--- end preview ---\n")
        return True
    return send(text)


def send_failure(reason: str, dry_run: bool = False) -> bool:
    text = format_failure(reason)
    if dry_run:
        print("\n--- telegram failure preview (not sent) ---")
        print(text)
        return True
    return send(text)