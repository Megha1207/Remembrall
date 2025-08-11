#!/usr/bin/env python3

import os
import re
import asyncio
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from typing import Annotated

from fastapi import FastAPI, Request, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from fastmcp import FastMCP
from mcp import ErrorData, McpError
from mcp.types import TextContent, INTERNAL_ERROR
from pydantic import Field
from twilio.twiml.messaging_response import MessagingResponse
load_dotenv()
import whatsapp   # your existing command parsing module
import notion     # your Notion API wrapper module
import reminders  # your reminders starter module

# ======================
# ENVIRONMENT VARIABLES
# ======================
load_dotenv()
AUTH_TOKEN = os.environ.get("AUTH_TOKEN", "m12egha12")
VALIDATE_PHONE_NUMBER = os.environ.get("VALIDATE_PHONE_NUMBER", "919602712127")

# ======================
# MCP SERVER
# ======================
mcp = FastMCP("Notion WhatsApp Bot MCP Server")

@mcp.tool(description="Validate bearer token and return user phone number.")
async def validate(token: Annotated[str, Field(description="Bearer token to validate")] = "") -> str:
    if token == AUTH_TOKEN:
        return VALIDATE_PHONE_NUMBER
    else:
        raise McpError(ErrorData(code=INTERNAL_ERROR, message="Invalid token"))

# ======================
# COMMAND ARG PARSERS
# ======================
def parse_add_args(args: str):
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
        elif lowered.startswith("repeat "):
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
            updates["new_tags"] = [t.strip() for t in part[5:].split(",") if t.strip()]
        elif lowered.startswith("notes "):
            updates["new_notes"] = part[6:].strip()
    return old_task_name, updates

# ======================
# COMMAND PROCESSOR
# ======================
def process_whatsapp_command(body: str, from_number: str) -> str:
    """Process WhatsApp commands and return plain text responses."""
    command_line = body.strip()
    if not command_line:
        return "Unknown command. Send 'help' for the list of commands."

    split_msg = command_line.split(" ", 1)
    command = split_msg[0].lower()
    args = split_msg[1] if len(split_msg) > 1 else ""

    if command == "add":
        if not args:
            return ("Please specify a task to add. Example:\n"
                    "add Buy groceries /reminder 2025-08-10T15:00:00 /priority High /repeat Daily "
                    "/tags shopping,urgent /notes Buy low fat milk")
        task_text, reminder, priority, recurrence, tags, notes = parse_add_args(args)
        success = notion.add_task(
            task_text, reminder_datetime=reminder, priority=priority,
            recurrence=recurrence, tags=tags, notes=notes, user_phone=from_number
        )
        return f"Task added{' with reminder at ' + reminder if reminder else ''}!" if success else "Failed to add task."

    elif command == "list":
        sort_flag = "sort" in args.lower()
        tasks = notion.list_tasks(user_phone=from_number, sort_by_reminder=sort_flag)
        if tasks:
            return "Your tasks:\n" + "\n".join(
                f"- [{'x' if t['done'] else ' '}] {t['name']}"
                + (f" (reminder: {t['reminder']})" if t.get('reminder') else "")
                + (f" [Priority: {t['priority']}]" if t.get('priority') else "")
                + (f" [Repeat: {t['recurrence']}]" if t.get('recurrence') else "")
                for t in tasks
            )
        return "No tasks found."

    elif command == "list-incomplete":
        sort_flag = "sort" in args.lower()
        tasks = notion.list_tasks(user_phone=from_number, filter_done=False, sort_by_reminder=sort_flag)
        if tasks:
            return "Incomplete tasks:\n" + "\n".join(
                f"- {t['name']}"
                + (f" (reminder: {t['reminder']})" if t.get('reminder') else "")
                + (f" [Priority: {t['priority']}]" if t.get('priority') else "")
                + (f" [Repeat: {t['recurrence']}]" if t.get('recurrence') else "")
                for t in tasks
            )
        return "No incomplete tasks found."

    elif command == "complete":
        task_name = args.strip()
        return "Task marked as completed!" if notion.complete_task(task_name, user_phone=from_number) else "Failed to mark task."

    elif command == "mark-incomplete":
        task_name = args.strip()
        return "Task marked as incomplete!" if notion.mark_incomplete_task(task_name, user_phone=from_number) else "Failed to update task."

    elif command == "edit":
        if not args.strip():
            return ("Specify task edit details. Example:\n"
                    "edit Old Task Name /newname New Task Name /reminder 2025-08-12T10:00:00 /priority High "
                    "/recurrence Daily /tags tag1,tag2 /notes Some notes here")
        old_task_name, updates = parse_edit_args(args)
        return "Task edited successfully!" if notion.edit_task(
            old_task_name,
            new_task_name=updates["new_task_name"],
            new_reminder=updates["new_reminder"],
            new_priority=updates["new_priority"],
            new_recurrence=updates["new_recurrence"],
            new_tags=updates["new_tags"],
            new_notes=updates["new_notes"],
            user_phone=from_number,
        ) else "Failed to edit task."

    elif command == "delete":
        return "Task deleted!" if notion.delete_task(args.strip(), user_phone=from_number) else "Failed to delete task."

    elif command == "delete-all-completed":
        return "All completed tasks deleted!" if notion.delete_all_completed_tasks(user_phone=from_number) else "Failed to delete completed tasks."

    elif command == "search":
        keyword = args.strip()
        if not keyword:
            return "Please provide a keyword to search tasks."
        results = notion.search_tasks(keyword, user_phone=from_number)
        return "Search results:\n" + "\n".join(f"- {t['name']}" for t in results) if results else "No matching tasks found."

    elif command == "summary":
        tasks = notion.list_tasks(user_phone=from_number)
        total = len(tasks)
        completed = sum(t['done'] for t in tasks)
        incomplete = total - completed
        priorities = {}
        for t in tasks:
            p = t.get('priority', 'None')
            priorities[p] = priorities.get(p, 0) + 1
        return (f"Task Summary:\nTotal: {total}\nCompleted: {completed}\nIncomplete: {incomplete}\n"
                "By Priority:\n" + "\n".join(f"- {p}: {count}" for p, count in priorities.items()))

    elif command == "help" or not command:
        return ("Commands:\n"
                "- add <task> [/reminder <ISO datetime>] [/priority <Low|Medium|High>] [/repeat|recurrence <None|Daily|Weekly|Monthly>] "
                "[/tags <tag1,tag2>] [/notes <text>]\n"
                "- list [sort]\n"
                "- list-incomplete [sort]\n"
                "- complete <task>\n"
                "- mark-incomplete <task>\n"
                "- edit <old_task_name> /newname <new_name> /reminder <ISO datetime> /priority <Low|Medium|High> "
                "/recurrence <None|Daily|Weekly|Monthly> /tags <tag1,tag2> /notes <text>\n"
                "- delete <task>\n"
                "- delete-all-completed\n"
                "- search <keyword>\n"
                "- summary\n"
                "- help")

    return "Unknown command. Send 'help' for the list of commands."

