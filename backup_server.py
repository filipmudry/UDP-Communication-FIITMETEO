import socket
import json
import threading
import time

def crc32_bytes(data: bytes) -> int:
    crc = 0xFFFFFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            mask = -(crc & 1)
            crc = (crc >> 1) ^ (0xEDB88320 & mask)
    return crc ^ 0xFFFFFFFF

def crc32_of_json_data(data_obj) -> int:
    # canonical JSON of the 'data' field only: compact and sorted keys
    payload = json.dumps(data_obj, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return crc32_bytes(payload) & 0xFFFFFFFF

class Server:
    def __init__(self):
        self.server_ip = "127.0.0.1"
        self.server_port = 5005
        self.sock = None
        # tokens per sensor_id
        self.tokens = {}
        # remember last known remote addr per sensor
        self.sensor_addr = {}
        self.listening = False
        self._last_resend_req = {}
        self.active_by_type = {}

        self.last_seen = {}  # sensor_id -> unix time of last good DATA (or register)
        self.id_type = {}  # sensor_id -> sensor_type
        self._mon_running = False
        self._mon_thread = None
        self._probe = {}

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
        self.sock.settimeout(0.5)
        self.listening = True
        print(f"Server listening on {self.server_ip}:{self.server_port}\n")
        self.start_activity_monitor()
        self.listen_loop()

    def listen_loop(self):
        while self.listening:
            try:
                data, addr = self.sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break

            try:
                message = json.loads(data.decode("utf-8", errors="ignore"))
            except json.JSONDecodeError:
                print("INFO: Corrupted message - invalid JSON")
                continue

            msg_type = message.get("type")
            if msg_type == "register":
                self.handle_register(message, addr)
            elif msg_type == "data":
                self.handle_data(message, addr)
            elif msg_type == "activity_ack":
                self.handle_activity_ack(message, addr)
            else:
                print(f"Unknown message type: {msg_type}")

    def handle_register(self, message, addr):
        sensor_id = message.get("sensor_id")
        sensor_type = message.get("sensor_type", "UNKNOWN")
        ts = message.get("timestamp", int(time.time()))

        if not sensor_id:
            print("INFO: register missing sensor_id, ignored")
            return

        # P10: allow only one active sensor per type at a time
        active_id = self.active_by_type.get(sensor_type)

        if active_id is not None and active_id != sensor_id:
            # another sensor of the same type is already active -> deny
            print(f"INFO: {sensor_id} REGISTER DENIED for {sensor_type}, active is {active_id}")
            deny = {
                "type": "register_denied",
                "reason": "type_busy",
                "sensor_type": sensor_type,
                "active_sensor_id": active_id,
                "timestamp": int(time.time()),
            }
            self.safe_send(addr, deny)
            return

        # allowed: either first of its type, or re-register of the same id
        token = f"TOKEN_{int(time.time())}"
        self.tokens[sensor_id] = token
        self.sensor_addr[sensor_id] = addr
        self.active_by_type[sensor_type] = sensor_id
        self.last_seen[sensor_id] = time.time()
        self.id_type[sensor_id] = sensor_type

        print(f"INFO: {sensor_id} REGISTERED at {ts}")
        response = {
            "type": "register_ack",
            "sensor_id": sensor_id,
            "token": token,
            "timestamp": int(time.time()),
        }
        self.safe_send(addr, response)

    def handle_data(self, message, addr):
        sensor_id = message.get("sensor_id")
        sensor_type = message.get("sensor_type", "UNKNOWN")
        token = message.get("token")
        ts = message.get("timestamp", int(time.time()))
        self.last_seen[sensor_id] = time.time()
        self.id_type[sensor_id] = sensor_type
        # if we were probing this sensor, getting data also proves life; clear probe and announce RECONNECTED once
        st = self._probe.pop(sensor_id, None)
        if st is not None and st.get("attempts", 0) > 0:
            print(f"INFO: {sensor_id} RECONNECTED!")


        if not sensor_id or not token:
            print(f"INFO: DATA missing sensor_id or token at {ts}")
            self.safe_send(addr, {"type": "invalid_token", "sensor_id": sensor_id, "timestamp": int(time.time())})
            return

        if self.tokens.get(sensor_id) != token:
            print(f"INFO: {sensor_id} INVALID TOKEN at {ts}")
            self.safe_send(addr, {"type": "invalid_token", "sensor_id": sensor_id, "timestamp": int(time.time())})
            return

        self.sensor_addr[sensor_id] = addr

        data = message.get("data", {})
        recv_crc = message.get("crc32",None)
        calc_crc = crc32_of_json_data(data)

        if recv_crc != calc_crc:
            # exact wording required by spec (including the typo)
            print(f"INFO: {sensor_id} CORRUTPED DATA at {ts}. REQUESTING DATA")
            self.safe_send(addr, {
                "type": "request_resend",
                "sensor_id": sensor_id,
                "timestamp": int(time.time())
            })
            return

        if message.get("low_battery"):
            print(f"{ts} - WARNING: LOW BATTERY {sensor_id} ")
        else:
            print(f"{ts} - {sensor_id}")

        line = "; ".join(f"{k}: {v}" for k, v in data.items()) + ";"
        print(line + "\n")

        self.safe_send(addr, {"type": "data_ack", "sensor_id": sensor_id, "timestamp": int(time.time())})

    def safe_send(self, addr, obj):
        try:
            self.sock.sendto(json.dumps(obj, separators=(",", ":")).encode("utf-8"), addr)
        except OSError:
            pass

    def start_activity_monitor(self):
        if self._mon_running:
            return
        self._mon_running = True
        self._mon_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._mon_thread.start()

    def stop_activity_monitor(self):
        self._mon_running = False
        if self._mon_thread:
            self._mon_thread.join(timeout=1.0)

    def _monitor_loop(self):
        # checks inactivity and runs ping cycle per UAT4
        while self._mon_running and self.listening:
            now = time.time()

            # iterate over known sensors (those that registered at least once)
            for sensor_id, token in list(self.tokens.items()):
                last = self.last_seen.get(sensor_id, now)
                # if inactive for 15s, start/continue probe
                if now - last >= 15.0:
                    st = self._probe.get(sensor_id)
                    if st is None:
                        st = {"attempts": 0, "waiting": False, "deadline": 0.0, "next": 0.0}
                        self._probe[sensor_id] = st

                    # if currently waiting for response, check deadline
                    if st["waiting"] and now >= st["deadline"]:
                        # timeout -> announce DISCONNECTED and schedule next try
                        print(f"WARNING: {sensor_id} DISCONNECTED!")
                        st["waiting"] = False
                        st["next"] = now + 5.0  # next probe after 5s
                        # attempts already counted when ping was sent

                    # if not waiting and it is time to send another probe (cap at 10 tries)
                    if not st["waiting"] and st["attempts"] < 10 and now >= st["next"]:
                        # find sensor_type and addr
                        sensor_type = self.id_type.get(sensor_id, "UNKNOWN")
                        addr = self.sensor_addr.get(sensor_id)
                        if addr:
                            ping = {
                                "type": "activity_check",
                                "sensor_type": sensor_type,
                                "sensor_id": sensor_id,
                                "token": token,
                                "timestamp": int(now),
                                "low_battery": False,
                                "attempt": st["attempts"] + 1
                            }
                            self.safe_send(addr, ping)
                            st["attempts"] += 1
                            st["waiting"] = True
                            st["deadline"] = now + 1.0  # wait up to 1s for ack
            time.sleep(0.2)

    def handle_activity_ack(self, message, addr):
        sensor_id = message.get("sensor_id")
        token = message.get("token")
        if not sensor_id or self.tokens.get(sensor_id) != token:
            return

        # aktualizuj stav
        self.last_seen[sensor_id] = time.time()
        self.sensor_addr[sensor_id] = addr

        # RECONNECTED iba ak bola rozbehnuta sonda (teda existoval _probe z UAT4)
        st = self._probe.pop(sensor_id, None)
        if st and st.get("attempts", 0) > 0:
            print(f"INFO: {sensor_id} RECONNECTED!")

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
                try:
                    if self.sock:
                        self.sock.close()
                except OSError:
                    pass
                break
            else:
                print("Invalid choice.")


if __name__ == "__main__":
    server = Server()
    server.menu()
