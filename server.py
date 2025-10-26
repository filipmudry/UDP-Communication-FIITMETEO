import socket
import json
import time

class Server:
    def __init__(self):
        self.server_ip = "127.0.0.1"
        self.server_port = 5005
        self.sock = None
        self.tokens = {}
        self.listening = False

    def configure(self):
        print("\n--- SERVER CONFIGURATION ---")
        self.server_ip = input(f"Enter IP [{self.server_ip}]: ") or self.server_ip
        port_input = input(f"Enter PORT [{self.server_port}]: ")
        if port_input.strip():
            self.server_port = int(port_input)
        print(f"Configured IP={self.server_ip}, PORT={self.server_port}\n")

    def start_listening(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((self.server_ip, self.server_port))
        self.listening = True
        print(f"Server listening on {self.server_ip}:{self.server_port}\n")
        self.listen_loop()

    def listen_loop(self):
        while self.listening:
            data, addr = self.sock.recvfrom(4096)
            try:
                message = json.loads(data.decode())
            except json.JSONDecodeError:
                print("INFO: Corrupted message - invalid JSON")
                continue

            msg_type = message.get("type")

            if msg_type == "register":
                self.handle_register(message, addr)
            elif msg_type == "data":
                self.handle_data(message, addr)
            else:
                print(f"Unknown message type: {msg_type}")

    def handle_register(self, message, addr):
        sensor_id = message["sensor_id"]
        token = f"TOKEN_{int(time.time())}"
        self.tokens[sensor_id] = token
        print(f"INFO: {sensor_id} REGISTERED at {message['timestamp']}")
        response = {
            "type": "register_ack",
            "sensor_id": sensor_id,
            "token": token,
            "timestamp": int(time.time())
        }
        self.sock.sendto(json.dumps(response).encode(), addr)

    def handle_data(self, message, addr):
        # Extract fields
        sensor_id = message.get("sensor_id")
        sensor_type = message.get("sensor_type", "UNKNOWN")
        token = message.get("token")

        # Validate token
        if self.tokens.get(sensor_id) != token:
            print(f"INFO: {sensor_id} INVALID TOKEN at {message.get('timestamp')}")
            response = {
                "type": "invalid_token",
                "sensor_id": sensor_id,
                "timestamp": int(time.time())
            }
            self.sock.sendto(json.dumps(response).encode(), addr)
            return

        # Header with or without battery warning
        if message.get("low_battery"):
            print(f"{message.get('timestamp')} - WARNING: LOW BATTERY {sensor_id} ({sensor_type})")
        else:
            print(f"{message.get('timestamp')} - {sensor_id} ({sensor_type})")

        # Print payload
        data = message.get("data", {})
        for key, value in data.items():
            print(f"{key}: {value}; ", end="")
        print("\n")

        # Send ACK
        ack = {
            "type": "data_ack",
            "sensor_id": sensor_id,
            "timestamp": int(time.time())
        }
        self.sock.sendto(json.dumps(ack).encode(), addr)

    def menu(self):
        while True:
            print("\n--- SERVER MENU ---")
            print("1. Configure IP/PORT")
            print("2. Start listening")
            print("3. Exit")
            choice = input("Select option: ").strip()

            if choice == "1":
                self.configure()
            elif choice == "2":
                self.start_listening()
            elif choice == "3":
                print("Server shutting down.")
                self.listening = False
                break
            else:
                print("Invalid choice.")

if __name__ == "__main__":
    server = Server()
    server.menu()
