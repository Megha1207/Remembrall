import os
import re
import requests
from storage import set_phone_for_task  # your local phone storage helper

NOTION_API_URL = "https://api.notion.com/v1/pages"
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")
NOTION_API_KEY = os.getenv("NOTION_API_KEY")
NOTION_VERSION = "2022-06-28"

headers = {
    "Authorization": f"Bearer {NOTION_API_KEY}",
    "Content-Type": "application/json",
    "Notion-Version": NOTION_VERSION,
}

def add_task(task_name: str, reminder_datetime: str = None, user_phone: str = None,
             priority: str = None, recurrence: str = None, tags: list[str] = None, notes: str = None) -> bool:
    if not NOTION_DATABASE_ID or not NOTION_API_KEY:
        print("Error: Missing Notion DB ID or API Key")
        return False

    properties = {
        "Name": {
            "title": [{"text": {"content": task_name}}]
        },
        "Done": {"checkbox": False}
    }

    if user_phone:
        properties["User"] = {
            "rich_text": [{"text": {"content": user_phone}}]
        }
    if reminder_datetime:
        properties["Reminder"] = {
            "date": {"start": reminder_datetime, "time_zone": "Asia/Kolkata"}
        }
    if priority:
        properties["Priority"] = {
            "select": {"name": priority.capitalize()}
        }
    if recurrence:
        properties["Recurrence"] = {
            "select": {"name": recurrence.capitalize()}
        }
    if tags:
        properties["Tags"] = {
            "multi_select": [{"name": tag.strip()} for tag in tags]
        }
    if notes:
        properties["Notes"] = {
            "rich_text": [{"text": {"content": notes}}]
        }

    data = {"parent": {"database_id": NOTION_DATABASE_ID}, "properties": properties}

    try:
        resp = requests.post(NOTION_API_URL, json=data, headers=headers)
        print(f"add_task: status_code={resp.status_code}, response={resp.text}")
        success = resp.status_code in (200, 201)
    except Exception as e:
        print(f"Exception in add_task: {e}")
        success = False

    if success and user_phone:
        set_phone_for_task(task_name, user_phone)

    return success


def list_tasks(user_phone: str = None, filter_priority: str = None, filter_tags: list[str] = None, 
               filter_done: bool = None, sort_by_reminder: bool = False) -> list:
    if not NOTION_DATABASE_ID or not NOTION_API_KEY:
        print("Error: Missing Notion DB ID or API Key")
        return []

    query_url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"

    filters = []
    if user_phone:
        filters.append({
            "property": "User",
            "rich_text": {"equals": user_phone}
        })
    if filter_priority:
        filters.append({
            "property": "Priority",
            "select": {"equals": filter_priority.capitalize()}
        })
    if filter_tags:
        filters.append({
            "property": "Tags",
            "multi_select": {
                "contains": filter_tags[0]  # Notion only supports contains on one tag at a time
            }
        })
    if filter_done is not None:
        filters.append({
            "property": "Done",
            "checkbox": {"equals": filter_done}
        })

    filter_payload = {"filter": {"and": filters}} if filters else {}

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
            priority_property = props.get("Priority", {})
            recurrence_property = props.get("Recurrence", {})
            tags_property = props.get("Tags", {})
            notes_property = props.get("Notes", {})

            title_text = ""
            done = False
            reminder = None
            priority = None
            recurrence = None
            tags = []
            notes = ""

            if "title" in title_property and title_property["title"]:
                title_text = "".join(t.get("plain_text", "") for t in title_property["title"])
            if done_property.get("checkbox") is not None:
                done = done_property.get("checkbox", False)
            if "date" in reminder_property and reminder_property["date"]:
                reminder = reminder_property["date"].get("start")
            if priority_property.get("select"):
                priority = priority_property["select"].get("name")
            if recurrence_property.get("select"):
                recurrence = recurrence_property["select"].get("name")
            if tags_property.get("multi_select"):
                tags = [t.get("name") for t in tags_property["multi_select"]]
            if "rich_text" in notes_property and notes_property["rich_text"]:
                notes = "".join(t.get("plain_text", "") for t in notes_property["rich_text"])

            if title_text:
                tasks.append({
                    "name": title_text,
                    "done": done,
                    "reminder": reminder,
                    "priority": priority,
                    "recurrence": recurrence,
                    "tags": tags,
                    "notes": notes,
                    "page_id": page.get("id"),
                })

        if sort_by_reminder:
            tasks.sort(key=lambda t: t.get("reminder") or "9999-12-31T23:59:59Z")

        return tasks
    except Exception as e:
        print(f"Exception in list_tasks: {e}")
        return []


