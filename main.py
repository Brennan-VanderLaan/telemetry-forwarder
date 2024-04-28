import threading
import time
import requests
import socket
import json
import struct


# Global telemetry state
telemetry_state = None
freq_state = {}
sample_size = 1000  # Number of samples to calculate the average frequency

# Configuration
POLLING_URL = "http://127.0.0.1:8888/api/getgamedata"
POLLING_HZ = 50
UDP_IP = "127.0.0.1"
UDP_PORT = 9923
UDP_SEND_HZ = 100  # Target frequency in Hz
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setblocking(False)

def monitor_frequency(loop_func):
    """Decorator to monitor and print the frequency of loops, averaging over several cycles."""
    def wrapper(hz):
        global freq_state
        cycle_time = 1.0 / hz
        next_time = time.perf_counter()
        elapsed_times = []
        while True:
            start_time = time.perf_counter()
            loop_func()
            next_time += cycle_time
            sleep_time = max(next_time - time.perf_counter(), 0)
            if sleep_time > 0:
                time.sleep(sleep_time)
            elapsed = time.perf_counter() - start_time
            elapsed_times.append(elapsed)
            if len(elapsed_times) > sample_size:
                elapsed_times.pop(0)
            avg_frequency = 1.0 / (sum(elapsed_times) / len(elapsed_times))
            freq_state[loop_func.__name__] = avg_frequency

    return wrapper

@monitor_frequency
def fetch_telemetry():
    global telemetry_state
    try:
        response = requests.get(POLLING_URL)
        response.raise_for_status()
        data = response.json()['NewData']
        gear_mapping = {'N': 0.0, 'R': -1.0}  # Assuming 'R' for Reverse
        for i in range(1, 7):  # Assuming gears 1 through 6
            gear_mapping[str(i)] = float(i)

        # Calculate average wheel slip, which could indicate a burn-out if high
        average_wheel_slip = (data['FeedbackData']['RearLeftWheelSlip'] + data['FeedbackData']['RearRightWheelSlip']) / 2

        # Define a simple burn-out condition: high slip, low speed
        burn_out = average_wheel_slip > 1 and data['SpeedKmh'] < 10  # threshold values are examples
        drift = average_wheel_slip > 1 and data['SpeedKmh'] > 10  # threshold values are examples

        # Example scalings
        engineRPM_scaled = (float(data['FilteredRpms']) / 10000) * 10
        currentSpeed_scaled = (float(data['SpeedKmh']) / 300) * 10
        throttle_scaled = float(data['Throttle']) * 0.1
        gear_scaled = (gear_mapping.get(data['Gear'], 0.0) / 6) * 10

        telemetry_state = {
            'engineRPM': engineRPM_scaled,
            'gas': throttle_scaled,
            'brake': float(data['Brake']) * 0.1,
            'clutch': float(data['Clutch']) * 0.1,
            'tractionControl': float(data['TCActive']) * 10,
            'abs': float(data['ABSActive']) * 10,
            'gear': gear_scaled,
            'currentSpeed': currentSpeed_scaled,
            'burnOut': (float(burn_out) * 10),
            'drift': (float(drift) * 10)
        }
    except requests.RequestException as e:
        print(f"Failed to fetch data: {e}")


@monitor_frequency
def send_udp_data():
    global sock
    if telemetry_state:
        # Define the format to pack the data: float values and integers
        # This assumes all values are being sent as floats for simplicity
        data_format = 'f' * len(telemetry_state.values())  # 'f' for float, repeat for each value
        packed_data = struct.pack(data_format, *telemetry_state.values())
        try:
            sock.sendto(packed_data, (UDP_IP, UDP_PORT))
        except BlockingIOError:
            pass  # Handle case where the socket is not ready to send data


def main():
    polling_thread = threading.Thread(target=fetch_telemetry, args=(POLLING_HZ,))
    polling_thread.daemon = True
    polling_thread.start()

    udp_thread = threading.Thread(target=send_udp_data, args=(UDP_SEND_HZ,))
    udp_thread.daemon = True
    udp_thread.start()

    try:
        while True:
            time.sleep(1.1)
            for loop in freq_state:
                print(f"{loop} running at {freq_state[loop]:.2f} Hz")
    except KeyboardInterrupt:
        print("Stopped by user")
        sock.close()

if __name__ == "__main__":
    main()
