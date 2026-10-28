import cadquery as cq
import partkit as pk
import math

def build_part(length=49.52, width=27.37, thickness=3.0, tab_width=16.8, tab_length=2.2, tab_corner_radius=1.33, hole_diameter=10.05):
    half_len = length / 2.0
    half_wid = width / 2.0
    body_bottom = -half_wid + tab_length
    th = tab_width / 2.0
    r = tab_corner_radius
    # clamp radius to not exceed tab dimensions
    if r > th:
        r = th
    if r > tab_length:
        r = tab_length

    # helper to generate fillet arc points from a->b with center
    def arc_points(center, radius, start_angle_deg, end_angle_deg, steps=8):
        pts = []
        for i in range(steps + 1):
            t = i / steps
            ang = math.radians(start_angle_deg + t * (end_angle_deg - start_angle_deg))
            x = center[0] + radius * math.cos(ang)
            y = center[1] + radius * math.sin(ang)
            pts.append((x, y))
        return pts

    # outline clockwise starting at top-left
    pts = []
    pts.append((-half_len, half_wid))
    pts.append((half_len, half_wid))
    pts.append((half_len, body_bottom))
    pts.append((th, body_bottom))

    # right tip fillet: connects side (th, -half_wid+r) to tip (th-r, -half_wid)
    # center at (th-r, -half_wid+r)
    c_r = (th - r, -half_wid + r)
    # side point to tip point via 90deg arc (0deg -> -90deg)
    # side point angle 0deg from center (east), tip point angle -90deg (south)
    right_arc = arc_points(c_r, r, 0, -90, steps=8)
    pts.extend(right_arc)

    # tip bottom edge middle is covered by end of right arc to start of left arc
    # left tip fillet center (-th+r, -half_wid+r), from tip (-th+r, -half_wid) to side (-th, -half_wid+r)
    c_l = (-th + r, -half_wid + r)
    left_arc = arc_points(c_l, r, -90, -180, steps=8)
    pts.extend(left_arc)

    pts.append((-th, body_bottom))
    pts.append((-half_len, body_bottom))

    part = pk.outline_from_points(pts, thickness)

    # hole centered in main body (center of rectangle length x (width-tab_length))
    # main body center y = (half_wid + body_bottom)/2 = tab_length/2
    hole_center = (0.0, tab_length / 2.0)
    part = pk.cut_circle(part, hole_center, hole_diameter)

    return part
