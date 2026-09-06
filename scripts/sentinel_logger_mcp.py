#!/usr/bin/env python3
"""
Antigravity & Claude MCP Server for Vireon Bot
Provides standard MCP tools to log events, bugs, betterment ideas,
and heartbeats directly to your Sentinel Monitoring Dashboard.
"""

import sys
import json
import urllib.request
import urllib.error
import os

DASHBOARD_URL = os.environ.get("SENTINEL_DASHBOARD_URL") or os.environ.get("DASHBOARD_URL", "http://localhost:3000")
API_SECRET = os.environ.get("SENTINEL_INGEST_TOKEN") or os.environ.get("INGEST_SECRET_TOKEN", "")

def send_jsonrpc_response(request_id, result=None, error=None):
    resp = {"jsonrpc": "2.0", "id": request_id}
    if error:
        resp["error"] = error
    else:
        resp["result"] = result
    sys.stdout.write(json.dumps(resp) + "\n")
    sys.stdout.flush()

def handle_log_event(args):
    payload = {
        "type": args.get("type", "idea"),
        "title": args.get("title", "Untitled Agent Event"),
        "detail": args.get("detail", ""),
        "status": args.get("status", "open"),
        "link": args.get("link"),
        "project": args.get("project", "Vireon-discord-bot"),
        "metadata": args.get("metadata", {})
    }
    
    url = f"{DASHBOARD_URL.rstrip('/')}/api/ingest"
    headers = {"Content-Type": "application/json"}
    if API_SECRET:
        headers["Authorization"] = f"Bearer {API_SECRET}"
        headers["x-api-key"] = API_SECRET
        
    req_data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=req_data, headers=headers, method="POST")
    
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            res_body = response.read().decode("utf-8")
            return {"content": [{"type": "text", "text": f"Successfully logged to Sentinel Dashboard: {res_body}"}]}
    except Exception as e:
        return {"content": [{"type": "text", "text": f"Logged with warning (Dashboard status): {str(e)}"}]}

def main():
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        try:
            msg = json.loads(line.strip())
            method = msg.get("method")
            req_id = msg.get("id")

            if method == "initialize":
                send_jsonrpc_response(req_id, {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "Vireon-sentinel-logger", "version": "1.0.0"}
                })
            elif method == "tools/list":
                send_jsonrpc_response(req_id, {
                    "tools": [
                        {
                            "name": "log_sentinel_event",
                            "description": "Logs an audit event, bug detection, auto-fix PR, web research finding, or heartbeat to the Sentinel Monitoring Dashboard.",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "type": {
                                        "type": "string",
                                        "enum": ["bug", "idea", "fix", "heartbeat", "search"],
                                        "description": "Category of the event"
                                    },
                                    "title": {
                                        "type": "string",
                                        "description": "Terse, factual one-line summary"
                                    },
                                    "detail": {
                                        "type": "string",
                                        "description": "Technical details, under 40 words"
                                    },
                                    "status": {
                                        "type": "string",
                                        "enum": ["open", "pr_opened", "needs_review", "resolved"],
                                        "description": "Status of the bug or idea"
                                    },
                                    "link": {
                                        "type": "string",
                                        "description": "Optional GitHub PR or issue URL"
                                    },
                                    "project": {
                                        "type": "string",
                                        "description": "Name of the attached repository/project (defaults to Vireon-discord-bot)"
                                    }
                                },
                                "required": ["type", "title"]
                            }
                        }
                    ]
                })
            elif method == "tools/call":
                params = msg.get("params", {})
                name = params.get("name")
                args = params.get("arguments", {})
                if name in ["log_sentinel_event", "log_event"]:
                    result = handle_log_event(args)
                    send_jsonrpc_response(req_id, result)
                else:
                    send_jsonrpc_response(req_id, error={"code": -32601, "message": f"Tool '{name}' not found"})
        except Exception as e:
            sys.stderr.write(f"Error handling MCP request: {e}\n")

if __name__ == "__main__":
    main()
