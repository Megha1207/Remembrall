import os
import asyncio
from typing import Annotated
from dotenv import load_dotenv
from fastmcp import FastMCP
from fastmcp.server.auth.providers.bearer import BearerAuthProvider, RSAKeyPair
from mcp import McpError, ErrorData, INVALID_PARAMS, INTERNAL_ERROR
from mcp.server.auth.provider import AccessToken
from mcp.types import TextContent
from pydantic import BaseModel, Field

import whatsapp  # Your existing command parsing module
import notion    # Your existing Notion API wrapper module
import reminders # Your background reminders starter

# --- Load environment variables ---
load_dotenv()

# CHANGED: Use consistent environment variable names with other examples
TOKEN = os.environ.get("AUTH_TOKEN")  # Changed from BEARER_TOKEN
MY_NUMBER = os.environ.get("MY_NUMBER")  # Changed from USER_PHONE_NUMBER

assert TOKEN is not None, "Please set AUTH_TOKEN in your .env file"
assert MY_NUMBER is not None, "Please set MY_NUMBER in your .env file"

# --- Auth Provider (UPDATED to match other examples) ---
class SimpleBearerAuthProvider(BearerAuthProvider):
    def __init__(self, token: str):
        k = RSAKeyPair.generate()
        # FIXED: Added missing parameters for consistency
        super().__init__(public_key=k.public_key, jwks_uri=None, issuer=None, audience=None)
        self.token = token

    async def load_access_token(self, token: str) -> AccessToken | None:
        if token == self.token:
            return AccessToken(
                token=token, 
                client_id="notion-whatsapp-client",  # Updated client_id
                scopes=["*"], 
                expires_at=None
            )
        return None

# --- Rich Tool Description model (ADDED for consistency) ---
class RichToolDescription(BaseModel):
    description: str
    use_when: str
    side_effects: str | None = None

# --- MCP Server Setup ---
mcp = FastMCP(
    "Notion WhatsApp MCP Server", 
    auth=SimpleBearerAuthProvider(TOKEN)
)

# --- Tool: validate (required by Puch) ---
@mcp.tool
async def validate() -> str:
    return MY_NUMBER

# --- Tool Descriptions (ADDED for better integration) ---
COMMAND_HANDLER_DESCRIPTION = RichToolDescription(
    description="Execute Notion task management commands like add, list, complete, edit, delete, and more.",
    use_when="Use this when the user wants to manage their Notion tasks through natural language commands.",
    side_effects="Modifies Notion database by adding, updating, completing, or deleting tasks based on the command."
)

# UPDATED: Input model with better typing
class CommandInput(BaseModel):
    puch_user_id: str = Field(..., description="Puch User Unique Identifier")  # ADDED for user isolation
    command: str = Field(..., description="Command name like add, list, complete, etc.")
    args: str | None = Field(None, description="Command arguments string")

