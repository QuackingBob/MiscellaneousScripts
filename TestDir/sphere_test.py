import numpy as np
import pyvista as pv
from pyvistaqt import BackgroundPlotter
import time
import sys
from PyQt5.QtWidgets import QApplication

RADIUS = 1.0

KP_V = 1.0
KP_YAW = 20.0
MIN_VEL = 0.005
MAX_VEL = 0.1
MAX_YAW_RATE = 25.0
DT = 0.05

trail_points = []
trail_actor = None
arrow_actor = None
target_actor = [None, None]
additional_arrows = []

lat1, lon1, yaw1 = 20.0, 30.0, 0.0
lat2, lon2 = -10.0, 110.0

def latlon_to_cartesian(lat, lon, radius=RADIUS):
    lat_rad = np.radians(lat)
    lon_rad = np.radians(lon)
    x = radius * np.cos(lat_rad) * np.cos(lon_rad)
    y = radius * np.cos(lat_rad) * np.sin(lon_rad)
    z = radius * np.sin(lat_rad)
    return np.array([x, y, z])

def cartesian_to_latlon(vec):
    x, y, z = vec
    r = np.linalg.norm(vec)
    lat = np.degrees(np.arcsin(z / r))
    lon = np.degrees(np.arctan2(y, x))
    return lat, lon

def tangential_direction(lat, lon, yaw_deg):
    lat_rad = np.radians(lat)
    lon_rad = np.radians(lon)
    east = np.array([-np.sin(lon_rad), np.cos(lon_rad), 0])
    north = np.array([-np.sin(lat_rad) * np.cos(lon_rad),
                      -np.sin(lat_rad) * np.sin(lon_rad),
                      np.cos(lat_rad)])
    yaw_rad = np.radians(yaw_deg)
    return (np.cos(yaw_rad) * east + np.sin(yaw_rad) * north)

def great_circle_vector(pos_from, pos_to):
    cross = np.cross(pos_from, pos_to)
    if np.linalg.norm(cross) < 1e-8:
        if np.allclose(pos_from, pos_to):
            return np.zeros(3), 0.0
        else:
            return np.array([0, 0, 1]), RADIUS * np.pi
    normal = cross / np.linalg.norm(cross)
    tangent = np.cross(normal, pos_from)
    tangent = tangent / np.linalg.norm(tangent)
    angle = np.arccos(np.clip(np.dot(pos_from, pos_to) / (np.linalg.norm(pos_from) * np.linalg.norm(pos_to)), -1.0, 1.0))
    arc_length = RADIUS * angle
    return tangent, arc_length

def rotation_matrix(axis, angle):
    axis = axis / np.linalg.norm(axis)
    K = np.array([[0, -axis[2], axis[1]],
                  [axis[2], 0, -axis[0]],
                  [-axis[1], axis[0], 0]])
    I = np.eye(3)
    return I + np.sin(angle) * K + (1 - np.cos(angle)) * (K @ K)

def heading_vector(pos, yaw_deg):
    # pos is a unit vector on the sphere (current position)
    # local vertical axis (just pos itself)
    up = pos / np.linalg.norm(pos)
    
    # reference direction in tangent plane 
    if np.allclose(up, [0, 0, 1]) or np.allclose(up, [0, 0, -1]):
        ref = np.array([1.0, 0.0, 0.0])  # fallback east vector
    else:
        ref = np.cross([0, 0, 1], up)
        ref = ref / np.linalg.norm(ref)

    # Rotate ref around 'up' (pos) by yaw to get heading vector
    yaw_rad = np.radians(yaw_deg)
    R = rotation_matrix(up, yaw_rad)
    heading = R @ ref
    return heading

def heading_vector_v2(pos, yaw_deg, lon_deg):
    yaw_rad = np.deg2rad(yaw_deg)
    lon_rad = np.deg2rad(lon_deg) + np.pi/2 # add since y is forwards

    normal = pos / np.linalg.norm(pos)

    ref_frame = np.eye(3, 3) # x , y , z
    z_axis = ref_frame[:,2]

    if np.allclose(normal, z_axis):
        # aligned with north
        R = rotation_matrix(z_axis, lon_rad + yaw_rad)
        heading = R @ ref_frame[:, 1]
        return  heading
    elif np.allclose(normal, -z_axis):
        # aligned with south
        R = rotation_matrix(z_axis, lon_rad - yaw_rad)
        heading = R @ ref_frame[:, 1]
        return  heading
    
    # orient with longitude
    R1 = rotation_matrix(z_axis, lon_rad)
    ref_frame = R1 @ ref_frame

    # apply rotation to orient z as normal
    angle = np.arccos(np.clip(np.dot(normal, ref_frame[:,2]), -1.0, 1.0))
    R2 = rotation_matrix(ref_frame[:, 0], angle)
    ref_frame = R2 @ ref_frame

    # apply yaw rotation
    R3 = rotation_matrix(ref_frame[:, 2], yaw_rad)
    ref_frame = R3 @ ref_frame

    heading = ref_frame[:, 1]
    return heading / np.linalg.norm(heading)


app = QApplication(sys.argv)
plotter = BackgroundPlotter()
plotter.set_background('black')
plotter.enable_camera_reset = False

sphere = pv.Sphere(radius=RADIUS, theta_resolution=60, phi_resolution=60)
plotter.add_mesh(sphere, style='wireframe', color='white', opacity=0.3)

target_pos = latlon_to_cartesian(lat2, lon2)
target_actor[0] = plotter.add_mesh(pv.Sphere(center=target_pos, radius=0.02), color='cyan')
target_actor[1] = plotter.add_point_labels([target_pos], ['X'], font_size=12)

