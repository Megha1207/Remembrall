import os
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request, Header, HTTPException
from fastapi.responses import PlainTextResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import logging
import json

# Environment variables
BEARER_TOKEN = os.getenv("BEARER_TOKEN", "m12egha12")  # Default fallback
USER_PHONE_NUMBER = os.getenv("USER_PHONE_NUMBER", "+919602712127")  # Default fallback

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Puch AI MCP Server",
    description="MCP Server for Puch AI Integration",
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
    logger.info(f"=== REQUEST ===")
    logger.info(f"Method: {request.method}")
    logger.info(f"URL: {request.url}")
    logger.info(f"Headers: {dict(request.headers)}")
    
    response = await call_next(request)
    
    logger.info(f"=== RESPONSE ===")
    logger.info(f"Status: {response.status_code}")
    logger.info(f"Headers: {dict(response.headers)}")
    
    return response

@app.get("/")
async def root():
    return {
        "name": "Notion WhatsApp Bot MCP Server",
        "version": "1.0.0",
        "status": "ready",
        "mcp_endpoint": "/mcp",
        "phone_configured": bool(USER_PHONE_NUMBER),
        "auth_configured": bool(BEARER_TOKEN)
    }

@app.get("/health")
async def health():
    return {"status": "healthy"}

# OPTIONS handler for CORS preflight
@app.options("/mcp")
async def mcp_options():
    response = JSONResponse({"message": "CORS preflight"})
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "POST, GET, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "*"
    response.headers["Access-Control-Max-Age"] = "3600"
    return response

@app.get("/mcp")
async def mcp_info():
    return {
        "name": "Notion WhatsApp Bot MCP Server",
        "description": "MCP server for Puch AI integration",
        "version": "1.0.0",
        "protocol_version": "2024-11-05",
        "capabilities": {
            "tools": True,
            "resources": False,
            "prompts": False
        },
        "usage": "POST to this endpoint with proper MCP JSON-RPC format"
    }

@app.post("/mcp")
async def mcp_handler(request: Request):
    try:
        # Log the raw request
        body = await request.body()
        logger.info(f"Raw body: {body}")
        
        if len(body) == 0:
            logger.error("Empty request body")
            return create_error_response(-32600, "Empty request body")
        
        # Parse JSON
        try:
            data = json.loads(body)
            logger.info(f"Parsed JSON: {data}")
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error: {e}")
            return create_error_response(-32700, f"Parse error: {str(e)}")
        
        # Handle different request types
        method = data.get("method")
        params = data.get("params", {})
        request_id = data.get("id")
        
        logger.info(f"Method: {method}, Params: {params}, ID: {request_id}")
        
        # Handle initialize request
        if method == "initialize":
            logger.info("Handling initialize request")
            return create_success_response(request_id, {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {"listChanged": True},
                    "resources": {"listChanged": False, "subscribe": False},
                    "prompts": {"listChanged": False}
                },
                "serverInfo": {
                    "name": "notion-whatsapp-bot",
                    "version": "1.0.0"
                }
            })
        
        # Handle notifications/initialized
        if method == "notifications/initialized":
            logger.info("Handling initialized notification")
            # No response needed for notifications
            return JSONResponse({})
        
        # Handle tools/list request
        if method == "tools/list":
            logger.info("Handling tools/list request")
            return create_success_response(request_id, {
                "tools": [
                    {
                        "name": "validate",
                        "description": "Validate server and return owner phone number",
                        "inputSchema": {
                            "type": "object",
                            "properties": {},
                            "required": []
                        }
                    },
                    {
                        "name": "add_task", 
                        "description": "Add a new task to Notion",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "task": {"type": "string", "description": "Task description"},
                                "priority": {"type": "string", "description": "Task priority (Low/Medium/High)"},
                                "reminder": {"type": "string", "description": "Reminder datetime"}
                            },
                            "required": ["task"]
                        }
                    }
                ]
            })
        
        # Handle tools/call request
        if method == "tools/call":
            tool_name = params.get("name")
            tool_args = params.get("arguments", {})
            
            logger.info(f"Tool call: {tool_name} with args: {tool_args}")
            
            if tool_name == "validate":
                # Check authorization for validate tool
                auth_header = request.headers.get("authorization")
                if auth_header:
                    if not auth_header.startswith("Bearer "):
                        return create_error_response(-32002, "Invalid authorization format")
                    
                    token = auth_header.split(" ")[1]
                    if token != BEARER_TOKEN:
                        return create_error_response(-32002, "Invalid token")
                
                # Return phone number without + prefix as per Puch AI requirements
                phone = str(USER_PHONE_NUMBER).strip()
                if phone.startswith('+'):
                    phone = phone[1:]
                
                logger.info(f"Returning phone number: {phone}")
                
                return create_success_response(request_id, {
                    "content": [
                        {
                            "type": "text",
                            "text": phone
                        }
                    ]
                })
            
            elif tool_name == "add_task":
                # Check authorization for add_task
                auth_header = request.headers.get("authorization") 
                if not auth_header or not auth_header.startswith("Bearer "):
                    return create_error_response(-32002, "Missing or invalid authorization")
                
                token = auth_header.split(" ")[1]
                if token != BEARER_TOKEN:
                    return create_error_response(-32002, "Invalid token")
                
                task = tool_args.get("task", "")
                if not task:
                    return create_error_response(-32602, "Task description is required")
                
                # Here you would integrate with your Notion API
                # For now, just return success
                return create_success_response(request_id, {
                    "content": [
                        {
                            "type": "text", 
                            "text": f"Task '{task}' added successfully to Notion!"
                        }
                    ]
                })
            
            else:
                return create_error_response(-32601, f"Unknown tool: {tool_name}")
        
        # Handle validate method (legacy format for testing)
        if method == "validate":
            logger.info("Handling legacy validate method")
            phone = str(USER_PHONE_NUMBER).strip()
            if phone.startswith('+'):
                phone = phone[1:]
            
            response = PlainTextResponse(phone)
            response.headers["Access-Control-Allow-Origin"] = "*"
            return response
        
        # Unknown method
        logger.warning(f"Unknown method: {method}")
        return create_error_response(-32601, f"Method not found: {method}")
        
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}", exc_info=True)
        return create_error_response(-32603, f"Internal error: {str(e)}")

def create_success_response(request_id, result):
    """Create a JSON-RPC success response"""
    response_data = {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": result
    }
    response = JSONResponse(response_data)
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Content-Type"] = "application/json"
    return response

def create_error_response(code, message, request_id=None):
    """Create a JSON-RPC error response"""
    response_data = {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {
            "code": code,
            "message": message
        }
    }
    response = JSONResponse(response_data, status_code=400)
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Content-Type"] = "application/json"
    return response

# Catch-all for debugging
@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def catch_all(path: str, request: Request):
    logger.info(f"Catch-all hit: {request.method} {path}")
    return JSONResponse(
        {
            "error": "Not Found",
            "path": path,
            "method": request.method,
            "available_endpoints": ["/", "/health", "/mcp"]
        },
        status_code=404
    )

