"""A minimal streamable-HTTP MCP caller, for scripted harness checks and setup lookups.

Conversations always go through Claude Code (client.py); this is only for the harness
itself, e.g. step 3's link checks.
"""

import json

import requests


class MCP:
    def __init__(self, url, token):
        self.url, self.token, self.sid, self._id = url, token, None, 0
        self._post({"jsonrpc": "2.0", "id": self._next(), "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "sewasetu-eval-harness", "version": "1"}}})
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def _next(self):
        self._id += 1
        return self._id

    def _post(self, body):
        h = {"Authorization": "Bearer " + self.token, "Content-Type": "application/json",
             "Accept": "application/json, text/event-stream"}
        if self.sid:
            h["mcp-session-id"] = self.sid
        r = requests.post(self.url, json=body, headers=h, timeout=60)
        r.raise_for_status()
        r.encoding = "utf-8"            # text/event-stream carries no charset; requests guesses latin-1
        self.sid = r.headers.get("mcp-session-id", self.sid)
        if "id" not in body:
            return None
        if r.headers.get("content-type", "").startswith("text/event-stream"):
            for line in r.text.splitlines():
                if line.startswith("data:"):
                    msg = json.loads(line[5:])
                    if msg.get("id") == body["id"]:
                        return msg
            raise RuntimeError("no response in event stream")
        return r.json()

    def tools(self):
        return [t["name"] for t in self._post({"jsonrpc": "2.0", "id": self._next(),
                                               "method": "tools/list"})["result"]["tools"]]

    def call(self, name, **args):
        """The tool's structured result (dict), or its text if it has none."""
        msg = self._post({"jsonrpc": "2.0", "id": self._next(), "method": "tools/call",
                          "params": {"name": name, "arguments": args}})
        if "error" in msg:
            raise RuntimeError(msg["error"])
        res = msg["result"]
        if res.get("structuredContent") is not None:
            return res["structuredContent"]
        text = "".join(c.get("text", "") for c in res.get("content", []))
        try:
            return json.loads(text)
        except ValueError:
            return text
