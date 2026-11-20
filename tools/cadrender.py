"""Tiny flat-shaded orthographic renderer that imitates Inventor thumbnails:
light grey parts, Lambert shading, darkened feature edges, black background.
Usage: python3 -I cadrender.py <outdir>
"""
import sys, math
import numpy as np
from PIL import Image, ImageFilter

S = 1024          # supersampled size; downscaled to 512
BG = (0, 0, 0)

# ---------- mesh primitives (triangles with color + part id) ----------
class Scene:
    def __init__(self):
        self.tris = []   # (v0, v1, v2, color, pid)
        self.pid = 0

    def _id(self):
        self.pid += 1
        return self.pid

    def quad(self, a, b, c, d, color, pid):
        self.tris.append((a, b, c, color, pid))
        self.tris.append((a, c, d, color, pid))

    def box(self, x0, y0, z0, x1, y1, z1, color=(222, 222, 222)):
        p = self._id()
        v = lambda x, y, z: np.array([x, y, z], float)
        A, B, C, D = v(x0, y0, z0), v(x1, y0, z0), v(x1, y1, z0), v(x0, y1, z0)
        E, F, G, H = v(x0, y0, z1), v(x1, y0, z1), v(x1, y1, z1), v(x0, y1, z1)
        for q in ((A, D, C, B), (E, F, G, H), (A, B, F, E), (B, C, G, F), (C, D, H, G), (D, A, E, H)):
            self.quad(*q, color, p)
        return p

    def cyl(self, cx, cy, z0, z1, r, color=(222, 222, 222), n=36, axis='z', cone_r=None):
        """Cylinder (or frustum if cone_r) along an axis starting at (cx, cy, z0)."""
        p = self._id()
        r1 = r if cone_r is None else cone_r
        def P(ang, h, rr):
            u, w = rr * math.cos(ang), rr * math.sin(ang)
            if axis == 'z': return np.array([cx + u, cy + w, h])
            if axis == 'x': return np.array([h, cx + u, cy + w])
            return np.array([cx + u, h, cy + w])        # axis y
        for i in range(n):
            a0, a1 = 2 * math.pi * i / n, 2 * math.pi * (i + 1) / n
            b0, b1, t0, t1 = P(a0, z0, r), P(a1, z0, r), P(a0, z1, r1), P(a1, z1, r1)
            self.quad(b0, b1, t1, t0, color, p)
            c0 = {'z': np.array([cx, cy, z0]), 'x': np.array([z0, cx, cy]), 'y': np.array([cx, z0, cy])}[axis]
            c1 = {'z': np.array([cx, cy, z1]), 'x': np.array([z1, cx, cy]), 'y': np.array([cx, z1, cy])}[axis]
            self.tris.append((c0, b1, b0, color, p))
            self.tris.append((c1, t0, t1, color, p))
        return p

    def decal_rect(self, face, a0, b0, a1, b1, level, color=(30, 30, 34), eps=0.004):
        """Dark flat rectangle on an axis-aligned face. face in x+,x-,y+,y-,z+."""
        p = self._id()
        if face == 'z+': pts = [(a0, b0, level + eps), (a1, b0, level + eps), (a1, b1, level + eps), (a0, b1, level + eps)]
        elif face == 'y-': pts = [(a0, level - eps, b0), (a1, level - eps, b0), (a1, level - eps, b1), (a0, level - eps, b1)]
        elif face == 'x+': pts = [(level + eps, a0, b0), (level + eps, a1, b0), (level + eps, a1, b1), (level + eps, a0, b1)]
        elif face == 'x-': pts = [(level - eps, a0, b0), (level - eps, a1, b0), (level - eps, a1, b1), (level - eps, a0, b1)]
        pts = [np.array(q, float) for q in pts]
        self.quad(*pts, color, p)

    def decal_disc(self, face, ca, cb, r, level, color=(30, 30, 34), eps=0.004, n=28):
        p = self._id()
        def pt(u, w):
            if face == 'z+': return np.array([u, w, level + eps])
            if face == 'y-': return np.array([u, level - eps, w])
            if face == 'x+': return np.array([level + eps, u, w])
        c = pt(ca, cb)
        for i in range(n):
            a0, a1 = 2 * math.pi * i / n, 2 * math.pi * (i + 1) / n
            self.tris.append((c, pt(ca + r * math.cos(a0), cb + r * math.sin(a0)),
                              pt(ca + r * math.cos(a1), cb + r * math.sin(a1)), color, p))


