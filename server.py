import random
import socket
import json
import time
import threading


# --- CRC-32 (IEEE) pure Python ---
def crc32_bytes(data: bytes) -> int:
    crc = 0xFFFFFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            mask = -(crc & 1)
            crc = (crc >> 1) ^ (0xEDB88320 & mask)
    return crc ^ 0xFFFFFFFF

def crc32_of_json_data(data_obj) -> int:
    payload = json.dumps(data_obj, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return crc32_bytes(payload) & 0xFFFFFFFF


class Server:
    def __init__(self):
        self.server_ip = "127.0.0.1"
        self.server_port = 5005
        self.sock = None

        # auth and addressing
        self.tokens = {}          # sensor_id -> token
        self.sensor_addr = {}     # sensor_id -> addr
        self.id_type = {}         # sensor_id -> sensor_type

        # P10: one active sensor per type
        self.active_by_type = {}  # sensor_type -> sensor_id

        # integrity + activity
        self.last_seen = {}       # sensor_id -> last data/register time
        self._probe = {}          # sensor_id -> {attempts, waiting, deadline, next}
        self._last_resend_req = {}  # debounce for request_resend

        # flags\
        self._rx_thread = None  # background listener thread
        self.listening = False
        self._mon_running = False
        self._mon_thread = None

    # --------------- config ---------------
    def configure(self):
        print("\n--- SERVER CONFIGURATION ---")
        self.server_ip = input(f"Enter IP [{self.server_ip}]: ") or self.server_ip
        p = input(f"Enter PORT [{self.server_port}]: ").strip()
        if p:
            self.server_port = int(p)
        print(f"Configured IP={self.server_ip}, PORT={self.server_port}\n")

    # --------------- start ---------------
    def start_listening(self):
        # already running? nic nerob
        if self.listening:
            print(f"Already listening on {self.server_ip}:{self.server_port}")
            return

        # bind socket
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((self.server_ip, self.server_port))
        self.sock.settimeout(0.5)

        # flip flags and start monitors
        self.listening = True
        self.start_activity_monitor()

        print(f"Server listening on {self.server_ip}:{self.server_port} (background).")

        # spusti prijimaciu slucku na pozadi, menu ostava dostupne
        self._rx_thread = threading.Thread(target=self.listen_loop, daemon=True)
        self._rx_thread.start()

    # --------------- monitor ---------------
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
        while self._mon_running and self.listening:
            now = time.time()
            for sensor_id in list(self.tokens.keys()):
                last = self.last_seen.get(sensor_id, now)
                if now - last < 15.0:
                    continue

                st = self._probe.get(sensor_id)
                if st is None:
                    st = {"attempts": 0, "waiting": False, "deadline": 0.0, "next": 0.0}
                    self._probe[sensor_id] = st

                # timeout of waiting window -> DISCONNECTED and schedule next
                if st["waiting"] and now >= st["deadline"]:
                    print(f"WARNING: {sensor_id} DISCONNECTED!")
                    st["waiting"] = False
                    st["next"] = now + 5.0  # next probe in 5s

                # send next probe if due, max 10 attempts
                if not st["waiting"] and st["attempts"] < 10 and now >= st["next"]:
                    addr = self.sensor_addr.get(sensor_id)
                    if addr:
                        ping = {
                            "type": "activity_check",
                            "sensor_type": self.id_type.get(sensor_id, "UNKNOWN"),
                            "sensor_id": sensor_id,
                            "token": self.tokens.get(sensor_id),
                            "timestamp": int(now),
                            "low_battery": False,
                            "attempt": st["attempts"] + 1,
                        }
                        self.safe_send(addr, ping)
                        st["attempts"] += 1
                        st["waiting"] = True
                        st["deadline"] = now + 1.0  # wait up to 1s for ack
            time.sleep(0.2)

    # --------------- main loop ---------------
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

            mtype = message.get("type")
            if mtype == "register":
                self.handle_register(message, addr)
            elif mtype == "data":
                self.handle_data(message, addr)
            elif mtype == "activity_ack":
                self.handle_activity_ack(message, addr)
            else:
                print(f"Unknown message type: {mtype}")

    # --------------- handlers ---------------
    def handle_register(self, message, addr):
        sensor_id = message.get("sensor_id")
        sensor_type = message.get("sensor_type", "UNKNOWN")
        ts = message.get("timestamp", int(time.time()))
        if not sensor_id:
            print("INFO: register missing sensor_id, ignored")
            return

        active = self.active_by_type.get(sensor_type)
        if active is not None and active != sensor_id:
            print(f"INFO: {sensor_id} REGISTER DENIED for {sensor_type}, active is {active}")
            resp = {"type": "register_denied", "reason": "type_busy",
                    "sensor_type": sensor_type, "active_sensor_id": active, "timestamp": int(time.time())}
            self.safe_send(addr, resp)
            return

        token = random.randint(100000, 999999)
        self.tokens[sensor_id] = token
        self.sensor_addr[sensor_id] = addr
        self.id_type[sensor_id] = sensor_type
        self.active_by_type[sensor_type] = sensor_id
        self.last_seen[sensor_id] = time.time()

        print(f"INFO: {sensor_id} REGISTERED at {ts}\n.")
        resp = {"type": "register_ack", "sensor_id": sensor_id, "token": token, "timestamp": int(time.time())}
        self.safe_send(addr, resp)

    def handle_activity_ack(self, message, addr):
        sensor_id = message.get("sensor_id")
        token = message.get("token")
        if not sensor_id or self.tokens.get(sensor_id) != token:
            return

        now = time.time()
        self.last_seen[sensor_id] = now
        self.sensor_addr[sensor_id] = addr

        # Print RECONNECTED only if we were actually probing (i.e., previously disconnected)
        st = self._probe.pop(sensor_id, None)
        if st and st.get("attempts", 0) > 0:
            print(f"INFO: {sensor_id} RECONNECTED!")

    def handle_data(self, message, addr):
        sensor_id = message.get("sensor_id")
        sensor_type = message.get("sensor_type", "UNKNOWN")
        token = message.get("token")
        ts = message.get("timestamp", int(time.time()))

        if not sensor_id or not token:
            print(f"INFO: DATA missing sensor_id or token at {ts}")
            self.safe_send(addr, {"type": "invalid_token", "sensor_id": sensor_id, "timestamp": int(time.time())})
            return
        if self.tokens.get(sensor_id) != token:
            print(f"INFO: {sensor_id} INVALID TOKEN at {ts}")
            self.safe_send(addr, {"type": "invalid_token", "sensor_id": sensor_id, "timestamp": int(time.time())})
            return

        self.sensor_addr[sensor_id] = addr
        self.id_type[sensor_id] = sensor_type
        self.last_seen[sensor_id] = time.time()

        # if a probe was running, data proves life -> announce once
        st = self._probe.pop(sensor_id, None)
        if st and st.get("attempts", 0) > 0:
            print(f"INFO: {sensor_id} RECONNECTED!")

        # integrity
        data_obj = message.get("data", {})
        recv_crc = message.get("crc32", None)
        if not isinstance(recv_crc, int) or recv_crc != crc32_of_json_data(data_obj):
            now = time.time()
            last_req = self._last_resend_req.get(sensor_id, 0)
            if now - last_req >= 1.0:
                print(f"INFO: {sensor_id} CORRUTPED DATA at {ts}. REQUESTING DATA")
                self.safe_send(addr, {"type": "request_resend", "sensor_id": sensor_id, "timestamp": int(time.time())})
                self._last_resend_req[sensor_id] = now
            return

        # data headers
        if message.get("low_battery"):
            print(f"{ts} - WARNING: LOW BATTERY {sensor_id}")
        else:
            print(f"{ts} - {sensor_id}")

        # payload (end with semicolon and blank line)
        line = "; ".join(f"{k}: {v}" for k, v in data_obj.items()) + ";"
        print(line + "\n")

        # ack
        self.safe_send(addr, {"type": "data_ack", "sensor_id": sensor_id, "timestamp": int(time.time())})

    # --------------- utils ---------------
    def safe_send(self, addr, obj):
        try:
            self.sock.sendto(json.dumps(obj, separators=(",", ":")).encode("utf-8"), addr)
        except OSError:
            pass

    # --------------- menu ---------------
    def menu(self):
        while True:
            print("\n--- SERVER MENU ---")
            print("1. Configure IP/PORT")
            print("2. Start listening")
            print("3. Exit")
            choice = input("Select option: \n").strip()
            if choice == "1":
                self.configure()
            elif choice == "2":
                self.start_listening()
            elif choice == "3":
                print("Server shutting down.")
                self.listening = False
                self.stop_activity_monitor()
                try:
                    if self.sock:
                        self.sock.close()
                except OSError:
                    pass
                break
            else:
                print("Invalid choice.")


if __name__ == "__main__":
    Server().menu()
