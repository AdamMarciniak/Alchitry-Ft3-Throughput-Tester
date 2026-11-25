"""Use the production B-mode shaders for deterministic offscreen bench images."""
from pathlib import Path
import numpy as np
import moderngl
from PySide6.QtGui import QImage


class Renderer:
    def __init__(self, host):
        self.h = host
        self.ctx = moderngl.create_standalone_context(require=330)
        self.vbo = self.ctx.buffer(np.array([-1,-1, 1,-1, -1,1, 1,1], np.float32).tobytes())
        self.bf = self.ctx.program(vertex_shader=host.VERT, fragment_shader=host.BEAMFORM)
        self.cp = self.ctx.program(vertex_shader=host.VERT, fragment_shader=host.COMPRESS)
        self.bv = self.ctx.simple_vertex_array(self.bf, self.vbo, 'in_pos')
        self.cv = self.ctx.simple_vertex_array(self.cp, self.vbo, 'in_pos')

    def render(self, analytic, box_mm, width=512, height=640):
        h, ctx, p = self.h, self.ctx, self.bf
        bands = analytic if analytic.ndim == 4 else analytic[None]
        n, samples = bands.shape[1:3]
        bank = getattr(analytic, 'bank', None)
        expected_rows = 24 if bank is not None else 144 if h.pulser.shot_method == 3 else 48
        if n != expected_rows or samples > ctx.info['GL_MAX_TEXTURE_SIZE']:
            raise ValueError('RF shape exceeds this GPU texture limit')
        textures = []
        try:
            for band in bands:
                t = ctx.texture((samples, n), 2, band.astype('f4').tobytes(), dtype='f4')
                t.filter = (moderngl.LINEAR, moderngl.LINEAR)
                t.repeat_x = t.repeat_y = False
                textures.append(t)
            for i in range(3):
                textures[min(i, len(textures)-1)].use(i)
            p['elems'].write(h.elem_uniform().tobytes())
            p['alive'].write(h.alive_mask(bank).tobytes())
            p['rx_weights'].write(h.multi_rx_weights().tobytes())
            values = {'multi_rx': int(n == 144), 'alternating': int(bank is not None), 'rf0': 0, 'rf1': 1, 'rf2': 2,
                      'viewbox': tuple(float(x)/1000 for x in box_mm),
                      'c': h.state['c'], 'dly_s': h.state['dly_us']*1e-6,
                      'fs': h.FS_HZ, 'samps': samples,
                      'cos_acc': float(np.cos(np.radians(h.state['accept']))),
                      'apod': h.state['apod'], 't0_s': h.state['t0_ns']*1e-9,
                      'neighbor_rx': int(h.pulser.shot_method == 2), 'cf_pow': h.state['cf'], 'freq_comp': int(len(bands) == 3),
                      'debug_view': h.state.get('debug_view', 0)}
            for key, val in values.items():
                p[key].value = val
            mag = ctx.texture((width, height), 1, dtype='f4')
            fb = ctx.framebuffer([mag])
            rgb = ctx.texture((width, height), 4)
            cf = ctx.framebuffer([rgb])
            textures += [mag, fb, rgb, cf]
            fb.use()
            self.bv.render(moderngl.TRIANGLE_STRIP)
            linear = np.frombuffer(fb.read(components=1, dtype='f4'), np.float32).reshape(height, width)[::-1].copy()
            peak = ctx.texture((1, 1), 1, np.array([linear.max()], np.float32).tobytes(), dtype='f4')
            textures.append(peak)
            mag.use(0)
            peak.use(1)
            for key, val in {'magtex': 0, 'maxtex': 1, 'full_scale': h.full_scale(h.state['apod'], bank),
                             'dyn_db': h.state['dyn'], 'gain_db': h.state['gain'],
                             'auto_gain': int(h.state['auto']), 'curve': h.state['curve'],
                             'debug_view': h.state.get('debug_view', 0)}.items():
                self.cp[key].value = val
            cf.use()
            self.cv.render(moderngl.TRIANGLE_STRIP)
            pixels = np.frombuffer(cf.read(components=3, alignment=1), np.uint8).reshape(height, width, 3)[::-1].copy()
            image = QImage(pixels.data, width, height, 3*width, QImage.Format_RGB888).copy()
            return linear, image
        finally:
            for resource in reversed(textures):
                resource.release()

    def close(self):
        for obj in (self.bv, self.cv, self.bf, self.cp, self.vbo, self.ctx):
            obj.release()


