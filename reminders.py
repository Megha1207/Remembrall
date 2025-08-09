import time
import threading
from datetime import datetime, timedelta, timezone
from twilio.rest import Client
import notion
from storage import get_phone_for_task
import os

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER")  # e.g. 'whatsapp:+1234567890'

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

sent_reminders = set()  # track sent reminders to avoid duplicates

def send_whatsapp_message(to, message):
    try:
        client.messages.create(
            from_=TWILIO_WHATSAPP_NUMBER,
            body=message,
            to=f"whatsapp:{to}"
        )
        print(f"[{datetime.now(timezone.utc).isoformat()}] Sent WhatsApp message to {to}: {message}")
    except Exception as e:
        print(f"[{datetime.now(timezone.utc).isoformat()}] Failed to send WhatsApp message to {to}: {e}")

def check_and_send_reminders():
    while True:
        now = datetime.now(timezone.utc)
        print(f"[{now.isoformat()}] Checking reminders...")

        tasks = notion.list_tasks()
        for task in tasks:
            if task.get("done"):
                continue

            reminder_str = task.get("reminder")
            if not reminder_str:
                continue

            try:
                reminder_time = datetime.fromisoformat(reminder_str.replace("Z", "+00:00"))
            except Exception as e:
                print(f"[{now.isoformat()}] Error parsing reminder time '{reminder_str}': {e}")
                continue

            user_phone = get_phone_for_task(task.get("name", ""))
            if not user_phone:
                print(f"[{now.isoformat()}] No phone number found for task '{task.get('name', '')}'")
                continue

            two_minutes_before = reminder_time - timedelta(minutes=2)

            # Reminder keys for tracking
            before_key = (task.get("name", ""), "2min_before")
            due_key = (task.get("name", ""), "due_now")

            # Send reminder 2 minutes before (1-minute window)
            if two_minutes_before <= now < two_minutes_before + timedelta(minutes=1):
                if before_key not in sent_reminders:
                    print(f"[{now.isoformat()}] Sending 2-minutes prior reminder for task '{task.get('name', '')}'")
                    send_whatsapp_message(user_phone, f"Reminder: Task '{task.get('name', '')}' is coming up in 2 minutes!")
                    sent_reminders.add(before_key)

            # Send reminder exactly at the time (1-minute window)
            if reminder_time <= now < reminder_time + timedelta(minutes=1):
                if due_key not in sent_reminders:
                    print(f"[{now.isoformat()}] Sending due now reminder for task '{task.get('name', '')}'")
                    send_whatsapp_message(user_phone, f"Reminder: Task '{task.get('name', '')}' is due now!")
                    sent_reminders.add(due_key)

        time.sleep(60)

def start_reminder_thread():
    thread = threading.Thread(target=check_and_send_reminders, daemon=True)
    thread.start()
    print("Reminder thread started.")
