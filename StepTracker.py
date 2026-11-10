import threading
from langchain_core.callbacks import BaseCallbackHandler

class StepTracker(BaseCallbackHandler):

    def __init__(self, events, lock):
        self.events = events
        self.lock = lock
        self.current_step = 0

    def add_event(self, event):
        with self.lock:
            self.events.append(event)

    def on_tool_start(self, serialized, input_str, **kwargs):
        name = (serialized or {}).get("name") or kwargs.get("name") or "Unknown Tool"
        self.current_step += 1
        self.add_event({
            "type": "tool_call",
            "step": self.current_step,
            "tool": name,
            "content": str(input_str),
        })

    def on_tool_end(self, output, **kwargs):
        self.add_event({
            "type": "tool_result",
            "content": str(output)[:2000]
        })

    def on_tool_error(self, error, **kwargs):
        self.add_event({
            "type": "error",
            "content": str(error)
        })

    def on_agent_finish(self, finish, **kwargs):
        self.add_event({
            "type": "agent_finish",
            "content": str(finish.return_values)
        })