state = {'lat': lat1, 'lon': lon1, 'yaw': yaw1}

velocity_text_actor = None

call_time = time.time()
delta_t = 0.05

def update_arrow():
    global arrow_actor, target_actor, lat2, lon2, additional_arrows, call_time, delta_t

    lat1 = state['lat']
    lon1 = state['lon']
    yaw1 = state['yaw']

    pos = latlon_to_cartesian(lat1, lon1)
    # orientation = tangential_direction(lat1, lon1, yaw1)  # Current heading vector (tangent to sphere)
    # orientation = heading_vector(pos, yaw1)
    orientation = heading_vector_v2(pos, yaw1, lon1)
    target = latlon_to_cartesian(lat2, lon2)

    tgt_vec, arc_length = great_circle_vector(pos, target)
    if np.linalg.norm(tgt_vec) < 1e-6:
        return

    orientation_unit = orientation / np.linalg.norm(orientation)
    tgt_unit = tgt_vec / np.linalg.norm(tgt_vec)

    # yaw control 
    angle_error_rad = np.arccos(np.clip(np.dot(orientation_unit, tgt_unit), -1.0, 1.0))
    cross = np.cross(orientation_unit, tgt_unit)
    sign = np.sign(np.dot(pos, cross))
    yaw_change = sign * np.clip(KP_YAW * np.degrees(angle_error_rad), -MAX_YAW_RATE, MAX_YAW_RATE)
    yaw1_new = yaw1 + yaw_change * delta_t

    # velocity control
    dot = np.dot(orientation_unit, tgt_unit)
    vel_gain = np.clip(dot, 0.0, 1.0)
    # vel_gain *= (1 - angle_error_rad / np.pi)
    velocity = KP_V * vel_gain # * arc_length
    velocity = np.clip(velocity, MIN_VEL, MAX_VEL)

    move_angle = velocity * delta_t / RADIUS  # angular distance to move along sphere

    # axis to rotate pos around is perpendicular to pos and orientation vectors
    axis = np.cross(pos, orientation_unit)
    if np.linalg.norm(axis) < 1e-6:
        return
    axis = axis / np.linalg.norm(axis)

    R = rotation_matrix(axis, move_angle)
    new_pos = R @ pos
    lat1_new, lon1_new = cartesian_to_latlon(new_pos)

    state['lat'] = lat1_new
    # state['yaw'] = yaw1_new
    if abs(np.sin(np.deg2rad(lat1_new))) < 0.95:
        state['lon'] = lon1_new
        state['yaw'] = yaw1_new

    # new_dir = tangential_direction(lat1_new, lon1_new, state['yaw'])
    new_dir = heading_vector_v2(new_pos, state['yaw'], lon1_new)
    new_arrow = pv.Arrow(start=new_pos, direction=new_dir, tip_length=0.1, tip_radius=0.02, shaft_radius=0.01, scale=0.5)

    if arrow_actor:
        plotter.remove_actor(arrow_actor)

    arrow_actor = plotter.add_mesh(new_arrow, color='red', reset_camera=False)

    trail_points.append(new_pos)
    global trail_actor

    if len(trail_points) > 1:
        line = pv.lines_from_points(np.array(trail_points))
        if trail_actor:
            plotter.remove_actor(trail_actor)
        
        trail_actor = plotter.add_mesh(line, color='yellow', line_width=3, reset_camera=False)

    if arc_length < 1e-1:
        if target_actor[0]:
            plotter.remove_actor(target_actor[0])
            target_actor[0] = None

        if target_actor[1]:
            if isinstance(target_actor[1], (list, tuple)):
                for actor in target_actor[1]:
                    plotter.remove_actor(actor)
            else:
                plotter.remove_actor(target_actor[1])
            target_actor[1] = None

        lat2 = np.random.uniform(-45, 45) # -80, 80
        lon2 = np.random.uniform(-180, 180)



        new_target_pos = latlon_to_cartesian(lat2, lon2)
        target_actor[0] = plotter.add_mesh(pv.Sphere(center=new_target_pos, radius=0.02), color='cyan', reset_camera=False)
        target_actor[1] = plotter.add_point_labels([new_target_pos], ['X'], point_color='cyan', font_size=12)

    # additional arrows:

    # clear additional arrows
    for arr in additional_arrows:
        plotter.remove_actor(arr)
    additional_arrows = []

    # add new ones
    tgt_arrow = pv.Arrow(start=new_pos, direction=tgt_unit, tip_length=0.1, tip_radius=0.02, shaft_radius=0.01, scale=0.5)
    additional_arrows.append(plotter.add_mesh(tgt_arrow, color='lime', reset_camera=False))

    # global velocity_text_actor

    # text = f"ΔYaw: {yaw_change * DT:+.2f} deg\nΔVel: {velocity:+.3f} units/s"
    
    # if velocity_text_actor:
    #     plotter.remove_actor(velocity_text_actor)

    # velocity_text_actor = plotter.add_text(
    #     text,
    #     position='lower_left',
    #     font_size=12,
    #     color='white',
    #     shadow=True
    # )
    print(f"\rΔYaw: {yaw_change * DT:+6.2f} deg | ΔVel: {velocity:+.3f} u/s | ArcLen: {arc_length:.3f} rad | AngleErr: {np.degrees(angle_error_rad):.2f}° | DT: {delta_t:.3f} s ", end='')

    end_time = time.time()
    delta_t = end_time - call_time
    call_time = end_time


plotter.add_callback(update_arrow, interval=50)
sys.exit(app.exec_())