def list_incomplete_tasks(user_phone: str = None) -> list:
    return list_tasks(user_phone, filter_done=False)


def _find_task_page_id(task_name: str, user_phone: str = None) -> str | None:
    if not NOTION_DATABASE_ID or not NOTION_API_KEY:
        print("Error: Missing Notion DB ID or API Key")
        return None

    query_url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
    filter_conditions = [
        {
            "property": "Name",
            "title": {"equals": task_name}
        }
    ]
    if user_phone:
        filter_conditions.append({
            "property": "User",
            "rich_text": {"equals": user_phone}
        })

    filter_payload = {"filter": {"and": filter_conditions}}

    try:
        resp = requests.post(query_url, headers=headers, json=filter_payload)
        if resp.status_code != 200:
            print(f"_find_task_page_id query failed: {resp.text}")
            return None
        results = resp.json().get("results", [])
        if not results:
            print(f"_find_task_page_id: Task '{task_name}' not found")
            return None
        return results[0]["id"]
    except Exception as e:
        print(f"Exception in _find_task_page_id: {e}")
        return None


def complete_task(task_name: str, user_phone: str = None) -> bool:
    return _update_task_done_status(task_name, True, user_phone)


def mark_incomplete_task(task_name: str, user_phone: str = None) -> bool:
    return _update_task_done_status(task_name, False, user_phone)


def _update_task_done_status(task_name: str, done_status: bool, user_phone: str = None) -> bool:
    page_id = _find_task_page_id(task_name, user_phone)
    if not page_id:
        print(f"_update_task_done_status: Task '{task_name}' not found")
        return False

    update_url = f"https://api.notion.com/v1/pages/{page_id}"
    update_payload = {
        "properties": {
            "Done": {"checkbox": done_status}
        }
    }
    try:
        update_resp = requests.patch(update_url, headers=headers, json=update_payload)
        if update_resp.status_code in (200, 201):
            return True
        else:
            print(f"_update_task_done_status update failed: {update_resp.text}")
            return False
    except Exception as e:
        print(f"Exception in _update_task_done_status: {e}")
        return False


def edit_task(old_task_name: str, new_task_name: str = None, new_reminder: str = None,
              new_priority: str = None, new_recurrence: str = None, new_tags: list[str] = None, new_notes: str = None,
              user_phone: str = None) -> bool:
    if not NOTION_DATABASE_ID or not NOTION_API_KEY:
        print("Error: Missing Notion DB ID or API Key")
        return False

    page_id = _find_task_page_id(old_task_name, user_phone)
    if not page_id:
        print(f"edit_task: Task '{old_task_name}' not found")
        return False

    updated_properties = {}
    if new_task_name:
        updated_properties["Name"] = {
            "title": [{"text": {"content": new_task_name}}]
        }
    if new_reminder:
        updated_properties["Reminder"] = {
            "date": {"start": new_reminder, "time_zone": "Asia/Kolkata"}
        }
    if new_priority:
        updated_properties["Priority"] = {
            "select": {"name": new_priority.capitalize()}
        }
    if new_recurrence:
        updated_properties["Recurrence"] = {
            "select": {"name": new_recurrence.capitalize()}
        }
    if new_tags:
        updated_properties["Tags"] = {
            "multi_select": [{"name": tag.strip()} for tag in new_tags]
        }
    if new_notes:
        updated_properties["Notes"] = {
            "rich_text": [{"text": {"content": new_notes}}]
        }

    if not updated_properties:
        print("edit_task: No properties to update")
        return False

    update_url = f"https://api.notion.com/v1/pages/{page_id}"
    update_payload = {"properties": updated_properties}

    try:
        update_resp = requests.patch(update_url, headers=headers, json=update_payload)
        if update_resp.status_code in (200, 201):
            return True
        else:
            print(f"edit_task update failed: {update_resp.text}")
            return False
    except Exception as e:
        print(f"Exception in edit_task: {e}")
        return False


