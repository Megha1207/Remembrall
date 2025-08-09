import os
import requests
from storage import set_phone_for_task  # import the function to save phone locally

NOTION_API_URL = "https://api.notion.com/v1/pages"
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")
NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_VERSION = "2022-06-28"

headers = {
    "Authorization": f"Bearer {NOTION_API_KEY}",
    "Content-Type": "application/json",
    "Notion-Version": NOTION_VERSION,
}

def add_task(task_name: str, reminder_datetime: str = None, user_phone: str = None) -> bool:
    if not NOTION_DATABASE_ID or not NOTION_API_KEY:
        print("Error: Missing Notion DB ID or API Key")
        return False

    properties = {
        "Name": {
            "title": [
                {
                    "text": {"content": task_name}
                }
            ]
        },
        "Done": {
            "checkbox": False
        }
    }

    # Add User property only if you want tasks filtered by user in Notion
    if user_phone:
        properties["User"] = {
            "rich_text": [
                {"text": {"content": user_phone}}
            ]
        }

    if reminder_datetime:
        properties["Reminder"] = {
            "date": {
                "start": reminder_datetime,
                "time_zone": "Asia/Kolkata"  # Adjust timezone as needed
            }
        }

    data = {
        "parent": {"database_id": NOTION_DATABASE_ID},
        "properties": properties
    }

    try:
        resp = requests.post(NOTION_API_URL, json=data, headers=headers)
        print(f"add_task: status_code={resp.status_code}, response={resp.text}")
        success = resp.status_code in (200, 201)
    except Exception as e:
        print(f"Exception in add_task: {e}")
        success = False

    # Save user phone locally if task added successfully
    if success and user_phone:
        set_phone_for_task(task_name, user_phone)

    return success

def list_tasks(user_phone: str = None) -> list:
    if not NOTION_DATABASE_ID or not NOTION_API_KEY:
        print("Error: Missing Notion DB ID or API Key")
        return []

    query_url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"

    # Filter by user if provided
    if user_phone:
        filter_payload = {
            "filter": {
                "property": "User",
                "rich_text": {
                    "equals": user_phone
                }
            }
        }
    else:
        filter_payload = {}

    try:
        resp = requests.post(query_url, headers=headers, json=filter_payload if filter_payload else None)
        print(f"list_tasks: status_code={resp.status_code}, response={resp.text}")
        if resp.status_code != 200:
            return []
        data = resp.json()
        results = data.get("results", [])
        tasks = []
        for page in results:
            props = page.get("properties", {})
            title_property = props.get("Name", {})
            done_property = props.get("Done", {})
            reminder_property = props.get("Reminder", {})
            title_text = ""
            done = False
            reminder = None

            if "title" in title_property and title_property["title"]:
                title_text = "".join(t.get("plain_text", "") for t in title_property["title"])
            if done_property.get("checkbox") is not None:
                done = done_property.get("checkbox", False)
            if "date" in reminder_property and reminder_property["date"]:
                reminder = reminder_property["date"].get("start")

            if title_text:
                tasks.append({
                    "name": title_text,
                    "done": done,
                    "reminder": reminder
                })
        return tasks
    except Exception as e:
        print(f"Exception in list_tasks: {e}")
        return []

def list_incomplete_tasks(user_phone: str = None) -> list:
    all_tasks = list_tasks(user_phone)
    return [task for task in all_tasks if not task["done"]]

def complete_task(task_name: str, user_phone: str = None) -> bool:
    if not NOTION_DATABASE_ID or not NOTION_API_KEY:
        print("Error: Missing Notion DB ID or API Key")
        return False

    query_url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
    filter_conditions = [
        {
            "property": "Name",
            "title": {
                "equals": task_name
            }
        }
    ]
    if user_phone:
        filter_conditions.append({
            "property": "User",
            "rich_text": {
                "equals": user_phone
            }
        })

    filter_payload = {
        "filter": {
            "and": filter_conditions
        }
    }

    try:
        resp = requests.post(query_url, headers=headers, json=filter_payload)
        if resp.status_code != 200:
            print(f"complete_task query failed: {resp.text}")
            return False
        results = resp.json().get("results", [])
        if not results:
            print("complete_task: Task not found")
            return False

        page_id = results[0]["id"]
        update_url = f"https://api.notion.com/v1/pages/{page_id}"
        update_payload = {
            "properties": {
                "Done": {
                    "checkbox": True
                }
            }
        }
        update_resp = requests.patch(update_url, headers=headers, json=update_payload)
        if update_resp.status_code in (200, 201):
            return True
        else:
            print(f"complete_task update failed: {update_resp.text}")
            return False
    except Exception as e:
        print(f"Exception in complete_task: {e}")
        return False

def delete_task(task_name: str, user_phone: str = None) -> bool:
    if not NOTION_DATABASE_ID or not NOTION_API_KEY:
        print("Error: Missing Notion DB ID or API Key")
        return False

    query_url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
    filter_conditions = [
        {
            "property": "Name",
            "title": {
                "equals": task_name
            }
        }
    ]
    if user_phone:
        filter_conditions.append({
            "property": "User",
            "rich_text": {
                "equals": user_phone
            }
        })

    filter_payload = {
        "filter": {
            "and": filter_conditions
        }
    }

    try:
        resp = requests.post(query_url, headers=headers, json=filter_payload)
        if resp.status_code != 200:
            print(f"delete_task query failed: {resp.text}")
            return False
        results = resp.json().get("results", [])
        if not results:
            print("delete_task: Task not found")
            return False

        page_id = results[0]["id"]
        update_url = f"https://api.notion.com/v1/pages/{page_id}"
        update_payload = {"archived": True}
        update_resp = requests.patch(update_url, headers=headers, json=update_payload)
        if update_resp.status_code in (200, 201):
            return True
        else:
            print(f"delete_task update failed: {update_resp.text}")
            return False
    except Exception as e:
        print(f"Exception in delete_task: {e}")
        return False
