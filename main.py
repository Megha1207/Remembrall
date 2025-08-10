import os
import asyncio
from dotenv import load_dotenv
from fastmcp import FastMCP
from fastmcp.server.auth.providers.bearer import BearerAuthProvider, RSAKeyPair
from mcp import McpError, ErrorData, INVALID_PARAMS, INTERNAL_ERROR
from mcp.server.auth.provider import AccessToken
from pydantic import BaseModel, Field

import whatsapp  # Your existing command parsing module
import notion    # Your existing Notion API wrapper module
import reminders # Your background reminders starter
import uvicorn

load_dotenv()
TOKEN = os.getenv("BEARER_TOKEN")
MY_NUMBER = os.getenv("USER_PHONE_NUMBER")

assert TOKEN, "Please set BEARER_TOKEN in .env"
assert MY_NUMBER, "Please set USER_PHONE_NUMBER in .env"

# Auth provider for MCP server
class SimpleBearerAuthProvider(BearerAuthProvider):
    def __init__(self, token: str):
        k = RSAKeyPair.generate()
        super().__init__(public_key=k.public_key)
        self.token = token

    async def load_access_token(self, token: str) -> AccessToken | None:
        if token == self.token:
            return AccessToken(token=token, client_id="notion-whatsapp-bot", scopes=["*"], expires_at=None)
        return None

mcp = FastMCP("Notion WhatsApp MCP Server", auth=SimpleBearerAuthProvider(TOKEN))

# Validate tool required by MCP clients
@mcp.tool
async def validate() -> str:
    return MY_NUMBER

# Input model for commands
class CommandInput(BaseModel):
    command: str = Field(..., description="Command name like add, list, complete, etc.")
    args: str | None = Field(None, description="Command arguments string")

