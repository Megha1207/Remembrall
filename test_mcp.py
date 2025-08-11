from fastapi import FastAPI
from fastmcp import FastMCP
from mcp.types import TextContent
from pydantic import Field
from typing import Annotated, List

app = FastAPI()
mcp = FastMCP("Test MCP Server")

@mcp.tool(description="Test tool")
async def test_tool(body: Annotated[str, Field()], from_number: Annotated[str, Field()]) -> List[TextContent]:
    return [TextContent(type="text", text=f"Received: {body} from {from_number}")]

mcp_app = mcp.http_app()
app.mount("/mcp", mcp_app)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8086)
