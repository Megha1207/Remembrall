import os
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request, Header, HTTPException
from fastapi.responses import PlainTextResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import logging

from twilio.twiml.messaging_response import MessagingResponse
import re
import whatsapp  # Your command parsing module
import notion    # Your Notion API wrapper module
import reminders # Your background reminders starter

# Environment variables
BEARER_TOKEN = os.getenv("BEARER_TOKEN")  # Set this in your .env
USER_PHONE_NUMBER = os.getenv("USER_PHONE_NUMBER")  # Set your user phone number here

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Notion WhatsApp Bot",
    description="A WhatsApp bot for managing Notion tasks",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    logger.info(f"Method: {request.method}, URL: {request.url}, Headers: {dict(request.headers)}")
    response = await call_next(request)
    logger.info(f"Response Status: {response.status_code}")
    return response

@app.on_event("startup")
async def startup_event():
    logger.info("Starting up the application...")
    reminders.start_reminder_thread()
    logger.info("Reminder thread started successfully")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Shutting down the application...")

# Root endpoint
@app.get("/")
async def root():
    return {
        "message": "Notion WhatsApp Bot is running",
        "status": "healthy",
        "endpoints": {
            "health": "/health",
            "validate": "/validate (GET)",
            "mcp": "/mcp (GET for info, POST for commands)",
            "whatsapp_webhook": "/whatsapp/webhook (POST only)"
        }
    }

# Health check endpoint
@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "message": "Service is running properly"
    }

# MCP endpoints - Fixed to handle both GET and POST properly
@app.get("/mcp")
async def mcp_get():
    return {
        "message": "MCP endpoint for Puch AI integration",
        "methods": {
            "GET": "Returns this information",
            "POST": "Handles MCP commands (requires Authorization header)"
        },
        "usage": {
            "auth_header": "Authorization: Bearer <token>",
            "example_payload": {"method": "validate"}
        }
    }

@app.post("/mcp")
async def mcp_handler(request: Request, authorization: str = Header(None)):
    try:
        logger.info(f"Headers: {dict(request.headers)}")
        raw_body = await request.body()
        logger.info(f"Body: {raw_body.decode('utf-8')}")

        data = await request.json()
        method = data.get("method")
        request_id = data.get("id", None)

        logger.info(f"MCP request received - Method: {method}")

        # MCP 'initialize'
        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"serverInfo": {"name": "Notion WhatsApp MCP", "version": "1.0.0"}}
            }

        # MCP 'validate' - no token required, now safe
        if method == "validate":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "status": "ok",
                    "phone_number": USER_PHONE_NUMBER or None
                }
            }

        # Token required for everything else
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

        token = authorization.split(" ")[1]
        if token != BEARER_TOKEN:
            raise HTTPException(status_code=403, detail="Invalid token")

        # MCP 'tools/list'
        if method == "tools/list":
            tools = [
                {
                    "name": "summary",
                    "description": "Get a summary of tasks from Notion",
                    "parameters": {"type": "object", "properties": {}}
                },
                {
                    "name": "list_tasks",
                    "description": "List all tasks from Notion",
                    "parameters": {"type": "object", "properties": {}}
                }
            ]
            return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": tools}}

        # MCP 'tool/summary'
        if method == "tool/summary":
            tasks = notion.list_tasks(user_phone=USER_PHONE_NUMBER)
            total = len(tasks)
            completed = sum(t['done'] for t in tasks)
            incomplete = total - completed
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "total": total,
                    "completed": completed,
                    "incomplete": incomplete
                }
            }

        # MCP 'tool/list_tasks'
        if method == "tool/list_tasks":
            tasks = notion.list_tasks(user_phone=USER_PHONE_NUMBER)
            return {"jsonrpc": "2.0", "id": request_id, "result": {"tasks": tasks}}

        # Unknown MCP method
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": f"Unknown method '{method}'"}
        }

    except Exception as e:
        logger.error(f"Error in MCP handler: {str(e)}", exc_info=True)
        return {
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": -32603, "message": "Internal server error"}
        }





