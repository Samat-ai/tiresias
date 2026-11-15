"""Local playback of generated character loops with procedural fallback."""
from __future__ import annotations

import math
import logging
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageSequence

ASSET_DIR=Path(__file__).resolve().parents[1]/'static'/'avatar'
logger=logging.getLogger(__name__)


@lru_cache(maxsize=2)
def _artwork(directory: Path):
    try:
        with Image.open(directory/'tiresias.png') as source:
            master=source.convert('RGB').resize((400,400),Image.Resampling.LANCZOS)
    except (OSError,ValueError):
        return None
    loops={}
    for state in ('listening','thinking','speaking'):
        try:
            with Image.open(directory/f'{state}.gif') as source:
                if source.n_frames>64 or max(source.size)>2048:
                    raise ValueError('Animation exceeds local playback limits')
                frames=[]
                for frame in ImageSequence.Iterator(source):
                    frames.append((frame.convert('RGB').resize((400,400),Image.Resampling.LANCZOS),
                                   max(20,int(frame.info.get('duration',100)))))
                loops[state]=frames
        except (OSError,ValueError):
            # A missing or invalid loop must never prevent the call from starting.
            logger.info('Using character still for %s animation',state)
    return master,loops


def _font(size: int, *, serif=False):
    candidates=(['C:/Windows/Fonts/georgia.ttf','/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf']
                if serif else ['C:/Windows/Fonts/seguisb.ttf','/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'])
    for path in candidates:
        if Path(path).is_file():
            return ImageFont.truetype(path,size)
    return ImageFont.load_default(size=size)