def delete_task(task_name: str, user_phone: str = None) -> bool:
    if not NOTION_DATABASE_ID or not NOTION_API_KEY:
        print("Error: Missing Notion DB ID or API Key")
        return False

    query_url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
    filters = [
        {"property": "Name", "title": {"equals": task_name}}
    ]
    if user_phone:
        filters.append({"property": "User", "rich_text": {"equals": user_phone}})

    filter_payload = {"filter": {"and": filters}}

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


def delete_all_completed_tasks(user_phone: str = None) -> bool:
    if not NOTION_DATABASE_ID or not NOTION_API_KEY:
        print("Error: Missing Notion DB ID or API Key")
        return False

    query_url = f"https://api.notion.com/v1/databases/{NOTION_DATABASE_ID}/query"
    filters = [
        {"property": "Done", "checkbox": {"equals": True}}
    ]
    if user_phone:
        filters.append({"property": "User", "rich_text": {"equals": user_phone}})

    filter_payload = {"filter": {"and": filters}}

    try:
        resp = requests.post(query_url, headers=headers, json=filter_payload)
        if resp.status_code != 200:
            print(f"delete_all_completed_tasks query failed: {resp.text}")
            return False

        results = resp.json().get("results", [])
        if not results:
            print("delete_all_completed_tasks: No completed tasks found")
            return True  # nothing to delete = success

        success = True
        for page in results:
            page_id = page["id"]
            update_url = f"https://api.notion.com/v1/pages/{page_id}"
            update_payload = {"archived": True}
            update_resp = requests.patch(update_url, headers=headers, json=update_payload)
            if update_resp.status_code not in (200, 201):
                print(f"Failed to archive task {page_id}: {update_resp.text}")
                success = False
        return success
    except Exception as e:
        print(f"Exception in delete_all_completed_tasks: {e}")
        return False
def search_tasks(keyword: str, user_phone: str = None) -> list:
    all_tasks = list_tasks(user_phone=user_phone)
    keyword_lower = keyword.lower()
    filtered = [
        t for t in all_tasks
        if keyword_lower in t['name'].lower() or keyword_lower in t.get('notes', '').lower()
    ]
    return filtered
def parse_add_command(text: str):
    """
    Parses task add command with optional flags:
    - /reminder <ISO datetime>
    - /priority <Low|Medium|High>
    - /repeat <none|daily|weekly|monthly>
    """
    # Default values
    task_text = None
    reminder = None
    priority = None
    recurrence = None

    # Regex patterns
    reminder_pattern = r"/reminder\s+([\dT:\-\+]+)"
    priority_pattern = r"/priority\s+(\w+)"
    recurrence_pattern = r"/repeat\s+(\w+)"

    # Extract and remove flags from text
    task_text = text.split('/')[0].strip()

    reminder_match = re.search(reminder_pattern, text, re.IGNORECASE)
    if reminder_match:
        reminder = reminder_match.group(1)

    priority_match = re.search(priority_pattern, text, re.IGNORECASE)
    if priority_match:
        priority = priority_match.group(1).capitalize()

    recurrence_match = re.search(recurrence_pattern, text, re.IGNORECASE)
    if recurrence_match:
        recurrence = recurrence_match.group(1).capitalize()

    # Ensure recurrence is valid or None
    if recurrence not in ["None", "Daily", "Weekly", "Monthly"]:
        recurrence = None

    return task_text, reminder, priority, recurrence
def search_tasks(keywords: str, user_phone: str = None) -> list:
    """
    Search tasks whose names contain all keywords (case-insensitive).
    Notion API does not support full-text search in DB queries, so filter client side.
    """
    all_tasks = list_tasks(user_phone=user_phone)
    keywords_lower = [kw.lower() for kw in keywords.split()]

    def matches(task):
        name_lower = task['name'].lower()
        return all(kw in name_lower for kw in keywords_lower)

    return [t for t in all_tasks if matches(t)]