def _width(profile, coordinates, index):
    threshold = profile[index] * .5  # -6.02 dB amplitude
    lo = hi = index
    while lo > 0 and profile[lo-1] >= threshold:
        lo -= 1
    while hi < len(profile)-1 and profile[hi+1] >= threshold:
        hi += 1
    if lo == 0 or hi == len(profile)-1:
        return None
    def crossing(a, b):
        delta = profile[b]-profile[a]
        return float(coordinates[a] + (threshold-profile[a])/delta*(coordinates[b]-coordinates[a])) if delta else float(coordinates[a])
    return crossing(hi, hi+1) - crossing(lo-1, lo)


def wire_metrics(mag, box_mm, search_mm, anchor_mm=None, exclusion_mm=6):
    """Fixed physical ROIs; never grade compressed display pixels as signal."""
    if mag.ndim != 2 or not np.isfinite(mag).all() or np.min(mag) < 0:
        raise ValueError('Invalid beamformed magnitude image')
    h, w = mag.shape
    x = np.linspace(box_mm[0], box_mm[1], w, endpoint=False) + (box_mm[1]-box_mm[0])/(2*w)
    z = np.linspace(box_mm[2], box_mm[3], h, endpoint=False) + (box_mm[3]-box_mm[2])/(2*h)
    xx, zz = np.meshgrid(x, z)
    roi = ((xx >= search_mm[0]) & (xx <= search_mm[1]) &
           (zz >= search_mm[2]) & (zz <= search_mm[3]))
    if anchor_mm is not None:
        roi &= (np.abs(xx-anchor_mm[0]) <= 4) & (np.abs(zz-anchor_mm[1]) <= 4)
    if not roi.any():
        raise ValueError('Target search area is outside the image')
    r, c = np.unravel_index(np.argmax(np.where(roi, mag, -1)), mag.shape)
    peak = float(mag[r,c])
    # Anchor clutter gates to the baseline target, not to a moving candidate.
    ax, az = anchor_mm if anchor_mm is not None else (float(x[c]), float(z[r]))
    clutter = ((np.abs(xx-ax) >= exclusion_mm) & (np.abs(xx-ax) <= 25) &
               (np.abs(zz-az) <= 5))
    signal = (np.abs(xx-ax) <= exclusion_mm) & (np.abs(zz-az) <= 5)
    if not clutter.any() or not signal.any():
        raise ValueError('Image must include both the target and side-clutter measurement regions')
    noise95 = float(np.percentile(mag[clutter], 95))
    return {'peak_position_mm': [float(x[c]), float(z[r])], 'peak': peak,
            'lateral_width_6db_mm': _width(mag[r,:], x, c),
            'axial_width_6db_mm': _width(mag[:,c], z, r),
            'clutter_p95_relative_db': float(20*np.log10(max(noise95 or 0, 1e-12)/max(peak,1e-12))),
            'clutter_to_target_energy': float(np.sum(mag[clutter]**2)/max(float(np.sum(mag[signal]**2)),1e-20)),
            'anchor_mm': [ax, az], 'search_mm': search_mm,
            'exclusion_mm': exclusion_mm,
            'interpretation': 'Finite-wire response, not point resolution or tissue contrast. Clutter includes sidelobes, background scattering and receiver noise.'}
