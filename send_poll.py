
import os
import json
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
OPENWA_URL = os.getenv("OPENWA_URL", "http://127.0.0.1:2785")
OPENWA_SESSION_ID = os.getenv("OPENWA_SESSION_ID", "test-bot")
OPENWA_API_KEY = os.getenv("OPENWA_API_KEY")

if not all([SUPABASE_URL, SUPABASE_KEY, OPENWA_API_KEY]):
    raise ValueError(
        "Check SUPABASE_URL, SUPABASE_KEY, and "
        "OPENWA_API_KEY in your .env file."
    )

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


def get_templates():
    result = (
        supabase.table("message_templates")
        .select("id, name, body, response_options")
        .execute()
    )
    return result.data


def get_employees():
    result = (
        supabase.table("employees")
        .select("id, name, phone_number, department, whatsapp_chat_id")
        .eq("is_active", True)
        .not_.is_("whatsapp_chat_id", "null")
        .execute()
    )
    return result.data


def choose_items(items, label):
    print(f"\nAvailable {label}:")

    for index, item in enumerate(items, start=1):
        print(f"{index}. {item['name']}")

    raw = input(
        "\nEnter the numbers to select, separated by commas: "
    ).strip()

    try:
        indexes = [int(value.strip()) - 1 for value in raw.split(",")]
        if not indexes or len(set(indexes)) != len(indexes):
            raise ValueError

        if any(index < 0 or index >= len(items) for index in indexes):
            raise ValueError

        return [items[index] for index in indexes]

    except ValueError:
        print("Invalid selection. Please run the script again.")
        return []


def send_whatsapp_message(chat_id, message):
    url = (
        f"{OPENWA_URL}/api/sessions/"
        f"{OPENWA_SESSION_ID}/messages/send-text"
    )

    response = requests.post(
        url,
        headers={
            "X-API-Key": OPENWA_API_KEY,
            "Content-Type": "application/json"
        },
        json={
            "chatId": chat_id,
            "text": message
        },
        timeout=20
    )

    response.raise_for_status()
    return response


def main():
    templates = get_templates()

    if not templates:
        print("No message templates found in Supabase.")
        return

    selected_templates = choose_items(templates, "templates")

    if not selected_templates:
        return

    template = selected_templates[0]

    employees = get_employees()

    if not employees:
        print(
            "No active employees with a WhatsApp chat ID were found."
        )
        return

    selected_employees = choose_items(employees, "employees")

    if not selected_employees:
        return

    print("\nPoll preview")
    print("-" * 40)
    print(f"Template: {template['name']}")
    print(f"Message: {template['body']}")
    print(f"Recipients: {len(selected_employees)}")
    print(f"Responses: {template['response_options']}")
    print("-" * 40)

    confirmation = input(
        "Type SEND to send these WhatsApp messages: "
    ).strip()

    if confirmation != "SEND":
        print("Cancelled. No messages were sent.")
        return

    campaign_name = input(
        "Enter a name for this poll/campaign: "
    ).strip()

    if not campaign_name:
        print("Campaign name cannot be empty.")
        return

    campaign_result = (
        supabase.table("message_campaigns")
        .insert({
            "template_id": template["id"],
            "name": campaign_name,
            "status": "sending"
        })
        .execute()
    )

    campaign = campaign_result.data[0]
    campaign_id = campaign["id"]

    response_rows = [
        {
            "campaign_id": campaign_id,
            "employee_id": employee["id"],
            "delivery_status": "pending"
        }
        for employee in selected_employees
    ]

    supabase.table("message_responses").insert(
        response_rows
    ).execute()

    successful = 0
    failed = 0

    for employee in selected_employees:
        print(f"\nSending to {employee['name']}...")

        try:
            send_whatsapp_message(
                employee["whatsapp_chat_id"],
                template["body"]
            )

            supabase.table("message_responses").update({
                "sent_at": datetime.now(timezone.utc).isoformat(),
                "delivery_status": "sent"
            }).eq(
                "campaign_id", campaign_id
            ).eq(
                "employee_id", employee["id"]
            ).execute()

            successful += 1
            print("Message sent successfully.")

        except Exception as error:
            failed += 1
            print(f"Failed to send: {error}")

            supabase.table("message_responses").update({
                "delivery_status": "failed"
            }).eq(
                "campaign_id", campaign_id
            ).eq(
                "employee_id", employee["id"]
            ).execute()

    final_status = (
        "sent" if failed == 0
        else "partial_failure" if successful > 0
        else "failed"
    )

    supabase.table("message_campaigns").update({
        "status": final_status
    }).eq("id", campaign_id).execute()

    print("\nCampaign finished.")
    print(f"Campaign ID: {campaign_id}")
    print(f"Sent successfully: {successful}")
    print(f"Failed: {failed}")


if __name__ == "__main__":
    main()
