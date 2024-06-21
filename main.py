import threading
from ws_handler import WSHandler
from protocol import PROTOCOL

def handle_message(action, url, data):
    msg = PROTOCOL.parse_message(data)
    print(f"Received message: action={action}, url={url}, msg={msg.type}, {msg.seq}, {msg.name}, {msg.data}")

if __name__ == "__main__":
    ws_handler = WSHandler()
    ws_handler.add_message_callback(handle_message)
    ws_thread = threading.Thread(target=ws_handler.run)
    ws_thread.start()
    input("Press Enter to stop the server")
    ws_handler.stop()
    ws_thread.join()