@mcp.tool
async def command_handler(input: CommandInput) -> str:
    cmd = input.command.lower()
    args = input.args or ""

    try:
        if cmd == "add":
            task_text, reminder, priority, recurrence, tags, notes = whatsapp.parse_add_args(args)
            success = notion.add_task(
                task_text,
                reminder_datetime=reminder,
                priority=priority,
                recurrence=recurrence,
                tags=tags,
                notes=notes,
                user_phone=MY_NUMBER,
            )
            if success:
                return f"✅ Task added!{' Reminder set for ' + reminder if reminder else ''}"
            else:
                return "❌ Failed to add task."

        elif cmd == "list":
            sort_flag = "sort" in args.lower()
            tasks = notion.list_tasks(user_phone=MY_NUMBER, sort_by_reminder=sort_flag)
            if not tasks:
                return "📭 No tasks found."
            return "\n".join(
                f"{'✅' if t['done'] else '⏳'} {t['name']}"
                + (f" 🔔 {t['reminder']}" if t.get("reminder") else "")
                + (f" 🔥 {t['priority']}" if t.get("priority") else "")
                + (f" 🔄 {t['recurrence']}" if t.get("recurrence") else "")
                for t in tasks
            )

        elif cmd == "list-incomplete":
            sort_flag = "sort" in args.lower()
            tasks = notion.list_tasks(user_phone=MY_NUMBER, filter_done=False, sort_by_reminder=sort_flag)
            if not tasks:
                return "🎉 No incomplete tasks found!"
            return "\n".join(
                f"• {t['name']}"
                + (f" 🔔 {t['reminder']}" if t.get("reminder") else "")
                + (f" 🔥 {t['priority']}" if t.get("priority") else "")
                + (f" 🔄 {t['recurrence']}" if t.get("recurrence") else "")
                for t in tasks
            )

        elif cmd == "complete":
            task_name = args.strip()
            if not task_name:
                raise McpError(ErrorData(code=INVALID_PARAMS, message="Please specify task to complete."))
            success = notion.complete_task(task_name, user_phone=MY_NUMBER)
            return "✅ Task marked as completed!" if success else "❌ Failed to mark task as completed."

        elif cmd == "mark-incomplete":
            task_name = args.strip()
            if not task_name:
                raise McpError(ErrorData(code=INVALID_PARAMS, message="Please specify task to mark incomplete."))
            success = notion.mark_incomplete_task(task_name, user_phone=MY_NUMBER)
            return "⏳ Task marked as incomplete!" if success else "❌ Failed to update task."

        elif cmd == "edit":
            if not args.strip():
                return (
                    "Specify task edit details. Example:\n"
                    "edit Old Task Name /newname New Task Name /reminder 2025-08-12T10:00:00 /priority High "
                    "/recurrence Daily /tags tag1,tag2 /notes Some notes here"
                )
            old_task_name, updates = whatsapp.parse_edit_args(args)
            success = notion.edit_task(
                old_task_name,
                new_task_name=updates["new_task_name"],
                new_reminder=updates["new_reminder"],
                new_priority=updates["new_priority"],
                new_recurrence=updates["new_recurrence"],
                new_tags=updates["new_tags"],
                new_notes=updates["new_notes"],
                user_phone=MY_NUMBER,
            )
            return "✏️ Task edited successfully!" if success else "❌ Failed to edit task."

        elif cmd == "delete":
            task_name = args.strip()
            if not task_name:
                raise McpError(ErrorData(code=INVALID_PARAMS, message="Please specify task to delete."))
            success = notion.delete_task(task_name, user_phone=MY_NUMBER)
            return "🗑️ Task deleted!" if success else "❌ Failed to delete task."

        elif cmd == "delete-all-completed":
            success = notion.delete_all_completed_tasks(user_phone=MY_NUMBER)
            return "🗑️ All completed tasks deleted!" if success else "❌ Failed to delete completed tasks."

        elif cmd == "search":
            keyword = args.strip()
            if not keyword:
                raise McpError(ErrorData(code=INVALID_PARAMS, message="Please provide keyword to search."))
            results = notion.search_tasks(keyword, user_phone=MY_NUMBER)
            if results:
                return "🔍 Search results:\n" + "\n".join(f"• {t['name']}" for t in results)
            else:
                return "🔍 No matching tasks found."

        elif cmd == "summary":
            tasks = notion.list_tasks(user_phone=MY_NUMBER)
            total = len(tasks)
            completed = sum(t["done"] for t in tasks)
            incomplete = total - completed
            priorities = {}
            for t in tasks:
                p = t.get("priority", "None")
                priorities[p] = priorities.get(p, 0) + 1

            return (
                f"📊 Task Summary:\n"
                f"📋 Total: {total}\n"
                f"✅ Completed: {completed}\n"
                f"⏳ Incomplete: {incomplete}\n"
                f"🔥 By Priority:\n"
                + "\n".join(f"  • {p}: {count}" for p, count in priorities.items())
            )

        elif cmd == "help" or not cmd:
            return (
                "🤖 *Notion MCP Bot Commands:*\n\n"
                "📝 add <task> [options] - Add a task\n"
                "   Options: /reminder <datetime> /priority <Low|Medium|High> /repeat <Daily|Weekly|Monthly> /tags <tag1,tag2> /notes <text>\n\n"
                "📋 list [sort] - List all tasks\n"
                "⏳ list-incomplete [sort] - List incomplete tasks\n"
                "✅ complete <task> - Mark task as completed\n"
                "⏳ mark-incomplete <task> - Mark task as incomplete\n"
                "✏️ edit <task> [options] - Edit a task\n"
                "🗑️ delete <task> - Delete a task\n"
                "🗑️ delete-all-completed - Delete all completed tasks\n"
                "🔍 search <keyword> - Search tasks\n"
                "📊 summary - Show task summary\n"
                "❓ help - Show this message\n\n"
                "💡 Example: add Buy milk /reminder 2025-08-10T15:00:00 /priority High /tags shopping"
            )

        else:
            return "❓ Unknown command. Send 'help' for commands."

    except McpError:
        raise  # propagate MCP errors as is

    except Exception as e:
        raise McpError(ErrorData(code=INTERNAL_ERROR, message=f"Internal error: {str(e)}"))

# Start reminders on MCP startup
@mcp.on_event("startup")
async def startup():
    reminders.start_reminder_thread()

if __name__ == "__main__":
    print("🚀 Starting Notion WhatsApp MCP server at http://0.0.0.0:8000")
    uvicorn.run(mcp.app, host="0.0.0.0", port=8000)