class AvatarRenderer:
    width, height = 480, 640
    ink = '#123F43'
    teal = '#287E7C'
    paper = '#EAF3EF'
    gold = '#B98528'
    labels = {'connecting':'Connecting', 'listening':"I'm listening", 'thinking':'Taking a look',
              'speaking':'Speaking', 'ended':'Call ended'}

    def __init__(self):
        self.title=_font(43,serif=True)
        self.label=_font(30)
        self.small=_font(19)
        self.artwork=_artwork(ASSET_DIR)
        # Supersample the static illustration once; dynamic work stays small.
        if self.artwork:
            self.base=Image.new('RGB',(self.width,self.height),self.paper)
            d=ImageDraw.Draw(self.base)
            d.text((240,53),'Tiresias',font=self.title,fill=self.ink,anchor='mm')
            d.text((240,600),'Here with you.',font=self.small,fill=self.ink,anchor='mm')
        else:
            self.base=self._portrait()

    def _portrait(self):
        image=Image.new('RGB',(960,1280),self.paper)
        d=ImageDraw.Draw(image)
        def ellipse(box,**kw):
            d.ellipse(tuple(int(v*2) for v in box),**kw)
        def line(points,fill,width=2):
            d.line([(int(x*2),int(y*2)) for x,y in points],fill=fill,width=width*2,joint='curve')
        def polygon(points,fill):
            d.polygon([(int(x*2),int(y*2)) for x,y in points],fill=fill)
        ellipse((73,120,407,454),fill='#D8E8E1')
        ellipse((96,142,384,430),outline='#B6CDC4',width=2)
        # Draped shoulders and a simple sculptural, friendly seer silhouette.
        ellipse((116,350,364,487),fill=self.ink)
        polygon([(129,407),(240,471),(346,402),(363,476),(118,476)],self.teal)
        polygon([(211,352),(270,352),(286,399),(240,425),(195,397)],'#C28F69')
        ellipse((155,177,326,377),fill=self.ink)
        ellipse((168,207,311,383),fill='#D8AB82')
        ellipse((158,276,181,316),fill='#D8AB82')
        ellipse((299,276,322,316),fill='#D8AB82')
        # Silver hair and beard, with curls kept clear at mobile video sizes.
        for box in [(158,204,203,267),(179,182,225,239),(214,177,261,229),
                    (248,183,292,237),(276,205,321,264)]:
            ellipse(box,fill='#F7F9F5')
        polygon([(170,318),(187,344),(210,349),(240,340),(270,349),(296,322),
                 (290,374),(264,407),(240,423),(212,407),(186,375)],'#F7F9F5')
        line([(211,376),(219,396)],'#CFDCD5',2)
        line([(239,380),(239,408)],'#CFDCD5',2)
        line([(269,375),(260,397)],'#CFDCD5',2)
        line([(231,282),(222,317),(238,322)],'#A87455',3)
        line([(187,272),(214,268)],self.ink,3)
        line([(264,268),(290,272)],self.ink,3)
        # Laurel: Tiresias's Greek origin, rather than generic robot chrome.
        for side in (-1,1):
            for i in range(5):
                x=240+side*(75-i*10)
                y=246-i*14
                polygon([(x,y),(x+side*15,y-16),(x+side*14,y+5),(x,y+13)],self.gold)
        line([(147,444),(205,469)],'#77AD9F',2)
        line([(278,469),(331,440)],'#77AD9F',2)
        image=image.resize((self.width,self.height),Image.Resampling.LANCZOS)
        d=ImageDraw.Draw(image)
        d.text((240,53),'Tiresias',font=self.title,fill=self.ink,anchor='mm')
        d.text((240,600),'Here with you.',font=self.small,fill=self.ink,anchor='mm')
        return image

    def render(self, state: str, elapsed: float) -> Image.Image:
        image=self.base.copy()
        d=ImageDraw.Draw(image)
        state=state if state in self.labels else 'connecting'
        if self.artwork:
            master,loops=self.artwork
            frames=loops.get(state)
            frame=master
            if frames:
                position=(elapsed*1000)%sum(duration for _,duration in frames)
                for candidate,duration in frames:
                    if position<duration:
                        frame=candidate
                        break
                    position-=duration
            image.paste(frame,(40,100))
        else:
            self._face(d,state,elapsed)
        self._indicator(d,state,elapsed)
        return image

    def _face(self,d,state,elapsed):
        # Eyes blink slowly while listening; no strobing or fast scene motion.
        blink=state=='listening' and elapsed%5.5<0.16
        for x in (202,277):
            if blink:
                d.line((x-7,288,x+7,288),fill=self.ink,width=3)
            else:
                d.ellipse((x-4,283,x+4,292),fill=self.ink)
        if state=='speaking':
            opening=3+int(6*(0.5+0.5*math.sin(elapsed*15)))
            d.ellipse((227,345-opening/2,253,346+opening),fill=self.ink)
        else:
            d.arc((224,335,256,352),5,175,fill=self.ink,width=3)
        if state in ('thinking','connecting'):
            for i in range(3):
                angle=elapsed*1.2+i*math.tau/3
                x,y=240+174*math.cos(angle),285+174*math.sin(angle)
                d.ellipse((x-5,y-5,x+5,y+5),fill=self.teal)
        elif state=='listening':
            pulse=int(3*math.sin(elapsed*1.8))
            for offset in (0,12):
                d.arc((116-offset-pulse,251,161-offset-pulse,323),125,235,fill=self.teal,width=3)
                d.arc((319+offset+pulse,251,364+offset+pulse,323),-55,55,fill=self.teal,width=3)

    def _indicator(self,d,state,elapsed):
        d.text((240,521),self.labels[state],font=self.label,fill=self.ink,anchor='mm')
        if state=='speaking':
            for i in range(15):
                h=4+int(13*(0.5+0.5*math.sin(elapsed*8+i*1.3)))
                x=159+i*11
                d.rounded_rectangle((x,561-h/2,x+5,561+h/2),radius=2,fill=self.teal)
        elif state in ('thinking','connecting'):
            for i in range(3):
                r=3+int(2*(0.5+0.5*math.sin(elapsed*3-i)))
                x=220+i*20
                d.ellipse((x-r,559-r,x+r,559+r),fill=self.teal)
        else:
            d.line((220,559,260,559),fill=self.teal,width=3)

    def render_bytes(self, state: str, elapsed: float) -> bytes:
        return self.render(state,elapsed).tobytes()