# MCP wrapper
@mcp.tool(description="Process WhatsApp command input and return response text.")
async def whatsapp_process_command(
    body: Annotated[str, Field(description="Raw WhatsApp message body text")],
    from_number: Annotated[str, Field(description="Sender phone number")]
) -> list[TextContent]:
    try:
        response_text = process_whatsapp_command(body, from_number)
        return [TextContent(type="text", text=response_text)]
    except Exception as e:
        raise McpError(ErrorData(code=INTERNAL_ERROR, message=f"Processing failed: {str(e)}"))

# ======================
# FASTAPI APP
# ======================
security = HTTPBearer()
async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if credentials.credentials != AUTH_TOKEN:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication token")
    return credentials.credentials

@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    print("🚀 Starting reminder thread...")
    reminders.start_reminder_thread()
    yield
    print("🛑 Shutting down...")

app = FastAPI(title="Notion WhatsApp Bot Server", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes
@app.get("/")
async def root():
    return {"message": "Notion WhatsApp Bot Server is running."}

@app.get("/mcp/health")
async def mcp_health():
    return {"status": "MCP server is running", "tools": ["validate", "whatsapp_process_command"]}

# Manual test routes
@app.post("/mcp/validate")
async def validate_token(request: Request, token: str = None):
    # Try query/form param first
    if token:
        provided_token = token
    else:
        # Fallback to JSON body
        body = await request.json()
        provided_token = body.get("token", "")

    if provided_token == AUTH_TOKEN:
        return {"phone_number": VALIDATE_PHONE_NUMBER}
    else:
        return {"error": "Invalid token"}

@app.post("/mcp/process", dependencies=[Depends(verify_token)])
async def manual_process(body: str, from_number: str):
    return {"response": process_whatsapp_command(body, from_number)}

# WhatsApp webhook
@app.post("/whatsapp/webhook", response_class=PlainTextResponse)
async def whatsapp_webhook(request: Request):
    twilio_resp = MessagingResponse()
    try:
        form = await request.form()
        incoming_msg = form.get("Body", "").strip()
        from_number = form.get("From", "")
        if from_number.startswith("whatsapp:"):
            from_number = from_number[len("whatsapp:"):]
        if not incoming_msg:
            twilio_resp.message("Please send a valid command. Send 'help' for assistance.")
            return PlainTextResponse(content=str(twilio_resp), media_type="application/xml")

        twilio_resp.message(process_whatsapp_command(incoming_msg, from_number))
        return PlainTextResponse(content=str(twilio_resp), media_type="application/xml")
    except Exception as e:
        print(f"❌ Webhook error: {e}")
        twilio_resp.message("Sorry, something went wrong. Please try again.")
        return PlainTextResponse(content=str(twilio_resp), media_type="application/xml")

@app.get("/whatsapp/webhook")
async def whatsapp_webhook_get():
    return PlainTextResponse("Please use POST method for this endpoint.", status_code=405)

# Mount MCP only once
app.mount("/mcp", mcp.http_app())

if __name__ == "__main__":
    import uvicorn
    print("🚀 Starting Notion WhatsApp Bot Server...")
    print(f"📱 Auth token: {AUTH_TOKEN}")
    print("🌐 Server running at: http://localhost:8086")
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8086)))

