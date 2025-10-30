import socket
import json
import time
import threading
import random

# --- CRC-32 (IEEE) pure Python, no external libs ---
def crc32_bytes(data: bytes) -> int:
    crc = 0xFFFFFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            mask = -(crc & 1)
            crc = (crc >> 1) ^ (0xEDB88320 & mask)
    return crc ^ 0xFFFFFFFF

def crc32_of_json_data(data_obj) -> int:
    # canonical JSON of the 'data' field only: compact, sorted keys
    payload = json.dumps(data_obj, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return crc32_bytes(payload) & 0xFFFFFFFF

class Tester:
    def __init__(self):
        self.server_ip = "127.0.0.1"
        self.server_port = 5005
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # legacy single fields (kept for old flows)
        self.sensor_id = "T001"
        self.sensor_type = "ThermoNode"
        self.token = None
        self.pending_last = {}
        self.resend_on_request = {}

        # fixed sensors
        self.sensors = [
            ("ThermoNode",   "T001"),
            ("WindSense",    "W001"),
            ("RainDetect",   "R001"),
            ("AirQualityBox","A001"),
        ]
        # token per sensor_id
        self.tokens = {}

        # last good message cache per sensor_id
        self.last_sent_ok = {}

        self.sending = False
        self._auto_thread = None

        # background receiver for server control messages
        self._rx_thread = None
        self._rx_running = False

        self.paused_sensors = set()
        self.activity_ping_count = {}

    def configure(self):
        print("\n--- TESTER CONFIGURATION ---")
        self.server_ip = input(f"Enter SERVER IP [{self.server_ip}]: ") or self.server_ip
        port_input = input(f"Enter SERVER PORT [{self.server_port}]: ")
        if port_input.strip():
            self.server_port = int(port_input)
        print(f"Configured SERVER_IP={self.server_ip}, SERVER_PORT={self.server_port}\n")

    def send_json(self, msg):
        self.sock.sendto(json.dumps(msg, separators=(",", ":")).encode("utf-8"),
                         (self.server_ip, self.server_port))

    # ========================= CRC & BUILDERS =========================

    def _crc32_of_data(self, data_obj):
        return crc32_of_json_data(data_obj)

    def _build_data_msg(self, s_type, s_id, token, low_batt=False, data=None):
        if data is None:
            data = self.generate_data_for(s_type)
        crc = self._crc32_of_data(data)
        msg = {
            "type": "data",
            "sensor_type": s_type,
            "sensor_id": s_id,
            "token": token,
            "timestamp": int(time.time()),
            "low_battery": low_batt,
            "data": data,
            "crc32": crc
        }
        return msg

    def register_all(self):
        was_running = self._rx_running
        if was_running:
            self.stop_rx_loop()
        if self.sending:
            print("INFO: auto sending is running; stopping it for registration.")
            self.stop_auto()

        successes = 0
        for s_type, s_id in self.sensors:
            # if already have token, skip re-register (optional but practical)
            if s_id in self.tokens and self.tokens[s_id]:
                print(f"INFO: {s_id} already registered, skipping.")
                successes += 1
                continue
            ok = self._register_once(s_type, s_id)
            if ok:
                successes += 1

        if "T001" in self.tokens:
            self.sensor_id = "T001"
            self.sensor_type = "ThermoNode"
            self.token = self.tokens["T001"]

        if successes == len(self.sensors):
            print(f"OK: all {successes}/{len(self.sensors)} sensors registered.")
        else:
            print(f"WARNING: only {successes}/{len(self.sensors)} sensors registered. Fix it before start_auto().")

        if was_running or successes == len(self.sensors):
            self.start_rx_loop()

    def _register_once(self, sensor_type, sensor_id):
        msg = {
            "type": "register",
            "sensor_type": sensor_type,
            "sensor_id": sensor_id,
            "timestamp": int(time.time())
        }
        self.send_json(msg)
        try:
            self.sock.settimeout(2)
            data, _ = self.sock.recvfrom(4096)
            resp = json.loads(data.decode("utf-8", errors="ignore"))

            rtype = resp.get("type")
            if rtype == "register_ack":
                token = resp.get("token")
                if token:
                    self.tokens[sensor_id] = token
                    print(f"INFO: {sensor_id} REGISTERED, token={token}")
                    return True
                print(f"WARNING: register for {sensor_id} has no token in response.")
                return False

            if rtype == "register_denied":
                reason = resp.get("reason")
                active_id = resp.get("active_sensor_id")
                print(f"WARNING: {sensor_id} register denied ({reason}), active for {sensor_type} is {active_id}")
                return False

            print(f"WARNING: unexpected response to register: {resp}")
            return False

        except socket.timeout:
            print(f"WARNING: register timeout for {sensor_id}")
            return False
        finally:
            self.sock.settimeout(None)

    def generate_data_for(self, sensor_type):
        if sensor_type == "ThermoNode":
            return {
                "temperature": round(random.uniform(-50.0, 60.0), 1),
                "humidity": round(random.uniform(0.0, 100.0), 1),
                "dew_point": round(random.uniform(-50.0, 60.0), 1),
                "pressure": round(random.uniform(800.00, 1100.00), 2)
            }
        elif sensor_type == "WindSense":
            return {
                "wind_speed": round(random.uniform(0.0, 50.0), 1),
                "wind_gust": round(random.uniform(0.0, 70.0), 1),
                "wind_direction": random.randint(0, 359),
                "turbulence": round(random.uniform(0.0, 1.0), 1)
            }
        elif sensor_type == "RainDetect":
            return {
                "rainfall": round(random.uniform(0.0, 500.0), 1),
                "soil_moisture": round(random.uniform(0.0, 100.0), 1),
                "flood_risk": random.randint(0, 4),
                "rain_duration": random.randint(0, 60)
            }
        elif sensor_type == "AirQualityBox":
            return {
                "co2": random.randint(300, 5000),
                "ozone": round(random.uniform(0.0, 500.0), 1),
                "air_quality_index": random.randint(0, 500)
            }
        return {"error": "unknown sensor type"}

    def generate_data(self):
        return self.generate_data_for(self.sensor_type)

    # ========================= RX LOOP FOR SERVER COMMANDS =========================

    def start_rx_loop(self):
        if self._rx_running:
            return
        self._rx_running = True
        self._rx_thread = threading.Thread(target=self._rx_loop, daemon=True)
        self._rx_thread.start()

    def stop_rx_loop(self):
        self._rx_running = False
        if self._rx_thread:
            self._rx_thread.join(timeout=1.0)

    def _rx_loop(self):
        # non-blocking loop to process server control messages
        self.sock.settimeout(0.2)
        while self._rx_running:
            try:
                data_raw, _ = self.sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break

            try:
                msg = json.loads(data_raw.decode("utf-8", errors="ignore"))
            except json.JSONDecodeError:
                continue

            mtype = msg.get("type")
            if mtype == "request_resend":
                sid = msg.get("sensor_id")
                # UAT3 exact resend: prefer message prepared at injection time
                resend = self.resend_on_request.pop(sid, None)
                if resend is None:
                    # fallback: last confirmed good or pending
                    resend = self.last_sent_ok.get(sid) or self.pending_last.get(sid)
                if resend:
                    self.send_json(resend)
                    # nech sa po ack povysi na last_ok
                    self.pending_last[sid] = resend


            elif mtype == "data_ack":
                sid = msg.get("sensor_id")
                # promote pending to last good only after ACK
                if sid in self.pending_last:
                    self.last_sent_ok[sid] = self.pending_last.pop(sid)


            elif mtype == "activity_check":
                sid = msg.get("sensor_id")
                if not sid:
                    continue

                stype = msg.get("sensor_type") or next((t for t, s in self.sensors if s == sid), None)
                token = self.tokens.get(sid)
                if not token or not stype:
                    continue

                # This prevents fake RECONNECTED spam while paused.
                if not self.sending:
                    continue

                # UAT4 flow: if sensor is "paused", reply only on 3rd probe, then unpause
                if sid in self.paused_sensors:
                    c = self.activity_ping_count.get(sid, 0) + 1
                    self.activity_ping_count[sid] = c
                    if c >= 3:
                        ack = {
                            "type": "activity_ack",
                            "sensor_type": stype,
                            "sensor_id": sid,
                            "token": token,
                            "timestamp": int(time.time()),
                            "low_battery": False
                        }
                        self.send_json(ack)
                        self.paused_sensors.discard(sid)
                        self.activity_ping_count.pop(sid, None)

        # restore blocking mode for interactive paths
        try:
            self.sock.settimeout(None)
        except OSError:
            pass

    # ========================= MANUAL SEND =========================

    def _get_ranges_for(self, sensor_type):
        return {
            "ThermoNode": {
                "temperature": (-50.0, 60.0),
                "humidity": (0.0, 100.0),
                "dew_point": (-50.0, 60.0),
                "pressure": (800.0, 1100.0)
            },
            "WindSense": {
                "wind_speed": (0.0, 50.0),
                "wind_gust": (0.0, 70.0),
                "wind_direction": (0, 359),
                "turbulence": (0.0, 1.0)
            },
            "RainDetect": {
                "rainfall": (0.0, 500.0),
                "soil_moisture": (0.0, 100.0),
                "flood_risk": (0, 4),
                "rain_duration": (0, 60)
            },
            "AirQualityBox": {
                "co2": (300, 5000),
                "ozone": (0.0, 500.0),
                "air_quality_index": (0, 500)
            }
        }.get(sensor_type, {})

    def _pick_sensor_interactive(self):
        print("\n--- SELECT SENSOR FOR MANUAL SEND ---")
        for i, (stype, sid) in enumerate(self.sensors, start=1):
            print(f"{i}. {sid} ({stype})")
        choice = input("Select: ").strip()
        try:
            idx = int(choice) - 1
            stype, sid = self.sensors[idx]
            return stype, sid
        except Exception:
            print("Invalid choice, using default T001.")
            return "ThermoNode", "T001"

    def send_manual_data(self):
        # require prior register_all
        s_type, s_id = self._pick_sensor_interactive()
        token = self.tokens.get(s_id)
        if not token:
            print("ERROR: selected sensor not registered. Run 'Register ALL sensors' first.")
            return

        print("\n--- MANUAL DATA ENTRY ---")
        low_battery = (input("Low battery? (y/n): ").strip().lower() == "y")

        ranges = self._get_ranges_for(s_type)
        if not ranges:
            print("ERROR: unknown sensor type ranges, aborting.")
            return

        data = {}
        for param, (min_val, max_val) in ranges.items():
            while True:
                print(f"{param} allowed range: {min_val} - {max_val}")
                value_str = input(f"Enter value for {param}: ").strip()
                try:
                    value = float(value_str)
                    if min_val <= value <= max_val:
                        value_rounded = round(value, 2)
                        if float(value_rounded).is_integer():
                            value_rounded = int(value_rounded)
                        data[param] = value_rounded
                        break
                    else:
                        print(f"Value out of range ({min_val}-{max_val}). Try again.")
                except ValueError:
                    print("Invalid input. Enter numeric value.")

        msg = self._build_data_msg(s_type, s_id, token, low_batt=low_battery, data=data)

        # send and mark as pending; last_ok sa nastavi az po ACK
        self.send_json(msg)
        self.pending_last[s_id] = msg

        # read a single server reply synchronously (likely data_ack)
        try:
            self.sock.settimeout(2)
            data_raw, _ = self.sock.recvfrom(4096)
            response = json.loads(data_raw.decode("utf-8", errors="ignore"))
            print("Server replied:", response)

            # immediate promotion if this is the ACK for our sensor
            if response.get("type") == "data_ack" and response.get("sensor_id") == s_id:
                if s_id in self.pending_last:
                    self.last_sent_ok[s_id] = self.pending_last.pop(s_id)

        except socket.timeout:
            print("No ACK received (timeout)")
        finally:
            self.sock.settimeout(None)

    # ========================= AUTO MODE =========================

    def start_auto(self):
        missing = [sid for _, sid in self.sensors if sid not in self.tokens]
        if missing:
            print(f"ERROR: not all sensors registered: {missing}. Run 'Register ALL sensors' first.")
            return
        if self.sending:
            print("Already running.")
            return
        self.sending = True
        self._auto_thread = threading.Thread(target=self.auto_loop, daemon=True)
        self._auto_thread.start()
        print("Automatic sending started (every 10s).")

    def stop_auto(self):
        self.sending = False
        if self._auto_thread:
            self._auto_thread.join(timeout=1.0)
        print("Automatic sending stopped.")
        # optional cleanup
        self.paused_sensors.clear()
        self.activity_ping_count.clear()

    def auto_loop(self):
        # periodic sender; respects paused_sensors (UAT4)
        period = 10.0
        while self.sending:
            t0 = time.monotonic()

            for s_type, s_id in self.sensors:
                # UAT4: skip paused sensor -> server zacne pingat po 15s
                if s_id in self.paused_sensors:
                    continue

                token = self.tokens.get(s_id)
                if not token:
                    # not registered, skip gracefully
                    continue

                msg = self._build_data_msg(
                    s_type, s_id, token,
                    low_batt=(random.random() < 0.05)
                )

                # send and mark as pending; last_ok sa nastavi az po data_ack v _rx_loop
                self.send_json(msg)
                self.pending_last[s_id] = msg

                # tiny spacing to avoid burst
                time.sleep(0.02)

            elapsed = time.monotonic() - t0
            time.sleep(max(0.0, period - elapsed))

    # ========================= UAT3: BAD FRAME =========================

    def inject_bad_frame(self):
        print("\n--- UAT3: INJECT ONE BAD FRAME ---")
        s_type, s_id = self._pick_sensor_interactive()
        token = self.tokens.get(s_id)
        if not token:
            print("ERROR: sensor not registered.")
            return

        # Build the EXACT message we intend to send (good crc, fixed timestamp and data)
        good = self._build_data_msg(s_type, s_id, token, low_batt=False)
        # Stash it for exact resend after server's request
        self.resend_on_request[s_id] = good

        # Create corrupted copy (same timestamp, same data, only crc is wrong)
        bad = dict(good)
        bad["crc32"] = (good["crc32"] ^ 0x00FFFF00) & 0xFFFFFFFF

        print(f"Sending corrupted frame for {s_id} with wrong crc32={bad['crc32']}")
        self.send_json(bad)
        # Neoznacujeme nic za last_ok; pockame na request_resend a potom posleme 'good'
        print("Server is REQUESTING DATA  with correct CRC.")

    # ========================= LEGACY BITS (kept) =========================

    def select_sensor_type(self):
        print("\n--- SELECT SENSOR TYPE (legacy manual flows) ---")
        print("1. ThermoNode")
        print("2. WindSense")
        print("3. RainDetect")
        print("4. AirQualityBox")
        choice = input("Select: ").strip()
        types = {"1": "ThermoNode","2": "WindSense","3": "RainDetect","4": "AirQualityBox"}
        self.sensor_type = types.get(choice, "ThermoNode")
        print(f"Sensor type set to {self.sensor_type}\n")

    # ========================= UAT4: ACTIVITY CHECK =========================
    def uat4_activity_check(self):
        print("\n--- UAT4: ACTIVITY CHECK ---")
        print("Select sensor to pause :")
        for i, (stype, sid) in enumerate(self.sensors, start=1):
            print(f"{i}. {sid} ({stype})")
        choice = input("Select: ").strip()
        try:
            idx = int(choice) - 1
            stype, sid = self.sensors[idx]
        except Exception:
            print("Invalid choice, using default T001 (ThermoNode).")
            stype, sid = "ThermoNode", "T001"

        # pause this sensor's auto sending
        self.paused_sensors.add(sid)
        # reset ping counter; resposta az na treti ping
        self.activity_ping_count[sid] = 0
        print(
            f"Sensor {sid} paused. Server should ping after 15s of silence, then every 5s. We will answer on 3rd ping.")

    # ========================= MENU =========================

    def menu(self):
        while True:
            print("\n--- TESTER MENU ---")
            print("1. Configure SERVER IP/PORT")
            print("2. Register ALL sensors")
            print("3. Start automatic sending")
            print("4. Stop automatic sending")
            print("5. Send manual data (pick sensor)")
            print("6. Inject one bad crc (UAT3)")
            print("7. Activity check (UAT4)")
            print("8. Exit")
            choice = input("Select option: ").strip()

            if choice == "1":
                self.configure()
            elif choice == "2":
                self.register_all()
            elif choice == "3":
                self.start_auto()
            elif choice == "4":
                self.stop_auto()
            elif choice == "5":
                self.send_manual_data()
            elif choice == "6":
                self.inject_bad_frame()
            elif choice == "7":
                self.uat4_activity_check()
            elif choice == "8":
                self.stop_auto()
                self.stop_rx_loop()
                print("Exiting tester.")
                break

        else:
                print("Invalid option.")


if __name__ == "__main__":
    tester = Tester()
    tester.menu()