# ---------- rasterizer ----------
def render(scene, path, yaw=-38, pitch=32, margin=0.09):
    yr, pr = math.radians(yaw), math.radians(pitch)
    Rz = np.array([[math.cos(yr), -math.sin(yr), 0], [math.sin(yr), math.cos(yr), 0], [0, 0, 1]])
    Rx = np.array([[1, 0, 0], [0, math.cos(pr), -math.sin(pr)], [0, math.sin(pr), math.cos(pr)]])
    R = Rx @ Rz
    light = np.array([-0.35, -0.55, 0.76]); light /= np.linalg.norm(light)

    V = []
    for a, b, c, col, pid in scene.tris:
        V.append((R @ a, R @ b, R @ c, col, pid, np.cross(b - a, c - a)))
    allp = np.array([p for t in V for p in t[:3]])
    # screen: x = X, y = Z (up); depth = Y (into screen)
    xs, ys = allp[:, 0], allp[:, 2]
    span = max(xs.max() - xs.min(), ys.max() - ys.min())
    scale = S * (1 - 2 * margin) / span
    ox = S / 2 - (xs.max() + xs.min()) / 2 * scale
    oy = S / 2 + (ys.max() + ys.min()) / 2 * scale

    img = np.zeros((S, S, 3), float); img[:] = BG
    zb = np.full((S, S), np.inf)
    ids = np.zeros((S, S), int)
    for k, (a, b, c, col, pid, nrm) in enumerate(V):
        n = np.linalg.norm(nrm)
        if n == 0: continue
        nw = nrm / n
        shade = 0.5 + 0.5 * max(0.0, float(np.dot(nw, light)))
        # rotate normal to view to cull back faces (view dir = +Y in rotated space)
        nv = R @ nw
        if nv[1] > 1e-6: continue
        P = np.array([[p[0] * scale + ox, -p[2] * scale + oy, p[1]] for p in (a, b, c)])
        x0, x1 = int(max(0, P[:, 0].min())), int(min(S - 1, P[:, 0].max() + 1))
        y0, y1 = int(max(0, P[:, 1].min())), int(min(S - 1, P[:, 1].max() + 1))
        if x1 < x0 or y1 < y0: continue
        gx, gy = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        (ax, ay, az), (bx, by, bz), (cx, cy, cz) = P
        den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(den) < 1e-12: continue
        w0 = ((by - cy) * (gx - cx) + (cx - bx) * (gy - cy)) / den
        w1 = ((cy - ay) * (gx - cx) + (ax - cx) * (gy - cy)) / den
        w2 = 1 - w0 - w1
        m = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
        if not m.any(): continue
        z = w0 * az + w1 * bz + w2 * cz
        sub = zb[y0:y1 + 1, x0:x1 + 1]
        upd = m & (z < sub)
        sub[upd] = z[upd]
        img[y0:y1 + 1, x0:x1 + 1][upd] = np.array(col) * shade
        ids[y0:y1 + 1, x0:x1 + 1][upd] = pid * 8 + (int(round(shade * 7)) % 8)

    # feature edges: where face/part id changes
    e = np.zeros((S, S), bool)
    e[:, 1:] |= ids[:, 1:] != ids[:, :-1]
    e[1:, :] |= ids[1:, :] != ids[:-1, :]
    e &= np.isfinite(zb) | np.roll(np.isfinite(zb), 1, 0) | np.roll(np.isfinite(zb), 1, 1)
    img[e & np.isfinite(zb)] *= 0.62
    out = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).resize((512, 512), Image.LANCZOS)
    out.save(path)


