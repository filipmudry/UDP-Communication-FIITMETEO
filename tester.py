import socket
import json
import time
import threading
import random

class Tester:
    def __init__(self):
        self.server_ip = "127.0.0.1"
        self.server_port = 5005
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sensor_id = "T001"
        self.sensor_type = "ThermoNode"
        self.token = None
        self.sending = False

    def configure(self):
        print("\n--- TESTER CONFIGURATION ---")

        self.server_ip = input(f"Enter SERVER IP [{self.server_ip}]: ") or self.server_ip
        port_input = input(f"Enter SERVER PORT [{self.server_port}]: ")

        if port_input.strip():
            self.server_port = int(port_input)

        print(f"Configured SERVER_IP={self.server_ip}, SERVER_PORT={self.server_port}\n")

    def select_sensor_type(self):
        print("\n--- SELECT SENSOR TYPE ---")
        print("1. ThermoNode")
        print("2. WindSense")
        print("3. RainDetect")
        print("4. AirQualityBox")

        choice = input("Select: ").strip()
        types = {
            "1": "ThermoNode",
            "2": "WindSense",
            "3": "RainDetect",
            "4": "AirQualityBox"
        }
        self.sensor_type = types.get(choice, "ThermoNode")
        print(f"Sensor type set to {self.sensor_type}\n")

    def send_json(self, msg):
        self.sock.sendto(json.dumps(msg).encode(), (self.server_ip, self.server_port))

    def register(self):
        msg = {
            "type": "register",
            "sensor_type": self.sensor_type,
            "sensor_id": self.sensor_id,
            "timestamp": int(time.time())
        }
        self.send_json(msg)
        data, _ = self.sock.recvfrom(4096)
        response = json.loads(data.decode())
        print("Server replied:", response)
        self.token = response.get("token")

    def generate_data(self):
        if self.sensor_type == "ThermoNode":
            return {
                "temperature": round(random.uniform(-50.0, 60.0), 1),
                "humidity": round(random.uniform(0.0, 100.0), 1),
                "dew_point": round(random.uniform(-50.0, 60.0), 1),
                "pressure": round(random.uniform(800.00, 1100.00), 2)
            }
        elif self.sensor_type == "WindSense":
            return {
                "wind_speed": round(random.uniform(0.0, 50.0), 1),
                "wind_gust": round(random.uniform(0.0, 70.0), 1),
                "wind_direction": random.randint(0, 359),
                "turbulence": round(random.uniform(0.0, 1.0), 1)
            }
        elif self.sensor_type == "RainDetect":
            return {
                "rainfall": round(random.uniform(0.0, 500.0), 1),
                "soil_moisture": round(random.uniform(0.0, 100.0), 1),
                "flood_risk": random.randint(0, 4),
                "rain_duration": random.randint(0, 60)
            }
        elif self.sensor_type == "AirQualityBox":
            return {
                "co2": random.randint(300, 5000),
                "ozone": round(random.uniform(0.0, 500.0), 1),
                "air_quality_index": random.randint(0, 500)
            }
        else:
            return {"error": "unknown sensor type"}

    def send_data(self):
        if not self.token:
            print("Sensor not registered yet.")
            return
        msg = {
            "type": "data",
            "sensor_type": self.sensor_type,
            "sensor_id": self.sensor_id,
            "token": self.token,
            "timestamp": int(time.time()),
            "low_battery": False,
            "data": self.generate_data()
        }

        self.send_json(msg)

        try:
            self.sock.settimeout(2)
            data, _ = self.sock.recvfrom(4096)
            response = json.loads(data.decode())
            print("Server replied:", response)
        except socket.timeout:
            print("No ACK received (timeout)")
        finally:
            self.sock.settimeout(None)

    def send_manual_data(self):
        if not self.token:
            print("Sensor not registered yet.")
            return

        print("\n--- MANUAL DATA ENTRY ---")
        low_battery_input = input("Low battery? (y/n): ").strip().lower()
        low_battery = low_battery_input == "y"

        # Define parameter ranges per sensor type
        ranges = {
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
        }

        sensor_ranges = ranges.get(self.sensor_type, {})
        data = {}

        for param, (min_val, max_val) in sensor_ranges.items():
            while True:
                print(f"{param} allowed range: {min_val} - {max_val}")
                value_str = input(f"Enter value for {param}: ").strip()
                try:
                    value = float(value_str)
                    if min_val <= value <= max_val:
                        data[param] = round(value, 2)
                        break
                    else:
                        print(f"Value out of range ({min_val}-{max_val}). Try again.")
                except ValueError:
                    print("Invalid input. Enter numeric value.")

        # Build and send JSON
        msg = {
            "type": "data",
            "sensor_type": self.sensor_type,
            "sensor_id": self.sensor_id,
            "token": self.token,
            "timestamp": int(time.time()),
            "low_battery": low_battery,
            "data": data
        }

        self.send_json(msg)
        try:
            self.sock.settimeout(2)
            data, _ = self.sock.recvfrom(4096)
            response = json.loads(data.decode())
            print("Server replied:", response)
        except socket.timeout:
            print("No ACK received (timeout)")
        finally:
            self.sock.settimeout(None)

    def start_auto(self):
        if self.sending:
            print("Already running.")
            return
        self.sending = True
        thread = threading.Thread(target=self.auto_loop)
        thread.daemon = True
        thread.start()
        print("Automatic sending started (every 10s).")

    def stop_auto(self):
        self.sending = False
        print("Automatic sending stopped.")

    def auto_loop(self):
        while self.sending:
            self.send_data()
            time.sleep(10)

    def menu(self):
        while True:
            print("\n--- TESTER MENU ---")
            print("1. Configure SERVER IP/PORT")
            print("2. Select sensor type")
            print("3. Register sensor")
            print("4. Start automatic sending")
            print("5. Stop automatic sending")
            print("6. Send manual data")
            print("7. Exit")
            choice = input("Select option: ").strip()

            if choice == "1":
                self.configure()
            elif choice == "2":
                self.select_sensor_type()
            elif choice == "3":
                self.register()
            elif choice == "4":
                self.start_auto()
            elif choice == "5":
                self.stop_auto()
            elif choice == "6":
                self.send_manual_data()
            elif choice == "7":
                self.stop_auto()
                print("Exiting tester.")
                break
            else:
                print("Invalid option.")

if __name__ == "__main__":
    tester = Tester()
    tester.menu()
