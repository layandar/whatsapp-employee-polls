
from flask import Flask, request, jsonify
import os
import time
import unicodedata
from datetime import datetime, timezone

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

app = Flask(__name__)

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Missing SUPABASE_URL or SUPABASE_KEY in .env")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

processed_messages = {}
DUPLICATE_WINDOW_SECONDS = 60


def find_message(data):
    candidates = [
        data.get("payload", {}).get("message")
        if isinstance(data.get("payload"), dict) else None,
        data.get("message"),
        data.get("data", {}).get("message")
        if isinstance(data.get("data"), dict) else None,
        data.get("data"),
        data
    ]

    for item in candidates:
        if isinstance(item, dict) and "chatId" in item and "body" in item:
            return item

    return None


def normalize_reply(body):
    text = unicodedata.normalize("NFKC", str(body or ""))
    text = " ".join(text.strip().lower().split())

    yes_answers = {"yes", "y", "نعم", "اه", "أه", "أيوه", "ايوه"}
    no_answers = {"no", "n", "لا", "كلا", "لأ"}

    if text in yes_answers:
        return "نعم" if any("\u0600" <= c <= "\u06ff" for c in text) else "YES"

    if text in no_answers:
        return "لا" if any("\u0600" <= c <= "\u06ff" for c in text) else "NO"

    return None


@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True) or {}
    message = find_message(data)

    if not message:
        return jsonify({"received": True}), 200

    chat_id = message.get("chatId")
    print("Incoming chat ID:", repr(chat_id))
    print("Incoming message:", repr(message.get("body")))
    from_me = message.get("fromMe")
    is_group = message.get("isGroup", False)

    if from_me is not False or is_group or not chat_id:
        return jsonify({"ignored": True}), 200

    now = time.time()
    expired = [
        key for key, timestamp in processed_messages.items()
        if now - timestamp > DUPLICATE_WINDOW_SECONDS
    ]

    for key in expired:
        del processed_messages[key]

    message_id = (
        message.get("id")
        or message.get("messageId")
        or (message.get("_data") or {}).get("id")
    )

    if message_id:
        dedup_key = f"{chat_id}:{message_id}"

        if dedup_key in processed_messages:
            return jsonify({"duplicate": True}), 200

        processed_messages[dedup_key] = now

    answer = normalize_reply(message.get("body"))

    if answer is None:
        print(f"Ignored non-poll reply from {chat_id}")
        return jsonify({"ignored": True}), 200

    try:
        employee_result = (
            supabase.table("employees")
            .select("id, name")
            .eq("whatsapp_chat_id", chat_id)
            .execute()
        )

        if not employee_result.data:
            print(f"No employee found for chat ID {chat_id}")
            return jsonify({"employee_not_found": True}), 200

        employee = employee_result.data[0]

        pending_result = (
            supabase.table("message_responses")
            .select("id, campaign_id")
            .eq("employee_id", employee["id"])
            .is_("response", "null")
            .in_("delivery_status", ["sent"])
            .order("sent_at", desc=True)
            .limit(2)
            .execute()
        )

        if not pending_result.data:
            print(f"No unanswered sent poll found for {employee['name']}")
            return jsonify({"no_pending_poll": True}), 200

        if len(pending_result.data) > 1:
            print(
                f"Multiple unanswered polls for {employee['name']}. "
                "Reply not recorded to avoid assigning it to the wrong poll."
            )
            return jsonify({"multiple_pending_polls": True}), 200

        poll = pending_result.data[0]

        supabase.table("message_responses").update({
            "response": answer,
            "responded_at": datetime.now(timezone.utc).isoformat()
        }).eq("id", poll["id"]).is_("response", "null").execute()

        print(f"Saved response from {employee['name']}: {answer}")

        return jsonify({"response_saved": True}), 200

    except Exception as error:
        print("Error processing poll response:", error)
        return jsonify({"error": "Could not save response"}), 500


@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "running"}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
