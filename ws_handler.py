import asyncio
import json
import base64
from websockets.server import serve

class WSHandler:
    def __init__(self):
        self.loop = asyncio.get_event_loop()
        self.stop_future = self.loop.create_future()
        self.message_callbacks = []

    def run(self):
        self.loop.run_until_complete(self.serve())

    def stop(self):
        self.loop.call_soon_threadsafe(self.stop_future.set_result, None)

    def add_message_callback(self, callback):
        self.message_callbacks.append(callback)

    def remove_message_callback(self, callback):
        self.message_callbacks.remove(callback)

    async def handle_message(self, websocket):
        async for message in websocket:
            for callback in self.message_callbacks:
                json_message = json.loads(message)
                action = json_message.get("action", None)
                url = json_message.get("url", None)
                data = json_message.get("data", "")
                data = base64.b64decode(data)
                callback(action, url, data)

    async def serve(self):
        async with serve(self.handle_message, "localhost", 8421):
            await self.stop_future