# UPDATED: Tool with proper annotations and user context
@mcp.tool(description=COMMAND_HANDLER_DESCRIPTION.model_dump_json())
async def command_handler(
    puch_user_id: Annotated[str, Field(description="Puch User Unique Identifier")],
    command: Annotated[str, Field(description="Command name like add, list, complete, etc.")],
    args: Annotated[str | None, Field(description="Command arguments string")] = None,
) -> list[TextContent]:  # CHANGED: Return list[TextContent] for consistency
    """
    Execute Notion task management commands with user context isolation.
    """
    cmd = command.lower()
    args = args or ""
    
    # Use puch_user_id for user isolation (you can map this to phone numbers if needed)
    user_phone = puch_user_id  # You might want to map this to actual phone numbers

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
                user_phone=user_phone,
            )
            result = f"✅ Task added!{' Reminder set for ' + reminder if reminder else ''}" if success else "❌ Failed to add task."
            return [TextContent(type="text", text=result)]

        elif cmd == "list":
            sort_flag = "sort" in args.lower()
            tasks = notion.list_tasks(user_phone=user_phone, sort_by_reminder=sort_flag)
            if not tasks:
                result = "📭 No tasks found."
            else:
                result = "\n".join(
                    f"{'✅' if t['done'] else '⏳'} {t['name']}"
                    + (f" 🔔 {t['reminder']}" if t.get("reminder") else "")
                    + (f" 🔥 {t['priority']}" if t.get("priority") else "")
                    + (f" 🔄 {t['recurrence']}" if t.get("recurrence") else "")
                    for t in tasks
                )
            return [TextContent(type="text", text=result)]

        elif cmd == "list-incomplete":
            sort_flag = "sort" in args.lower()
            tasks = notion.list_tasks(user_phone=user_phone, filter_done=False, sort_by_reminder=sort_flag)
            if not tasks:
                result = "🎉 No incomplete tasks found!"
            else:
                result = "\n".join(
                    f"• {t['name']}"
                    + (f" 🔔 {t['reminder']}" if t.get("reminder") else "")
                    + (f" 🔥 {t['priority']}" if t.get("priority") else "")
                    + (f" 🔄 {t['recurrence']}" if t.get("recurrence") else "")
                    for t in tasks
                )
            return [TextContent(type="text", text=result)]

        elif cmd == "complete":
            task_name = args.strip()
            if not task_name:
                raise McpError(ErrorData(code=INVALID_PARAMS, message="Please specify task to complete."))
            success = notion.complete_task(task_name, user_phone=user_phone)
            result = "✅ Task marked as completed!" if success else "❌ Failed to mark task as completed."
            return [TextContent(type="text", text=result)]

        elif cmd == "mark-incomplete":
            task_name = args.strip()
            if not task_name:
                raise McpError(ErrorData(code=INVALID_PARAMS, message="Please specify task to mark incomplete."))
            success = notion.mark_incomplete_task(task_name, user_phone=user_phone)
            result = "⏳ Task marked as incomplete!" if success else "❌ Failed to update task."
            return [TextContent(type="text", text=result)]

        elif cmd == "edit":
            if not args.strip():
                result = (
                    "Specify task edit details. Example:\n"
                    "edit Old Task Name /newname New Task Name /reminder 2025-08-12T10:00:00 /priority High "
                    "/recurrence Daily /tags tag1,tag2 /notes Some notes here"
                )
                return [TextContent(type="text", text=result)]
            
            old_task_name, updates = whatsapp.parse_edit_args(args)
            success = notion.edit_task(
                old_task_name,
                new_task_name=updates["new_task_name"],
                new_reminder=updates["new_reminder"],
                new_priority=updates["new_priority"],
                new_recurrence=updates["new_recurrence"],
                new_tags=updates["new_tags"],
                new_notes=updates["new_notes"],
                user_phone=user_phone,
            )
            result = "✏️ Task edited successfully!" if success else "❌ Failed to edit task."
            return [TextContent(type="text", text=result)]

        elif cmd == "delete":
            task_name = args.strip()
            if not task_name:
                raise McpError(ErrorData(code=INVALID_PARAMS, message="Please specify task to delete."))
            success = notion.delete_task(task_name, user_phone=user_phone)
            result = "🗑️ Task deleted!" if success else "❌ Failed to delete task."
            return [TextContent(type="text", text=result)]

        elif cmd == "delete-all-completed":
            success = notion.delete_all_completed_tasks(user_phone=user_phone)
            result = "🗑️ All completed tasks deleted!" if success else "❌ Failed to delete completed tasks."
            return [TextContent(type="text", text=result)]

        elif cmd == "search":
            keyword = args.strip()
            if not keyword:
                raise McpError(ErrorData(code=INVALID_PARAMS, message="Please provide keyword to search."))
            results = notion.search_tasks(keyword, user_phone=user_phone)
            if results:
                result = "🔍 Search results:\n" + "\n".join(f"• {t['name']}" for t in results)
            else:
                result = "🔍 No matching tasks found."
            return [TextContent(type="text", text=result)]

        elif cmd == "summary":
            tasks = notion.list_tasks(user_phone=user_phone)
            total = len(tasks)
            completed = sum(t["done"] for t in tasks)
            incomplete = total - completed
            priorities = {}
            for t in tasks:
                p = t.get("priority", "None")
                priorities[p] = priorities.get(p, 0) + 1

            result = (
                f"📊 Task Summary:\n"
                f"📋 Total: {total}\n"
                f"✅ Completed: {completed}\n"
                f"⏳ Incomplete: {incomplete}\n"
                f"🔥 By Priority:\n"
                + "\n".join(f"  • {p}: {count}" for p, count in priorities.items())
            )
            return [TextContent(type="text", text=result)]

        elif cmd == "help" or not cmd:
            result = (
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
            return [TextContent(type="text", text=result)]

        else:
            result = "❓ Unknown command. Send 'help' for commands."
            return [TextContent(type="text", text=result)]

    except McpError:
        raise  # propagate MCP errors as is

    except Exception as e:
        raise McpError(ErrorData(code=INTERNAL_ERROR, message=f"Internal error: {str(e)}"))

# Start reminders on MCP startup
@mcp.on_event("startup")
async def startup():
    reminders.start_reminder_thread()

# --- Run MCP Server (UPDATED to match other examples) ---
async def main():
    print("🚀 Starting Notion WhatsApp MCP server on http://0.0.0.0:8086")
    await mcp.run_async("streamable-http", host="0.0.0.0", port=8086)

if __name__ == "__main__":
    asyncio.run(main())