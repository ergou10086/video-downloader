"""Durable author archives composed from the pure P1 scan and IO adapters."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import copy
from pathlib import Path
import threading
import time
import uuid

from .auth import load_credentials
from .binary import BinaryTransport
from .cli import credential_scope, proxy_from_config
from .client import FanboxClient
from .downloader import Downloader
from .errors import FanboxError
from .exporters import export_post
from .models import Post
from .naming import confined
from .options import normalize_options
from .parsers import parse_post
from .repository import Repository
from .scheduling import AccountGate
from .service import ScanService, write_json
from .transport import CurlTransport, HttpTransport
from .urls import parse_source

_PAUSES={'cancelled','quota_exceeded','quota_busy','rate_limited','challenge_required','access_denied','fallback_required','conflict_required'}


def summary(state):
    return {key:copy.deepcopy(state.get(key)) for key in
            ('id','source','status','version','created_at','updated_at','counts','error','scope','output','phase','outcome','resume_after')}


class ArchiveApplication:
    def __init__(self, root, *, repository=None, transport_factory=None,binary_factory=None,publish=None):
        self.root=Path(root)
        self._repository=repository
        self._repository_lock=threading.Lock()
        self.transport_factory=transport_factory
        self.binary_factory=binary_factory or BinaryTransport
        self.publish=publish or (lambda event:None)

    @property
    def repository(self):
        # An unavailable optional archive must not prevent other platforms or
        # the application's configuration UI from starting.
        with self._repository_lock:
            if self._repository is None:
                self._repository=Repository(confined(self.root,'.fanbox/library.sqlite',create=True))
            return self._repository

    def create(self,url,options=None):
        source=parse_source(url)
        state={'id':uuid.uuid4().hex,'source':source.url,'options':normalize_options(options),
               'created_at':time.time(),'task_date':datetime.now(timezone.utc).isoformat(),
               'status':'queued','phase':'queued','counts':{},'files':{},'archives':[],
               'checkpoint':None,'scan':None,'auth_scope':None,'selection':{},'error':None,
               'scope':{},'output':'','outcome':'','resume_after':None}
        self.repository.save_job(state)
        return state

    def run(self,job_id,*,credentials=None,config=None,cancel=None,preview=False,selection=None,on_update=None):
        state=self.repository.job(job_id)
        if state is None:
            raise FanboxError('job_not_found','归档任务不存在')
        cancel=cancel or threading.Event()
        config=config or {}
        credentials=credentials or load_credentials()
        options=normalize_options(state['options'])
        gate=AccountGate(self.repository,cancel,options['network']['api_interval_seconds'])
        job_token,_=self.repository.acquire('job:'+job_id)
        if job_token is None:
            raise FanboxError('job_busy','归档任务仍在运行或等待崩溃租约释放')
        lock=threading.RLock()
        received={}
        last_progress=[0.]

        def save():
            self.repository.heartbeat(job_token)
            self.repository.save_job(state)
            event={'type':'fanbox_job','data':summary(state)}
            try:
                self.publish(event)
                if on_update:on_update(event['data'])
            except Exception:
                pass

        def stats():
            posts=state['scan']['posts'] if state['scan'] else []
            results=[record for files in state['files'].values() for record in files.values()]
            state['counts']={'posts':len(posts),'restricted':sum(p['access']=='restricted' for p in posts),
                'completed':sum(r['status']=='completed' for r in results),
                'reused':sum(r['status']=='reused' for r in results),
                'failed':sum(r['status']=='failed' for r in results),
                'degraded':sum(r['status']=='degraded' for r in results),
                'skipped':sum(r['status']=='skipped' for r in results),
                'bytes_received':sum(received.values()),'links':sum(len(p['links']) for p in posts)}

        def progress(**data):
            with lock:
                received[data['key']]=received.get(data['key'],0)+data['delta']
                if time.monotonic()-last_progress[0]>.5:
                    stats();save();last_progress[0]=time.monotonic()

        try:
            scope=credential_scope(credentials)
            if state['auth_scope'] not in (None,scope):
                raise FanboxError('credentials_changed','登录快照已改变，请创建新抓取任务')
            state['auth_scope']=scope
            state['error']=None
            state['resume_after']=None
            state['status']='running'
            state['phase']='scanning'
            save()
            proxy=proxy_from_config(config,options)
            factory=self.transport_factory or (CurlTransport if options['network']['engine']=='curl' else HttpTransport)
            with factory(credentials,proxy=proxy,gate=gate) as transport:
                client=FanboxClient(transport)
                if state['scan'] is None or (state['scan']['status']!='completed' and not preview):
                    def checkpoint(value):
                        state['checkpoint']=value
                        save()
                    result=ScanService(client).scan(state['source'],options,
                        checkpoint=state['checkpoint'],save_checkpoint=checkpoint,auth_scope=scope)
                    state['scan']={key:value for key,value in result.items() if key!='checkpoint'}
                    state['checkpoint']=result['checkpoint']
                    state['scope']=result['coverage']
                    stats()
                    if result['errors']:
                        error=result['errors'][0]
                        if error['code'] in _PAUSES:
                            raise FanboxError(error['code'],error['message'],retry_after=error.get('retry_after'))
                if preview:
                    state['status']='preview_ready'
                    state['phase']='preview'
                    stats();save()
                    return summary(state)
                if selection is not None:
                    state['selection']=copy.deepcopy(selection)
                state['phase']='downloading'
                save()
                selected=state['selection'].get('post_ids')
                chosen_assets=state['selection'].get('asset_ids')
                binary=self.binary_factory(credentials,proxy=proxy,
                    speed=int(float(config.get('SPEED_LIMIT',0))*1024*1024/options['network']['file_concurrency']))
                downloader=Downloader(self.root,self.repository,gate,binary,progress=progress)
                state['archives']=[]
                for value in state['scan']['posts']:
                    gate.check()
                    post=Post.from_dict(value)
                    if selected is not None and post.id not in selected:
                        continue
                    results=state['files'].setdefault(post.id,{})

                    def one(asset):
                        gate.check()
                        def refresh():
                            updated=parse_post(client.post(post.id,post.creator_id),options)
                            return next((a for a in updated.assets if a.id==asset.id and a.variant==asset.variant and a.kind==asset.kind),None)
                        try:
                            result=downloader.download(post,asset,options,state['task_date'],refresh=refresh)
                        except FanboxError as error:
                            if error.code in _PAUSES:
                                cancel.set()
                                raise
                            result={'status':'failed','error':error.to_dict()}
                        with lock:
                            results[asset.id+':'+asset.variant]=result
                            stats();save()

                    assets=[a for a in post.assets if a.selected and
                            (chosen_assets is None or post.id+':'+a.id+':'+a.variant in chosen_assets)]
                    if post.access!='restricted':
                        with ThreadPoolExecutor(max_workers=options['network']['file_concurrency']) as workers:
                            futures=[workers.submit(one,asset) for asset in assets]
                            errors=[]
                            for future in as_completed(futures):
                                try:future.result()
                                except FanboxError as error:errors.append(error)
                            if errors:
                                raise next((e for e in errors if e.code!='cancelled'),errors[0])
                    entry=export_post(self.root,self.repository,post,options,state['task_date'],results)
                    state['archives'].append(entry)
                    stats();save()
                stats()
                counts=state['counts']
                partial=(counts['failed'] or counts['degraded'] or counts['restricted']
                         or state['scan']['status']!='completed')
                state['status']='partial' if partial else 'completed'
                if counts['failed'] and not (counts['completed'] or counts['reused'] or
                        options['content']['body'] and any(p['blocks'] for p in state['scan']['posts'])):
                    state['status']='failed'
                state['outcome']='empty' if not state['archives'] else 'restricted' if counts['restricted']==counts['posts'] else state['status']
                state['phase']='finished'
                state['output']=state['archives'][0]['index'] if state['archives'] else ''
                manifest={'schema_version':1,'source':state['source'],'status':state['status'],
                          'coverage':state['scope'],'counts':counts,'posts':state['archives'],'files':state['files']}
                write_json(confined(self.root,f'.fanbox/manifests/{state["id"]}.json',create=True),manifest)
                save()
        except FanboxError as error:
            state['status']='paused' if error.code in _PAUSES else 'failed'
            state['phase']='paused' if state['status']=='paused' else 'finished'
            state['error']=error.to_dict()
            if error.code=='quota_exceeded' and options['quota']['on_limit']=='next_day':
                state['resume_after']=self.repository._day(self.repository.clock(),options['quota']['timezone'])[1]*60
            stats();save()
        except KeyboardInterrupt:
            state['status']='paused';state['phase']='paused'
            state['error']={'code':'cancelled','message':'任务已暂停','retry_after':None}
            stats();save()
            raise
        except (OSError,ValueError,TypeError) as error:
            state['status']='failed';state['phase']='finished'
            state['error']={'code':'archive_error','message':'归档写入或响应处理失败','retry_after':None}
            stats();save()
        finally:
            self.repository.release(job_token)
        return summary(state)