# ---------- models ----------
def ensamble():
    s = Scene()
    g = 0.025
    widths = [1.25, 0.75, 1.25]; D, H = 1.9, 1.25
    x = 0
    for i, w in enumerate(widths):
        s.box(x, 0, 0.06, x + w - g, D, H)            # módulo
        x += w
    W = x - g
    s.box(-0.04, -0.03, 0, W + 0.04, D + 0.03, 0.08)  # base
    s.box(-0.05, -0.05, H, W + 0.05, D + 0.05, H + 0.14)  # tapa
    for hx in (W * 0.36, W * 0.64):                   # asas
        s.box(hx - 0.13, D * 0.5 - 0.09, H + 0.14, hx + 0.13, D * 0.5 + 0.09, H + 0.26)
        s.cyl(hx - 0.13, H + 0.26, D * 0.5 - 0.09, D * 0.5 + 0.09, 0.0, axis='y')
    # frente (y = 0): ventanas, bornes, interruptor
    s.decal_rect('y-', 0.35, 0.86, 0.9, 1.0, 0)
    s.decal_disc('y-', 0.62, 0.55, 0.075, 0)
    s.decal_disc('y-', 0.62, 0.32, 0.075, 0)
    s.decal_rect('y-', 1.4, 0.86, 1.8, 1.0, 0)
    s.decal_disc('y-', 1.6, 0.5, 0.075, 0)
    s.decal_disc('y-', 2.15, 0.35, 0.07, 0); s.decal_disc('y-', 2.95, 0.35, 0.07, 0)
    s.cyl(2.55, 0.0, 0.62, 0.62, 0.05, axis='y')      # base interruptor
    s.cyl(2.55, 0.62, -0.18, 0.0, 0.035, axis='y')    # palanca
    # costado derecho (x = W): ranuras de ventilación
    for k in range(5):
        z = 0.3 + k * 0.17
        s.decal_rect('x+', 0.35, z, 1.55, z + 0.05, W)
    return s


def requerimientos():
    s = Scene()
    s.box(0, 0, 0, 1.7, 2.3, 0.07)                           # tabla
    s.box(0.5, 2.05, 0.07, 1.2, 2.32, 0.2)                    # pinza
    s.cyl(0.85, 2.25, 0.2, 0.26, 0.12)
    s.box(0.18, 0.2, 0.07, 1.52, 1.92, 0.09, color=(236, 236, 236))  # hoja
    for k in range(4):
        y = 1.6 - k * 0.38
        s.box(0.32, y, 0.09, 0.5, y + 0.18, 0.15)            # casilla
        s.box(0.62, y + 0.05, 0.09, 1.36 - (k % 2) * 0.25, y + 0.13, 0.115)  # renglón
        if k < 3:
            s.decal_rect('z+', 0.36, y + 0.04, 0.46, y + 0.14, 0.15)
    # lápiz sobre la tabla
    s.cyl(2.0, 0.07, 0.4, 2.0, 0.07, axis='y', n=6)
    s.cyl(2.0, 0.07, 0.4, 0.12, 0.07, axis='y', cone_r=0.008, n=6)
    s.cyl(2.0, 0.07, 2.0, 2.2, 0.075, axis='y')
    return s


def pruebas():
    s = Scene()
    # multímetro
    s.box(0, 0, 0, 1.25, 2.1, 0.32)
    s.box(0.12, 1.35, 0.32, 1.13, 1.92, 0.34)
    s.decal_rect('z+', 0.18, 1.42, 1.07, 1.85, 0.34)
    s.cyl(0.625, 0.85, 0.32, 0.42, 0.3)
    s.box(0.6, 0.62, 0.42, 0.65, 1.1, 0.47)
    for xx in (0.25, 0.5, 0.75, 1.0):
        s.decal_disc('z+', xx, 0.22, 0.055, 0.32)
    # puntas de prueba
    for k, yy in enumerate((0.45, 0.85)):
        s.cyl(yy, 0.06, 1.55, 2.9, 0.06, axis='x')
        s.cyl(yy, 0.06, 2.9, 3.3, 0.06, axis='x', cone_r=0.01)
        s.cyl(yy, 0.06, 1.55, 1.75, 0.1, axis='x')
    # módulo de la fuente al fondo
    s.box(1.7, 1.2, 0, 3.0, 2.6, 1.1)
    s.decal_rect('y-', 2.0, 0.75, 2.7, 0.9, 1.2)
    s.decal_disc('y-', 2.15, 0.35, 0.07, 1.2); s.decal_disc('y-', 2.55, 0.35, 0.07, 1.2)
    return s


