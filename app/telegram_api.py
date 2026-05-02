# app/telegram_api.py
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class IncomingEvent:
    update_id: int
    chat_id: int
    user_id: int | None
    text: str | None = None
    callback_data: str | None = None
    callback_query_id: str | None = None
    contact_phone: str | None = None
    document: dict[str, Any] | None = None


def parse_telegram_update(payload: dict[str, Any]) -> IncomingEvent:
    update_id = payload.get("update_id", 0)

    if "callback_query" in payload:
        cq = payload["callback_query"]
        msg = cq.get("message", {})
        return IncomingEvent(
            update_id=update_id,
            chat_id=msg.get("chat", {}).get("id"),
            user_id=cq.get("from", {}).get("id"),
            callback_data=cq.get("data"),
            callback_query_id=cq.get("id"),
        )

    msg = payload.get("message", {})

    doc = None
    if "document" in msg:
        d = msg["document"]
        doc = {
            "file_id": d["file_id"],
            "file_unique_id": d.get("file_unique_id"),
            "file_name": d.get("file_name") or "document.bin",
            "mime_type": d.get("mime_type") or "application/octet-stream",
            "file_size": d.get("file_size", 0),
        }
    elif "photo" in msg:
        photo = max(msg["photo"], key=lambda x: x.get("file_size", 0))
        doc = {
            "file_id": photo["file_id"],
            "file_unique_id": photo.get("file_unique_id"),
            "file_name": "telegram_photo.jpg",
            "mime_type": "image/jpeg",
            "file_size": photo.get("file_size", 0),
        }

    contact_phone = msg.get("contact", {}).get("phone_number") if "contact" in msg else None

    return IncomingEvent(
        update_id=update_id,
        chat_id=msg.get("chat", {}).get("id"),
        user_id=msg.get("from", {}).get("id"),
        text=msg.get("text"),
        contact_phone=contact_phone,
        document=doc,
    )


class TelegramGateway:
    def __init__(self, bot_token: str) -> None:
        self._base = f"https://api.telegram.org/bot{bot_token}"
        self._file_base = f"https://api.telegram.org/file/bot{bot_token}"
        self._client = httpx.Client(timeout=60)

    def set_webhook(self, url: str, secret_token: str) -> dict[str, Any]:
        resp = self._client.post(
            f"{self._base}/setWebhook",
            json={
                "url": url,
                "secret_token": secret_token,
                "allowed_updates": ["message", "callback_query"],
                "drop_pending_updates": False,
            },
        )
        resp.raise_for_status()
        return resp.json()

    def send_message(self, chat_id: int, text: str, reply_markup: dict | None = None) -> dict:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        resp = self._client.post(f"{self._base}/sendMessage", json=payload)
        resp.raise_for_status()
        return resp.json()

    def answer_callback_query(self, callback_query_id: str) -> None:
        self._client.post(
            f"{self._base}/answerCallbackQuery",
            json={"callback_query_id": callback_query_id},
        )

    def get_file_bytes(self, file_id: str) -> tuple[bytes, dict[str, Any]]:
        meta = self._client.post(f"{self._base}/getFile", json={"file_id": file_id})
        meta.raise_for_status()
        file_obj = meta.json()["result"]
        resp = self._client.get(f"{self._file_base}/{file_obj['file_path']}")
        resp.raise_for_status()
        return resp.content, file_obj

    @staticmethod
    def phone_keyboard() -> dict:
        return {
            "keyboard": [[{"text": "Compartir teléfono", "request_contact": True}]],
            "resize_keyboard": True,
            "one_time_keyboard": True,
        }

    @staticmethod
    def vacancy_keyboard(vacancies: list[tuple[str, str]]) -> dict:
        return {
            "inline_keyboard": [
                [{"text": title, "callback_data": f"vac:{vid}"}]
                for vid, title in vacancies
            ]
        }

    @staticmethod
    def qa_keyboard() -> dict:
        return {
            "inline_keyboard": [
                [{"text": "Continuar", "callback_data": "go:continue"}],
                [{"text": "Hablar con RRHH", "callback_data": "go:human"}],
            ]
        }
