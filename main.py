import os
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from twilio.twiml.messaging_response import MessagingResponse
import re
import whatsapp  # Your command parsing module
import notion    # Your Notion API wrapper module
import reminders # Your background reminders starter

app = FastAPI()

@app.on_event("startup")
async def startup_event():
    reminders.start_reminder_thread()

def parse_add_args(args: str):
    # Split by / but allow spaces around /
    parts = [part.strip() for part in re.split(r'\s*/\s*', args)]
    task_text = parts[0]
    reminder = None
    priority = None
    recurrence = None
    tags = None
    notes = None

    for part in parts[1:]:
        lowered = part.lower()
        if lowered.startswith("reminder "):
            reminder = part[9:].strip()
        elif lowered.startswith("priority "):
            priority = part[9:].strip().capitalize()
        elif lowered.startswith("recurrence "):
            recurrence = part[11:].strip().capitalize()
        elif lowered.startswith("repeat "):  # alias for recurrence
            recurrence = part[7:].strip().capitalize()
        elif lowered.startswith("tags "):
            tags = [t.strip() for t in part[5:].split(",") if t.strip()]
        elif lowered.startswith("notes "):
            notes = part[6:].strip()

    return task_text, reminder, priority, recurrence, tags, notes

def parse_edit_args(args: str):
    parts = [part.strip() for part in re.split(r'\s*/\s*', args)]
    old_task_name = parts[0]
    updates = {
        "new_task_name": None,
        "new_reminder": None,
        "new_priority": None,
        "new_recurrence": None,
        "new_tags": None,
        "new_notes": None,
    }

    for part in parts[1:]:
        lowered = part.lower()
        if lowered.startswith("newname "):
            updates["new_task_name"] = part[8:].strip()
        elif lowered.startswith("reminder "):
            updates["new_reminder"] = part[9:].strip()
        elif lowered.startswith("priority "):
            updates["new_priority"] = part[9:].strip().capitalize()
        elif lowered.startswith("recurrence "):
            updates["new_recurrence"] = part[11:].strip().capitalize()
        elif lowered.startswith("repeat "):
            updates["new_recurrence"] = part[7:].strip().capitalize()
        elif lowered.startswith("tags "):
            tags_str = part[5:].strip()
            updates["new_tags"] = [t.strip() for t in tags_str.split(",") if t.strip()]
        elif lowered.startswith("notes "):
            updates["new_notes"] = part[6:].strip()

    return old_task_name, updates

@app.get("/")
async def root():
    return {"message": "Notion WhatsApp Bot is running."}