# ---------- módulos abiertos con su contenido ----------
GRIS = (222, 222, 222)
PCB = (150, 156, 150)
OSCURO = (92, 94, 98)
METAL = (190, 192, 196)


def caja_abierta(s, x0, y0, w, d, h, t=0.06, frente=None):
    """Módulo impreso: piso y cuatro paredes con espesor t, abierto arriba."""
    s.box(x0, y0, 0, x0 + w, y0 + d, t)
    s.box(x0, y0, 0, x0 + w, y0 + t, h)              # frente
    s.box(x0, y0 + d - t, 0, x0 + w, y0 + d, h)      # trasera
    s.box(x0, y0, 0, x0 + t, y0 + d, h)              # izquierda
    s.box(x0 + w - t, y0, 0, x0 + w, y0 + d, h)      # derecha
    s.box(x0 - 0.02, y0 - 0.02, h - 0.05, x0 + w + 0.02, y0 + 0.02, h)   # ceja de la ranura
    s.box(x0 - 0.02, y0 + d - 0.02, h - 0.05, x0 + w + 0.02, y0 + d + 0.02, h)


def borne(s, x, z, y=0.0, r=0.07):
    s.cyl(x, z, y - 0.09, y, r, axis='y', color=OSCURO)
    s.cyl(x, z, y - 0.13, y - 0.09, r * 0.55, axis='y', color=METAL)


def ventana(s, x0, x1, z0, z1, y=0.0):
    s.decal_rect('y-', x0, z0, x1, z1, y)


def contenido_fuente(s, x0, y0, w, d):
    s.box(x0 + 0.15, y0 + 0.35, 0.06, x0 + w - 0.15, y0 + d * 0.62, 0.1, color=PCB)       # placa
    s.cyl(x0 + 0.38, y0 + 0.75, 0.1, 0.7, 0.17, color=OSCURO)                             # capacitor 4700 µF
    s.box(x0 + 0.62, y0 + 0.5, 0.1, x0 + 0.78, y0 + 0.56, 0.36, color=OSCURO)              # LM317
    s.box(x0 + 0.58, y0 + 0.56, 0.1, x0 + 0.82, y0 + 0.6, 0.48, color=METAL)               # disipador
    s.box(x0 + 0.2, y0 + d * 0.66, 0.06, x0 + w - 0.2, y0 + d - 0.15, 0.62)                # transformador
    s.box(x0 + 0.32, y0 + d * 0.66 - 0.02, 0.06, x0 + w - 0.32, y0 + d - 0.13, 0.5, color=METAL)


def contenido_probador(s, x0, y0, w, d):
    s.box(x0 + 0.12, y0 + 0.3, 0.06, x0 + w - 0.12, y0 + d * 0.55, 0.1, color=PCB)
    s.cyl(x0 + w * 0.5, y0 + 0.6, 0.1, 0.28, 0.06, color=METAL)                             # LED
    s.cyl(x0 + w * 0.5, y0 + 0.6, 0.28, 0.34, 0.06, cone_r=0.03, color=METAL)
    s.box(x0 + 0.18, y0 + 0.85, 0.1, x0 + 0.34, y0 + 0.95, 0.18, color=OSCURO)              # resistencia
    s.box(x0 + 0.15, y0 + d * 0.6, 0.06, x0 + w - 0.15, y0 + d - 0.15, 0.5)                 # transformador pequeño


