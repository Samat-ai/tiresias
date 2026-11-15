"""One bounded speech result, delivered before optional trailing metadata."""
from __future__ import annotations

import asyncio
import logging
import threading

from tiresias.contracts import GroundedReply

logger=logging.getLogger(__name__)


class SpeechFirstParser:
    def __init__(self,*,frame_id):
        self.frame_id=frame_id
        self.buffer=''
        self.reply=None

    def _validate(self,text):
        text=' '.join(text.strip().split())
        if not text or len(text)>400 or any(char in text for char in '{}[]|') or '```' in text:
            raise ValueError('invalid speech-first answer')
        return GroundedReply(text=text,frame_id=self.frame_id)

    def feed(self,text):
        if self.reply is not None:
            return None
        self.buffer+=text
        if '|||' in self.buffer:
            spoken=self.buffer.split('|||',1)[0]
            self.reply=self._validate(spoken)
            self.buffer=''
            return self.reply
        if len(self.buffer)>403:
            raise ValueError('speech-first answer too long')
        return None

    def finish(self):
        if self.reply is not None:
            return self.reply
        if not self.buffer.rstrip().endswith(('.','!','?','…','。','！','？')):
            raise ValueError('incomplete delimiter-free vision answer')
        return self._validate(self.buffer)


async def speech_first_replies(generate,*,frame_id,timeout):
    """Bridge blocking SDK streaming without sharing async clients across jobs.

    Only one result crosses threads. Cancelled requests cannot set a late result;
    provider failures after speech readiness do not create a contradictory reply.
    """
    loop=asyncio.get_running_loop()
    ready=loop.create_future()
    stop=threading.Event()
    state={'reply':None}

    def deliver(reply):
        if not stop.is_set() and not ready.done():
            ready.set_result(reply)

    def produce():
        parser=SpeechFirstParser(frame_id=frame_id)
        stream=generate()
        total=0
        try:
            for chunk in stream:
                if stop.is_set():
                    return None
                text=chunk.text or ''
                for candidate in getattr(chunk,'candidates',None) or []:
                    reason=getattr(candidate,'finish_reason',None)
                    reason=getattr(reason,'value',reason)
                    if reason and reason not in {'STOP','FINISH_REASON_UNSPECIFIED'}:
                        if reason!='MAX_TOKENS' or (parser.reply is None and '|||' not in parser.buffer+text):
                            raise ValueError('vision stream did not finish a complete answer')
                total+=len(text)
                if total>4096:
                    raise ValueError('vision stream exceeded response bound')
                reply=parser.feed(text)
                if reply is not None:
                    state['reply']=reply
                    if not stop.is_set():
                        loop.call_soon_threadsafe(deliver,reply)
            return None if stop.is_set() else parser.finish()
        finally:
            if close:=getattr(stream,'close',None):
                close()

    task=asyncio.create_task(asyncio.to_thread(produce))
    try:
        done,_=await asyncio.wait({ready,task},timeout=timeout,return_when=asyncio.FIRST_COMPLETED)
        if not done:
            raise TimeoutError('vision speech deadline exceeded')
        if ready.done() and not ready.cancelled():
            reply=ready.result()
        elif state['reply'] is not None:
            reply=state['reply']
        else:
            reply=task.result()
        if reply is None:
            raise ValueError('empty vision speech response')
        yield reply
        try:
            await asyncio.wait_for(asyncio.shield(task),2)
        except Exception as error:
            logger.warning('Vision metadata tail unavailable: %s',type(error).__name__)
    finally:
        stop.set()
        if not ready.done():
            ready.cancel()
        if not task.done():
            task.cancel()
        await asyncio.gather(task,return_exceptions=True)