@app.api_route("/whatsapp/webhook", methods=["POST"], response_class=PlainTextResponse)
async def whatsapp_webhook(request: Request):
    try:
        form = await request.form()
        incoming_msg = form.get('Body', '').strip()
        from_number = form.get('From', '').strip()

        command, args = whatsapp.parse_command(incoming_msg)
        response_text = ""

        if command == "add":
            if not args:
                response_text = ("Please specify a task to add. Example:\n"
                                 "add Buy groceries /reminder 2025-08-10T15:00:00 /priority High /repeat Daily "
                                 "/tags shopping,urgent /notes Buy low fat milk")
            else:
                task_text, reminder, priority, recurrence, tags, notes = parse_add_args(args)
                success = notion.add_task(
                    task_text,
                    reminder_datetime=reminder,
                    priority=priority,
                    recurrence=recurrence,
                    tags=tags,
                    notes=notes,
                    user_phone=from_number
                )
                if success:
                    if reminder:
                        response_text = f"Task added with reminder set at {reminder}!"
                    else:
                        response_text = "Task added to Notion!"
                else:
                    response_text = "Failed to add task."

        elif command == "list":
            sort_flag = "sort" in args.lower()
            tasks = notion.list_tasks(user_phone=from_number, sort_by_reminder=sort_flag)
            if tasks:
                response_text = "Your tasks:\n" + "\n".join(
                    f"- [{'x' if t['done'] else ' '}] {t['name']}" +
                    (f" (reminder: {t['reminder']})" if t.get('reminder') else "") +
                    (f" [Priority: {t['priority']}]" if t.get('priority') else "") +
                    (f" [Repeat: {t['recurrence']}]" if t.get('recurrence') else "")
                    for t in tasks
                )
            else:
                response_text = "No tasks found."

        elif command == "list-incomplete":
            sort_flag = "sort" in args.lower()
            tasks = notion.list_tasks(user_phone=from_number, filter_done=False, sort_by_reminder=sort_flag)
            if tasks:
                response_text = "Incomplete tasks:\n" + "\n".join(
                    f"- {t['name']}" +
                    (f" (reminder: {t['reminder']})" if t.get('reminder') else "") +
                    (f" [Priority: {t['priority']}]" if t.get('priority') else "") +
                    (f" [Repeat: {t['recurrence']}]" if t.get('recurrence') else "")
                    for t in tasks
                )
            else:
                response_text = "No incomplete tasks found."

        elif command == "complete":
            task_name = args.strip()
            if not task_name:
                response_text = "Specify a task to complete. Example:\ncomplete Buy groceries"
            else:
                success = notion.complete_task(task_name, user_phone=from_number)
                response_text = "Task marked as completed!" if success else "Failed to mark task."

        elif command == "mark-incomplete":
            task_name = args.strip()
            if not task_name:
                response_text = "Specify a task to mark incomplete. Example:\nmark-incomplete Buy groceries"
            else:
                success = notion.mark_incomplete_task(task_name, user_phone=from_number)
                response_text = "Task marked as incomplete!" if success else "Failed to update task."

        elif command == "edit":
            if not args.strip():
                response_text = (
                    "Specify task edit details. Example:\n"
                    "edit Old Task Name /newname New Task Name /reminder 2025-08-12T10:00:00 /priority High "
                    "/recurrence Daily /tags tag1,tag2 /notes Some notes here"
                )
            else:
                old_task_name, updates = parse_edit_args(args)
                success = notion.edit_task(
                    old_task_name,
                    new_task_name=updates["new_task_name"],
                    new_reminder=updates["new_reminder"],
                    new_priority=updates["new_priority"],
                    new_recurrence=updates["new_recurrence"],
                    new_tags=updates["new_tags"],
                    new_notes=updates["new_notes"],
                    user_phone=from_number,
                )
                response_text = "Task edited successfully!" if success else "Failed to edit task."

        elif command == "delete":
            task_name = args.strip()
            if not task_name:
                response_text = "Specify a task to delete. Example:\ndelete Buy groceries"
            else:
                success = notion.delete_task(task_name, user_phone=from_number)
                response_text = "Task deleted!" if success else "Failed to delete task."

        elif command == "delete-all-completed":
            success = notion.delete_all_completed_tasks(user_phone=from_number)
            response_text = "All completed tasks deleted!" if success else "Failed to delete completed tasks."

        elif command == "search":
            keyword = args.strip()
            if not keyword:
                response_text = "Please provide a keyword to search tasks. Example:\nsearch groceries"
            else:
                results = notion.search_tasks(keyword, user_phone=from_number)
                if results:
                    response_text = "Search results:\n" + "\n".join(f"- {t['name']}" for t in results)
                else:
                    response_text = "No matching tasks found."

        elif command == "summary":
            tasks = notion.list_tasks(user_phone=from_number)
            total = len(tasks)
            completed = sum(t['done'] for t in tasks)
            incomplete = total - completed
            priorities = {}
            for t in tasks:
                p = t.get('priority', 'None')
                priorities[p] = priorities.get(p, 0) + 1
            response_text = (
                f"Task Summary:\n"
                f"Total: {total}\n"
                f"Completed: {completed}\n"
                f"Incomplete: {incomplete}\n"
                "By Priority:\n" + "\n".join(f"- {p}: {count}" for p, count in priorities.items())
            )

        elif command == "help" or not command:
            response_text = (
                "Commands:\n"
                "- add <task> [/reminder <ISO datetime>] [/priority <Low|Medium|High>] [/repeat|recurrence <None|Daily|Weekly|Monthly>] "
                "[/tags <tag1,tag2>] [/notes <text>]: Add a task\n"
                "- list [sort]: List all tasks, optionally sorted by reminder\n"
                "- list-incomplete [sort]: List only incomplete tasks, optionally sorted\n"
                "- complete <task>: Mark a task as completed\n"
                "- mark-incomplete <task>: Mark a task as incomplete\n"
                "- edit <old_task_name> /newname <new_name> /reminder <ISO datetime> /priority <Low|Medium|High> "
                "/recurrence <None|Daily|Weekly|Monthly> /tags <tag1,tag2> /notes <text>: Edit a task\n"
                "- delete <task>: Delete a task\n"
                "- delete-all-completed: Delete all completed tasks\n"
                "- search <keyword>: Search tasks by keyword\n"
                "- summary: Show summary of your tasks\n"
                "- help: Show this message"
            )

        else:
            response_text = "Unknown command. Send 'help' for the list of commands."

        twilio_resp = MessagingResponse()
        twilio_resp.message(response_text)
        return PlainTextResponse(content=str(twilio_resp), media_type="application/xml")

    except Exception as e:
        print(f"Exception in webhook: {e}")
        twilio_resp = MessagingResponse()
        twilio_resp.message("Sorry, something went wrong. Please try again.")
        return PlainTextResponse(content=str(twilio_resp), media_type="application/xml")

@app.get("/whatsapp/webhook")
async def whatsapp_webhook_get():
    return PlainTextResponse("Please use POST method for this endpoint.", status_code=405)