def contenido_soldadora(s, x0, y0, w, d):
    s.box(x0 + 0.22, y0 + 0.55, 0.06, x0 + w - 0.22, y0 + d - 0.45, 0.82, color=METAL)     # núcleo
    s.box(x0 + 0.32, y0 + 0.45, 0.12, x0 + w - 0.32, y0 + d - 0.35, 0.72, color=OSCURO)    # bobinado
    s.box(x0 + 0.42, y0 + 0.8, 0.82, x0 + w - 0.42, y0 + 1.15, 0.84, color=GRIS)           # etiqueta
    s.cyl(x0 + 0.42, 0.4, y0 + 0.12, y0 + 0.45, 0.07, axis='y', color=METAL)                 # secundario grueso
    s.cyl(x0 + w - 0.42, 0.4, y0 + 0.12, y0 + 0.45, 0.07, axis='y', color=METAL)


def modulo_fuente():
    s = Scene(); w, d, h = 1.25, 1.9, 1.1
    caja_abierta(s, 0, 0, w, d, h); contenido_fuente(s, 0, 0, w, d)
    ventana(s, 0.3, 0.95, 0.78, 0.94)
    s.cyl(0.4, 0.5, -0.1, 0.0, 0.11, axis='y', color=OSCURO)          # perilla
    borne(s, 0.78, 0.5); borne(s, 1.0, 0.5)
    s.decal_disc('y-', 0.22, 0.78, 0.035, 0, color=(70, 150, 90))      # LED de encendido
    return s


def modulo_probador():
    s = Scene(); w, d, h = 0.8, 1.9, 1.1
    caja_abierta(s, 0, 0, w, d, h); contenido_probador(s, 0, 0, w, d)
    ventana(s, 0.18, 0.62, 0.78, 0.94)
    borne(s, 0.28, 0.45); borne(s, 0.52, 0.45)
    return s


def modulo_soldadora():
    s = Scene(); w, d, h = 1.25, 1.9, 1.1
    caja_abierta(s, 0, 0, w, d, h); contenido_soldadora(s, 0, 0, w, d)
    for k in range(5):                                                 # ranuras laterales
        z = 0.25 + k * 0.15
        s.decal_rect('x+', 0.35, z, 1.55, z + 0.045, w)
    s.cyl(0.62, 0.75, -0.02, 0.0, 0.06, axis='y', color=METAL)        # interruptor
    s.cyl(0.62, 0.75, -0.2, -0.02, 0.025, axis='y', color=METAL)
    borne(s, 0.32, 0.32, r=0.08); borne(s, 0.92, 0.32, r=0.08)
    return s


def integracion():
    s = Scene(); d, h = 1.9, 1.1; g = 0.03
    x = 0
    for w, fn in ((1.25, contenido_fuente), (0.8, contenido_probador), (1.25, contenido_soldadora)):
        caja_abierta(s, x, 0, w, d, h); fn(s, x, 0, w, d); x += w + g
    # tapa apoyada al lado
    pass
    borne(s, 0.78, 0.5); borne(s, 1.0, 0.5); borne(s, 1.42, 0.45); borne(s, 1.66, 0.45)
    s.cyl(2.7, 0.75, -0.2, 0.0, 0.03, axis='y', color=METAL)
    return s


def render_modulos(out):
    render(modulo_fuente(), f'{out}/cad-modulo-fuente-512.png', yaw=-30, pitch=52, margin=0.05)
    render(modulo_probador(), f'{out}/cad-modulo-probador-led-512.png', yaw=-30, pitch=52, margin=0.06)
    render(modulo_soldadora(), f'{out}/cad-modulo-soldadora-512.png', yaw=-30, pitch=52, margin=0.05)
    render(integracion(), f'{out}/cad-integracion-512.png', yaw=-22, pitch=54, margin=0.03)


if __name__ == '__main__':
    out = sys.argv[1]
    render(ensamble(), f'{out}/cad-ensamble-512.png', margin=0.03)
    render(requerimientos(), f'{out}/cad-requerimientos-512.png', yaw=-30, pitch=40)
    render(pruebas(), f'{out}/cad-pruebas-512.png', yaw=-34, pitch=36)
    render_modulos(out)
    print('ok')
