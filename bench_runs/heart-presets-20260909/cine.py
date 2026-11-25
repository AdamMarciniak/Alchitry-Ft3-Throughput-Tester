"""Export comparable cine previews with the production renderer, offline only."""
import copy
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from PySide6.QtGui import QImage
from analyze import SOURCES, OUT, load_session
from render_clips import COMMON, BOX
from test_rf_debug_ui import HostTests
from bench_render import Renderer
from rf_debug import atomic_json, validate_settings

HostTests.setUpClass()  # 'sim' set before importing host; no physical USB.
case=HostTests();case.setUp()
renderer=Renderer(case.h)
font=ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf',16)
try:
    assert not case.h.HW
    for name,path in SOURCES.items():
        case.w.debug_open_rf(path,raise_errors=True)
        s=case.w.debug_session
        settings=validate_settings(COMMON,s.metadata['acquired_settings'])
        case.w.debug_apply(settings,replay=True)
        pictures=[];indices=list(range(0,len(s.rf),4));profiles=[]
        for frame in indices:
            analytic=case.h.prepare_analytic(case.w._review_rf(frame),case.h.cfg['samps'],live=False)
            mag,qimage=renderer.render(analytic,BOX,width=384,height=480)
            rgb=qimage.convertToFormat(QImage.Format_RGB888)
            arr=np.frombuffer(rgb.bits(),np.uint8).reshape(rgb.height(),rgb.bytesPerLine())[:,:rgb.width()*3].reshape(rgb.height(),rgb.width(),3)
            picture=Image.new('RGB',(384,514),'#101921')
            picture.paste(Image.fromarray(arr),(0,34))
            ImageDraw.Draw(picture).text((10,6),f'{name.upper()} | RF frame {frame} | common settings',font=font,fill='#dce5eb')
            pictures.append(picture)
            profiles.append(np.median(mag[:,178:206],axis=1))
        duration=round(4*s.metadata['acquired_settings']['transmit']['frame_ms'])
        pictures[0].save(OUT/f'{name}-common.gif',save_all=True,append_images=pictures[1:],duration=duration,loop=0,optimize=False)
        np.save(OUT/f'{name}-central-profiles.npy',np.array(profiles),allow_pickle=False)
        atomic_json(OUT/f'{name}-cine.json',{'source':str(path),'rf_sha256':s.metadata['rf_sha256'],
            'sampled_frame_indices':indices,'frame_duration_ms':duration,'timing':'Nominal commanded sweep period; preview samples every fourth sweep.',
            'common_patch':COMMON,'box_mm':BOX,'size':[384,480]})
        print(name,len(pictures),'offline cine frames exported',flush=True)
finally:
    renderer.close();case.tearDown()
