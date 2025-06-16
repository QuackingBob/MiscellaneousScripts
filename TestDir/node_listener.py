import tkinter as tk
from tkinter import ttk, messagebox
import socket
import struct
import threading
import time
import math
from collections import defaultdict
import colorsys
import array

import numpy as np

from node_sender import wrap_angle

from opendis.dis7 import *
from opendis.RangeCoordinates import *
from opendis.PduFactory import createPdu

MAX_EDGES = 50
POS_UDP_PORT = 12345
GRAPH_UDP_PORT = 12346
DIS_UDP_PORT = 3000


class UDPReceiver:
    def __init__(self, port, callback):
        self.port = port
        self.callback = callback
        self.running = False
        self.sock = None
        
    def start(self):
        self.running = True
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(('', self.port))
        
        thread = threading.Thread(target=self._receive_loop, daemon=True)
        thread.start()
        
    def stop(self):
        self.running = False
        if self.sock:
            self.sock.close()
            
    def _receive_loop(self):
        while self.running:
            try:
                data, addr = self.sock.recvfrom(1024)
                self.callback(data)
            except Exception as e:
                if self.running:
                    print(f"Receiver error on port {self.port}: {e}")
                break

class NodeVisualizer:
    def __init__(self, root):
        self.root = root
        self.root.title("Node Network Visualizer")
        self.root.geometry("1200x800")
        
        self.node_positions = {}  # {node_id: (x, y)}
        self.node_graphs = {}     # {sender_id: [(source, target, strength), ...]}
        self.selected_node = None
        
        self.setup_gui()

        self.lock = threading.Lock()
        self.gps = GPS()
        
        # self.position_receiver = UDPReceiver(12345, self.handle_position_packet)
        self.graph_receiver = UDPReceiver(GRAPH_UDP_PORT, self.handle_graph_packet)
        self.dis_receiver = UDPReceiver(DIS_UDP_PORT, self.handle_dis_packet)

        # self.position_receiver.start()
        self.graph_receiver.start()
        self.dis_receiver.start()


        self.update_gui()
        
    def setup_gui(self):
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        left_frame = ttk.Frame(main_frame)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        self.canvas = tk.Canvas(left_frame, bg='white', width=800, height=600)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        
        right_frame = ttk.Frame(main_frame, width=300)
        right_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=(10, 0))
        right_frame.pack_propagate(False)
        
        ttk.Label(right_frame, text="Nodes", font=('Arial', 14, 'bold')).pack(pady=(0, 10))
        
        self.node_listbox = tk.Listbox(right_frame, height=15)
        self.node_listbox.pack(fill=tk.BOTH, expand=True)
        self.node_listbox.bind('<<ListboxSelect>>', self.on_node_select)
        
        info_frame = ttk.Frame(right_frame)
        info_frame.pack(fill=tk.X, pady=(10, 0))
        
        ttk.Label(info_frame, text="Click a node to view its graph connections", 
                 wraplength=280, justify=tk.CENTER).pack()
        
        self.info_label = ttk.Label(info_frame, text="No node selected", 
                                   font=('Arial', 10, 'bold'))
        self.info_label.pack(pady=(10, 0))
        
    def handle_position_packet(self, data):
        if len(data) >= 10:  # uint16 + float + float
            node_id, x, y = struct.unpack('<Hff', data[:10])
            with self.lock:
                self.node_positions[node_id] = (x, y)
            
    def handle_graph_packet(self, data):
        if len(data) >= 4:  # min: sender_id + edge_count
            sender_id, edge_count = struct.unpack('<HH', data[:4])
            
            edges = []
            offset = 4
            for i in range(min(edge_count, MAX_EDGES)):  
                if offset + 6 <= len(data):  
                    source, target, strength = struct.unpack('<HHH', data[offset:offset+6])
                    edges.append((source, target, strength))
                    offset += 6
                else:
                    break

            with self.lock:                
                self.node_graphs[sender_id] = edges

    def handle_dis_packet(self, data):
        pdu = createPdu(data);
        pduTypeName = pdu.__class__.__name__

        if pdu.pduType == 1: # PduTypeDecoders.EntityStatePdu:
            loc = (pdu.entityLocation.x, 
                pdu.entityLocation.y, 
                pdu.entityLocation.z,
                pdu.entityOrientation.psi,
                pdu.entityOrientation.theta,
                pdu.entityOrientation.phi
                )

            body = self.gps.ecef2llarpy(*loc)

            # print("Received {}\n".format(pduTypeName)
            #     + " Id        : {}\n".format(pdu.entityID.entityID)
            #     + " Latitude  : {:.2f} degrees\n".format(rad2deg(body[0]))
            #     + " Longitude : {:.2f} degrees\n".format(rad2deg(body[1]))
            #     + " Altitude  : {:.0f} meters\n".format(body[2])
            #     + " Yaw       : {:.2f} degrees\n".format(rad2deg(body[3]))
            #     + " Pitch     : {:.2f} degrees\n".format(rad2deg(body[4]))
            #     + " Roll      : {:.2f} degrees\n".format(rad2deg(body[5]))
            #     )
            
            normalized_x = wrap_angle(body[1] + np.pi, 0, 2*np.pi) / (2 * np.pi) * 1000
            normalized_y = wrap_angle(body[0] + np.pi/2, 0, np.pi) / np.pi * 500 + 250

            node_id = int(pdu.entityID.entityID)

            with self.lock:
                self.node_positions[node_id] = (normalized_x, normalized_y)
        else:
            print("Received {}, {} bytes".format(pduTypeName, len(data)), flush=True)
            
    def on_node_select(self, event):
        selection = self.node_listbox.curselection()
        if selection:
            node_text = self.node_listbox.get(selection[0])
            try:
                node_id = int(node_text.split(':')[0].replace('Node ', ''))
                self.selected_node = node_id
                self.info_label.config(text=f"Selected: Node {node_id}")
            except ValueError:
                pass
                
    def draw_nodes(self):
        self.canvas.delete("all")
        
        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()
        
        if canvas_width <= 1 or canvas_height <= 1:
            return
        
        with self.lock:
            positions_copy = dict(self.node_positions)
            graphs_copy = dict(self.node_graphs)
            
        if self.selected_node and self.selected_node in self.node_graphs:
            self.draw_connections(canvas_width, canvas_height, positions_copy, graphs_copy)
            
        for node_id, (x, y) in positions_copy.items():
            canvas_x = (x / 1000.0) * (canvas_width - 40) + 20
            canvas_y = (y / 1000.0) * (canvas_height - 40) + 20
            
            if node_id == self.selected_node:
                color = 'red'
                size = 12
            else:
                color = 'blue'
                size = 8
                
            self.canvas.create_oval(canvas_x - size, canvas_y - size,
                                  canvas_x + size, canvas_y + size,
                                  fill=color, outline='black', width=2)
            
            self.canvas.create_text(canvas_x, canvas_y - size - 15,
                                  text=str(node_id), font=('Arial', 10, 'bold'))
                                  
    def draw_connections(self, canvas_width, canvas_height, positions_copy, graphs_copy):
        edges = graphs_copy[self.selected_node]
        
        for source, target, strength in edges:
            if source in positions_copy and target in positions_copy:
                sx, sy = positions_copy[source]
                tx, ty = positions_copy[target]
                
                canvas_sx = (sx / 1000.0) * (canvas_width - 40) + 20
                canvas_sy = (sy / 1000.0) * (canvas_height - 40) + 20
                canvas_tx = (tx / 1000.0) * (canvas_width - 40) + 20
                canvas_ty = (ty / 1000.0) * (canvas_height - 40) + 20
                
                thickness = max(1, min(5, strength // 200))
                alpha = min(255, strength // 4)
                # color = self.interpolate_color(alpha / 255)
                color = self.interpolate_color_hue(strength / 1000)
                
                
                self.canvas.create_line(canvas_sx, canvas_sy, canvas_tx, canvas_ty,
                                      fill=color, width=thickness)
                
                mid_x = (canvas_sx + canvas_tx) / 2
                mid_y = (canvas_sy + canvas_ty) / 2
                self.canvas.create_text(mid_x, mid_y, text=str(strength),
                                      font=('Arial', 8), fill='darkgreen',
                                      activefill='white')
                
    def interpolate_color(self, percentage):
        red = "#f56942" 
        green = "#63f542"

        rr = int(red[1:3], 16)
        rg = int(red[3:5], 16)
        gr = int(green[1:3], 16)
        gg = int(green[3:5], 16)

        red_interp = int(percentage * (gr - rr) + rr)
        green_interp = int(percentage * (gg - rg) + rg)

        rhex = format(red_interp, 'x')
        ghex = format(green_interp, 'x')

        return "#" + rhex + ghex + "42"

    def interpolate_color_hue(self, percentage):
        red_rgb = (245/255, 105/255, 66/255)   # "#f56942"
        green_rgb = (99/255, 245/255, 66/255)  # "#63f542"

        red_hsv = colorsys.rgb_to_hsv(*red_rgb)
        green_hsv = colorsys.rgb_to_hsv(*green_rgb)

        h1, s1, v1 = red_hsv
        h2, s2, v2 = green_hsv

        # shortest hue rotation
        if abs(h2 - h1) > 0.5:
            if h1 > h2:
                h2 += 1
            else:
                h1 += 1

        h_interp = (1 - percentage) * h1 + percentage * h2
        h_interp = h_interp % 1.0  # wrap around 1.0
        s_interp = (1 - percentage) * s1 + percentage * s2
        v_interp = (1 - percentage) * v1 + percentage * v2

        r, g, b = colorsys.hsv_to_rgb(h_interp, s_interp, v_interp)
        r = int(r * 255)
        g = int(g * 255)
        b = int(b * 255)

        return f"#{r:02x}{g:02x}{b:02x}"
                                      
    def update_node_list(self):
        self.node_listbox.delete(0, tk.END)
        
        for node_id in sorted(self.node_positions.keys()):
            pos = self.node_positions[node_id]
            has_graph = "✓" if node_id in self.node_graphs else "✗"
            self.node_listbox.insert(tk.END, 
                f"Node {node_id}: ({pos[0]:.1f}, {pos[1]:.1f}) Graph: {has_graph}")
                
    def update_gui(self):
        self.draw_nodes()
        self.update_node_list()
        
        # if selected node has no graph data
        if (self.selected_node and 
            self.selected_node not in self.node_graphs):
            # if we just lost the selection
            pass
            
        # schedule next update
        self.root.after(100, self.update_gui)
        
    def show_no_graph_message(self):
        messagebox.showinfo("No Graph Available", 
                          f"No graph data available for Node {self.selected_node}")

def main():
    root = tk.Tk()
    app = NodeVisualizer(root)
    
    try:
        root.mainloop()
    finally:
        # app.position_receiver.stop()
        app.graph_receiver.stop()
        app.dis_receiver.stop()

if __name__ == "__main__":
    main()