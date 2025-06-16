import socket
import time
import random
from io import BytesIO
import threading

import numpy as np

from opendis.DataOutputStream import DataOutputStream
from opendis.dis7 import EntityStatePdu
from opendis.RangeCoordinates import *

UDP_PORT = 3000
DESTINATION_ADDRESS = "127.0.0.1"

udpSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
udpSocket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

gps = GPS()  # Conversion helper

NUM_NODES = 20
DELTA_T = 0.1  
ACCELERATION_STD = 0.01  
EARTH_RADIUS = 6371000  

MIN_VEL = 0.5
MAX_VEL = 1.5

nodes = []
for i in range(1, NUM_NODES + 1):
    node = {
        "id": i,
        "lat": random.uniform(-np.pi / 2, np.pi / 2),
        "lon": random.uniform(-np.pi, np.pi),
        "alt": 1.0,
        "yaw": random.uniform(-np.pi, np.pi),
        "vel": random.uniform(MIN_VEL, MAX_VEL)  
    }
    nodes.append(node)


def wrap_angle(angle, min_val, max_val):
    """Wrap angle to the range [min_val, max_val]"""
    range_size = max_val - min_val
    return ((angle - min_val) % range_size) + min_val


def update_node(node):
    node["vel"] += random.gauss(0, ACCELERATION_STD)
    node["vel"] = max(0.0, min(node["vel"], MAX_VEL))  

    node["yaw"] += random.gauss(0, np.pi/6)
    node["yaw"] = wrap_angle(node["yaw"], -np.pi, np.pi)

    delta_lat = node["vel"] * np.sin(node["yaw"]) * DELTA_T
    delta_lon = node["vel"] * np.cos(node["yaw"]) * DELTA_T
    node["lat"] = wrap_angle(node["lat"] + delta_lat, -np.pi/2, np.pi/2)
    node["lon"] = wrap_angle(node["lon"] + delta_lon, -np.pi, np.pi)

    # Compute distance traveled in this time step
    # distance = node["vel"] * DELTA_T  # meters

    # # Approximate latitude and longitude delta (radians)
    # delta_lat = distance * np.sin(node["yaw"]) / EARTH_RADIUS
    # denom = EARTH_RADIUS * np.cos(node["lat"])
    # delta_lon = 0
    # if abs(denom) >= 1e-5:
    #     delta_lon = distance * np.cos(node["yaw"]) / (denom)

    # # Update latitude and longitude
    # node["lat"] += delta_lat
    # node["lon"] += delta_lon

    # # Wrap latitude: reflect at poles and adjust longitude
    # if node["lat"] > np.pi / 2:
    #     node["lat"] = np.pi - node["lat"]
    #     node["lon"] += np.pi
    # elif node["lat"] < -np.pi / 2:
    #     node["lat"] = -np.pi - node["lat"]
    #     node["lon"] += np.pi

    # # Wrap longitude normally [-π, π]
    # node["lon"] = wrap_angle(node["lon"], -np.pi, np.pi)
    # node['lat'] = wrap_angle(node['lat'], -np.pi/2, np.pi/2)


def send_node(node):
    pdu = EntityStatePdu()
    pdu.pduType = 1
    pdu.pduStatus = 0
    pdu.entityAppearance = 0
    pdu.capabilities = 0

    pdu.entityID.siteID = 17
    pdu.entityID.applicationID = 23
    pdu.entityID.entityID = node["id"]

    pdu.marking.setString(f"Node{node['id']}")

    # lat/lon/alt + RPY to ECEF
    ecef = gps.llarpy2ecef(
        node["lon"],
        node["lat"],
        node["alt"],
        0,  # roll
        0,  # pitch
        node["yaw"]
    )

    pdu.entityLocation.x = ecef[0]
    pdu.entityLocation.y = ecef[1]
    pdu.entityLocation.z = ecef[2]
    pdu.entityOrientation.psi = ecef[5]  # yaw
    pdu.entityOrientation.theta = ecef[4]  # pitch
    pdu.entityOrientation.phi = ecef[3]  # roll

    memoryStream = BytesIO()
    outputStream = DataOutputStream(memoryStream)
    pdu.serialize(outputStream)
    data = memoryStream.getvalue()

    udpSocket.sendto(data, (DESTINATION_ADDRESS, UDP_PORT))
    # print(f"Sent {pdu.entityID.entityID}: yaw={node['yaw']:.2f} vel={node['vel']:.3f}")


lock = threading.Lock()
running = True

def stop_running():
    option = input("Press Enter to Stop ... ")
    with lock:
        global running
        running = False

def main_loop():
    print("Starting Dis Sending ... ")
    thread = threading.Thread(
        target=stop_running,
        daemon=True
    )
    thread.start()

    while True:
        with lock:
            if not running:
                break
        for node in nodes:
            update_node(node)
            send_node(node)
        time.sleep(DELTA_T)

    thread.join()
    udpSocket.close()

    print("Cleanly Stopped")


if __name__ == "__main__":
    main_loop()