# Helper functions for parsing commands
def parse_add_args(args: str):
    """Parse arguments for the add command"""
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
    """Parse arguments for the edit command"""
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

# WhatsApp webhook - Fixed to handle errors better
@app.post("/whatsapp/webhook", response_class=PlainTextResponse)
async def whatsapp_webhook(request: Request):
    try:
        # Get form data from Twilio
        form = await request.form()
        incoming_msg = form.get('Body', '').strip()
        from_number = form.get('From', '').strip()
        
        logger.info(f"WhatsApp message received from {from_number}: {incoming_msg}")

        # Parse the command
        command, args = whatsapp.parse_command(incoming_msg)
        response_text = ""

        # Handle commands
        if command == "add":
            if not args:
                response_text = (
                    "Please specify a task to add. Example:\n"
                    "add Buy groceries /reminder 2025-08-10T15:00:00 /priority High /repeat Daily "
                    "/tags shopping,urgent /notes Buy low fat milk"
                )
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
                        response_text = f"✅ Task added with reminder set at {reminder}!"
                    else:
                        response_text = "✅ Task added to Notion!"
                else:
                    response_text = "❌ Failed to add task. Please try again."

        elif command == "list":
            sort_flag = "sort" in args.lower()
            tasks = notion.list_tasks(user_phone=from_number, sort_by_reminder=sort_flag)
            if tasks:
                response_text = "📋 Your tasks:\n" + "\n".join(
                    f"{'✅' if t['done'] else '⏳'} {t['name']}" +
                    (f" 🔔 {t['reminder']}" if t.get('reminder') else "") +
                    (f" 🔥 {t['priority']}" if t.get('priority') else "") +
                    (f" 🔄 {t['recurrence']}" if t.get('recurrence') else "")
                    for t in tasks
                )
            else:
                response_text = "📭 No tasks found."

        elif command == "list-incomplete":
            sort_flag = "sort" in args.lower()
            tasks = notion.list_tasks(user_phone=from_number, filter_done=False, sort_by_reminder=sort_flag)
            if tasks:
                response_text = "⏳ Incomplete tasks:\n" + "\n".join(
                    f"• {t['name']}" +
                    (f" 🔔 {t['reminder']}" if t.get('reminder') else "") +
                    (f" 🔥 {t['priority']}" if t.get('priority') else "") +
                    (f" 🔄 {t['recurrence']}" if t.get('recurrence') else "")
                    for t in tasks
                )
            else:
                response_text = "🎉 No incomplete tasks found!"

        elif command == "complete":
            task_name = args.strip()
            if not task_name:
                response_text = "Please specify a task to complete. Example:\ncomplete Buy groceries"
            else:
                success = notion.complete_task(task_name, user_phone=from_number)
                response_text = "✅ Task marked as completed!" if success else "❌ Failed to mark task as completed."

        elif command == "mark-incomplete":
            task_name = args.strip()
            if not task_name:
                response_text = "Please specify a task to mark incomplete. Example:\nmark-incomplete Buy groceries"
            else:
                success = notion.mark_incomplete_task(task_name, user_phone=from_number)
                response_text = "⏳ Task marked as incomplete!" if success else "❌ Failed to update task."

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
                response_text = "✏️ Task edited successfully!" if success else "❌ Failed to edit task."

        elif command == "delete":
            task_name = args.strip()
            if not task_name:
                response_text = "Please specify a task to delete. Example:\ndelete Buy groceries"
            else:
                success = notion.delete_task(task_name, user_phone=from_number)
                response_text = "🗑️ Task deleted!" if success else "❌ Failed to delete task."

        elif command == "delete-all-completed":
            success = notion.delete_all_completed_tasks(user_phone=from_number)
            response_text = "🗑️ All completed tasks deleted!" if success else "❌ Failed to delete completed tasks."

        elif command == "search":
            keyword = args.strip()
            if not keyword:
                response_text = "Please provide a keyword to search tasks. Example:\nsearch groceries"
            else:
                results = notion.search_tasks(keyword, user_phone=from_number)
                if results:
                    response_text = "🔍 Search results:\n" + "\n".join(
                        f"• {t['name']}" for t in results
                    )
                else:
                    response_text = "🔍 No matching tasks found."

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
                f"📊 Task Summary:\n"
                f"📋 Total: {total}\n"
                f"✅ Completed: {completed}\n"
                f"⏳ Incomplete: {incomplete}\n"
                f"🔥 By Priority:\n" + 
                "\n".join(f"  • {p}: {count}" for p, count in priorities.items())
            )

        elif command == "help" or not command:
            response_text = (
                "🤖 *Notion WhatsApp Bot Commands:*\n\n"
                "📝 *add* <task> [options] - Add a task\n"
                "   Options: /reminder <datetime> /priority <Low|Medium|High> /repeat <Daily|Weekly|Monthly> /tags <tag1,tag2> /notes <text>\n\n"
                "📋 *list* [sort] - List all tasks\n"
                "⏳ *list-incomplete* [sort] - List incomplete tasks\n"
                "✅ *complete* <task> - Mark task as completed\n"
                "⏳ *mark-incomplete* <task> - Mark task as incomplete\n"
                "✏️ *edit* <task> [options] - Edit a task\n"
                "🗑️ *delete* <task> - Delete a task\n"
                "🗑️ *delete-all-completed* - Delete all completed tasks\n"
                "🔍 *search* <keyword> - Search tasks\n"
                "📊 *summary* - Show task summary\n"
                "❓ *help* - Show this message\n\n"
                "💡 *Example:* add Buy milk /reminder 2025-08-10T15:00:00 /priority High /tags shopping"
            )

        else:
            response_text = "❓ Unknown command. Send 'help' for the list of commands."

        logger.info(f"Sending response: {response_text[:100]}...")

        # Create Twilio response
        twilio_resp = MessagingResponse()
        twilio_resp.message(response_text)
        return PlainTextResponse(content=str(twilio_resp), media_type="application/xml")

    except Exception as e:
        logger.error(f"Exception in WhatsApp webhook: {str(e)}", exc_info=True)
        twilio_resp = MessagingResponse()
        twilio_resp.message("😵 Sorry, something went wrong. Please try again or contact support.")
        return PlainTextResponse(content=str(twilio_resp), media_type="application/xml")

# WhatsApp webhook GET endpoint - Returns proper error
@app.get("/whatsapp/webhook")
async def whatsapp_webhook_get():
    return JSONResponse(
        status_code=405,
        content={
            "error": "Method Not Allowed",
            "message": "This endpoint only accepts POST requests from Twilio WhatsApp webhook",
            "allowed_methods": ["POST"]
        }
    )

# Catch-all for undefined routes
@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def catch_all(path: str, request: Request):
    return JSONResponse(
        status_code=404,
        content={
            "error": "Not Found",
            "message": f"Endpoint '{path}' not found",
            "method": request.method,
            "available_endpoints": [
                "/",
                "/health", 
                "/validate",
                "/mcp",
                "/whatsapp/webhook"
            ]
        }
    )

# Error handlers
@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    return JSONResponse(
        status_code=404,
        content={
            "error": "Not Found",
            "message": "The requested endpoint was not found",
            "path": str(request.url.path)
        }
    )

@app.exception_handler(405)
async def method_not_allowed_handler(request: Request, exc):
    return JSONResponse(
        status_code=405,
        content={
            "error": "Method Not Allowed",
            "message": f"Method {request.method} is not allowed for this endpoint",
            "path": str(request.url.path)
        }
    )

