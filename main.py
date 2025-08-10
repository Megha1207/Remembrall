from dotenv import load_dotenv
load_dotenv()

from pydantic import BaseModel
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import PlainTextResponse
from twilio.twiml.messaging_response import MessagingResponse
import re
import whatsapp
import notion
import reminders

app = FastAPI()

class ValidateRequest(BaseModel):
    bearer_token: str

class ValidateResponse(BaseModel):
    phone_number: str

def validate_token(token: str) -> ValidateResponse:
    # Replace with your real token verification logic if needed
    if token != "abc123token":
        raise HTTPException(status_code=401, detail="Invalid token")
    # Return phone number in {country_code}{number} format as required
    return ValidateResponse(phone_number="919818517347")

@app.post("/validate", response_model=ValidateResponse)
def validate(req: ValidateRequest):
    return validate_token(req.bearer_token)

@app.api_route("/mcp", methods=["GET", "POST"], response_model=ValidateResponse)
async def mcp_validate(request: Request):
    if request.method == "GET":
        # Respond with dummy phone number for handshake/health check
        return ValidateResponse(phone_number="98")

    # POST: Validate bearer token from JSON body
    data = await request.json()
    token = data.get("bearer_token")
    return validate_token(token)

@app.on_event("startup")
async def startup_event():
    reminders.start_reminder_thread()

def parse_task_and_reminder(text: str):
    pattern = r"^(.*?)\s*/reminder\s*([\dT:\-\+]+)?$"
    match = re.match(pattern, text, re.IGNORECASE)
    if match:
        task_text = match.group(1).strip()
        reminder = match.group(2).strip() if match.group(2) else None
        return task_text, reminder
    else:
        return text.strip(), None

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
            task_text, reminder = parse_task_and_reminder(args)
            if not task_text:
                response_text = "Please specify a task to add. Example: add Buy groceries /reminder 2025-08-10T15:00:00"
            else:
                success = notion.add_task(task_text, reminder_datetime=reminder, user_phone=from_number)
                if reminder:
                    response_text = f"Task added with reminder set at {reminder}!" if success else "Failed to add task with reminder."
                else:
                    response_text = "Task added to Notion!" if success else "Failed to add task."

        elif command == "list":
            tasks = notion.list_tasks(user_phone=from_number)
            if tasks:
                response_text = "Your tasks:\n" + "\n".join(
                    f"- {'[x]' if t['done'] else '[ ]'} {t['name']}" + (f" (reminder: {t['reminder']})" if t.get('reminder') else "") for t in tasks
                )
            else:
                response_text = "No tasks found."

        elif command == "list-incomplete":
            tasks = notion.list_incomplete_tasks(user_phone=from_number)
            if tasks:
                response_text = "Incomplete tasks:\n" + "\n".join(
                    f"- {t['name']}" + (f" (reminder: {t['reminder']})" if t.get('reminder') else "") for t in tasks
                )
            else:
                response_text = "No incomplete tasks found."

        elif command == "complete":
            task_name = args.strip()
            if not task_name:
                response_text = "Specify a task to complete. Example: complete Buy groceries"
            else:
                success = notion.complete_task(task_name, user_phone=from_number)
                response_text = "Task marked as completed!" if success else "Failed to mark task."

        elif command == "delete":
            task_name = args.strip()
            if not task_name:
                response_text = "Specify a task to delete. Example: delete Buy groceries"
            else:
                success = notion.delete_task(task_name, user_phone=from_number)
                response_text = "Task deleted!" if success else "Failed to delete task."

        elif command == "help" or command == "":
            response_text = (
                "Commands:\n"
                "- add <task> [/reminder <ISO datetime>]: Add a task optionally with a reminder\n"
                "- list: List all tasks\n"
                "- list-incomplete: List only incomplete tasks\n"
                "- complete <task>: Mark a task as completed\n"
                "- delete <task>: Delete a task\n"
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