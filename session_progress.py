"""One live Telegram progress card; only fixed labels leave this module."""
import asyncio
import logging
import time
from telegram.error import RetryAfter
import i18n

log = logging.getLogger(__name__)
STAGES = i18n.T['progress_stages']['en']        # kept for backward compatibility

class SessionProgress:
    def __init__(self, message, remote, lang='en'):
        self.message, self.remote = message, remote
        self.lang = lang
        self.started = time.monotonic()
        self.stage = 0
        self.changed = self.started
        self.finished = False
        self.task = None

    def report(self, text):
        # Raw callback content can include account identifiers; never render it.
        stage = None
        if 'Step 1/6' in text or 'Step 2/6' in text: stage = 1
        elif 'Step 3/6' in text: stage = 2
        elif 'Step 4' in text: stage = 3
        elif 'Step 5/6' in text or 'Opening the Google AI Pro offer' in text: stage = 4
        elif 'Annual billing selected' in text or 'Clicked Get Google AI Pro' in text or 'card' in text.lower(): stage = 5
        if not self.finished and stage is not None and stage > self.stage:
            log.info('Preparation stage %d took %.1fs', self.stage+1, time.monotonic()-self.changed)
            self.changed = time.monotonic()
            self.stage = stage

    def render(self, outcome=None):
        elapsed = int(time.monotonic()-self.started)
        title = {'ready':i18n.t('progress_title_ready',self.lang), 'failed':i18n.t('progress_title_failed',self.lang),
                 'cancelled':i18n.t('progress_title_cancelled',self.lang)}.get(outcome, i18n.t('progress_title_preparing',self.lang))
        stages = i18n.T['progress_stages'].get(self.lang, i18n.T['progress_stages']['en'])
        lines=[title, '', i18n.t('progress_elapsed',self.lang,t=f'{elapsed//60:02d}:{elapsed%60:02d}'),
               i18n.t('progress_stage_of',self.lang,n=6 if outcome=="ready" else self.stage+1), '']
        for i, label in enumerate(stages):
            marker = '✅' if outcome=='ready' or i<self.stage else '⏳' if i==self.stage else '▫️'
            lines.append(f'{marker} {i+1}. {label}')
        if not outcome:
            lines += ['', i18n.t('progress_footer',self.lang)]
            if time.monotonic()-self.changed>20:
                lines.append(i18n.t('progress_waiting',self.lang))
        return '\n'.join(lines)

    async def _edit(self, outcome=None):
        try:
            await self.message.edit_text(self.render(outcome))
        except RetryAfter as exc:
            delay=exc.retry_after
            await asyncio.sleep(min(30, delay.total_seconds() if hasattr(delay,'total_seconds') else float(delay)))
        except Exception:
            log.debug('Progress display update unavailable', exc_info=True)

    async def run(self):
        while not self.finished:
            if self.remote and self.remote.closed:
                await self._edit('cancelled' if getattr(self.remote,'cancelled',False) else 'failed')
                return
            await self._edit()
            await asyncio.sleep(3)

    def start(self):
        self.task=asyncio.create_task(self.run())

    async def finish(self, outcome):
        self.finished=True
        if self.task:
            self.task.cancel()
            try: await self.task
            except asyncio.CancelledError: pass
        await self._edit(outcome)
