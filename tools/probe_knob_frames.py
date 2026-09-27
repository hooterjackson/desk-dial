from pathlib import Path
import sys,json,time,queue
app=Path(__file__).resolve().parents[1]/'app'
sys.path.insert(0,str(app))
from control_center.device import DeviceBridge
from control_center.controller import Controller
report={'events':[],'firmwareErrors':[]}
bridge=DeviceBridge(app/'backups')
if '--paced' in sys.argv:
    def paced_write(message):
        data=(json.dumps(message,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n').encode('utf-8')
        for start in range(0,len(data),64):
            part=data[start:start+64]
            if bridge.serial.write(part)!=len(part):raise OSError('Incomplete write')
            if start+64<len(data):time.sleep(.005)
    bridge._write=paced_write
    report['paced']=True
consume=bridge._consume
def inspect(message):
    if 'error' in message:
        allowed={'JSON parse error','Command too large','Invalid control frame','Stale control frame',
                 'Control ID must advance; wait for release before reconnecting'}
        code=message['error']
        entry={'code':code if isinstance(code,str) and code in allowed else 'Other firmware error',
               'detail':message.get('msg') if message.get('msg') in ('InvalidInput','IncompleteInput','NoMemory','EmptyInput','TooDeep') else None}
        report['firmwareErrors'].append(entry);print(entry,flush=True)
    consume(message)
bridge._consume=inspect
def wait(kind):
    end=time.monotonic()+20
    while time.monotonic()<end:
        e=bridge.events.get(timeout=3)
        report['events'].append(e['kind'])
        if e['kind']=='error': raise RuntimeError(e['message'])
        if e['kind']==kind:return e
    raise TimeoutError(kind)
try:
    bridge.submit('connect','COM8');wait('connected')
    c=Controller();c.state.update(online=True,volume=66,title='Connection test',artist='Display updates only')
    c.windows_hid_enabled=False
    bridge.submit('enter',c.control());wait('ready')
    for i in range(300):
        f=c.frame();f.update(id=c.control_id,value=f'{i%101}%',status='Testing display traffic',activity='pending')
        bridge.submit('frame',f)
        time.sleep(.05)
        while not bridge.events.empty():
            e=bridge.events.get_nowait();report['events'].append(e['kind'])
            if e['kind'] in ('error','disconnected','released'):raise RuntimeError(str(e))
    deadline=time.monotonic()+20
    while not bridge.commands.empty() and time.monotonic()<deadline:
        time.sleep(.1)
        while not bridge.events.empty():
            e=bridge.events.get_nowait();report['events'].append(e['kind'])
            if e['kind'] in ('error','disconnected','released'):raise RuntimeError(str(e))
    assert bridge.commands.empty(),'Backlog did not drain'
    time.sleep(1)
    assert bridge.ready_id is not None and bridge.serial is not None
    report['passed']=True
except Exception as e:
    report['failure']=str(e);print(str(e),flush=True)
finally:
    bridge.submit('close');bridge._thread.join(timeout=5)
    (app/('diagnostics/frame-traffic-paced.json' if '--paced' in sys.argv else 'diagnostics/frame-traffic-probe.json')).write_text(json.dumps(report,indent=2))
    print(json.dumps(report),flush=True)
