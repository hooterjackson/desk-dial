import json
import logging
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import standalone
from standalone import RetryPolicy, matching_port, fresh_controller, run_smoke_test, status_payload
from control_center.controller import Controller

def _tk_available():
    try:
        import tkinter as tk
        root=tk.Tk()
    except Exception:
        return False
    root.destroy()
    return True

class StandaloneTests(unittest.TestCase):
    def test_retry_waits_and_manual_pause_is_respected(self):
        p=RetryPolicy();self.assertTrue(p.can_attempt(0))
        p.inflight=True;self.assertFalse(p.can_attempt(100))
        p.failed(100);self.assertFalse(p.can_attempt(101));self.assertTrue(p.can_attempt(102))
        p.enabled=False;self.assertFalse(p.can_attempt(200))
        p.enabled=True
        for _ in range(20):p.failed(100)
        self.assertEqual(p.due,130)
        p.ready();self.assertEqual(p.attempts,0)

    def test_only_unique_expected_kit_is_selected(self):
        port=lambda name,vid,pid,serial:SimpleNamespace(device=name,vid=vid,pid=pid,serial_number=serial)
        kit=port('COM10',0x239a,0x8010,'Nano_D')
        self.assertEqual(matching_port([kit,port('COM3',1,2,'other')]),'COM10')
        self.assertIsNone(matching_port([kit,kit]))
        self.assertIsNone(matching_port([port('COM9',0x303a,0x1001,'bootloader')]))

    def test_reconnect_cannot_accept_old_results_or_replay_inputs(self):
        old=Controller();old.state.update(online=True,volume=50)
        old.turn(3);old.tick()
        previous_ids=set(old.pending)
        new=fresh_controller(old)
        self.assertGreater(new.control_id,old.control_id)
        self.assertIsNone(new.desired_volume)
        self.assertEqual(new.screen.mode,'home')  # v7 (K3): the volume screen is Home
        self.assertFalse(new.state['online'])
        request=new.request('state')
        self.assertNotIn(request,previous_ids)
        for stale in previous_ids:new.complete(stale,{'online':True,'volume':99})
        self.assertFalse(new.state['online'])


class StatusTests(unittest.TestCase):
    def app(self, connected):
        runtime=SimpleNamespace(device_connected=connected,device_status='Knob ready',led_style='white',
                                artwork_enabled=False,artwork_status={'state':'ready','key':'k','reason':'','message':'ok'},
                                apple=SimpleNamespace(credentials={'music_user_token':'secret'}))
        return SimpleNamespace(runtime=runtime,controller=Controller(),live=True)

    def test_status_reports_presentation_and_firmware(self):
        caps={'controlCenter':1,'presentation':4,'glyphs':'latin-ext-a',
              'artwork':{'version':1,'composited':'scrim80','width':120,'height':120}}
        status=status_payload(self.app(True),RetryPolicy(),{'exists':False},caps,Path('data'))
        self.assertEqual((status['ledStyle'],status['artwork']),('white',False))
        self.assertEqual(status['artworkStatus']['state'],'ready')
        self.assertEqual(status['firmwarePresentation'],4)
        self.assertEqual(status['firmware'],{'presentation':4,'controlCenter':1,'glyphs':'latin-ext-a','artwork':'scrim80'})
        self.assertTrue(status['musicAuthorized'])
        self.assertNotIn('secret',json.dumps(status))

    def test_status_without_a_connected_knob_has_no_firmware(self):
        status=status_payload(self.app(False),RetryPolicy(),{'exists':False},{'presentation':4},None)
        self.assertIsNone(status['firmwarePresentation'])
        self.assertIsNone(status['firmware'])
        self.assertIsNone(status['overlay'],'no floating knob on this app')
        json.dumps(status)

    def test_status_reports_the_floating_knob(self):
        app=self.app(True)
        app.overlay=SimpleNamespace(metrics=lambda:{'state':'hidden','dpi':96,'window_px':[434,434],
                                                    'lcd_px':302,'ulw_failures':0,'gdi_objects':4})
        app.overlay_submits=3
        status=status_payload(app,RetryPolicy(),{'exists':False},None,None)
        self.assertEqual(status['overlay']['state'],'hidden')
        self.assertEqual(status['overlay']['scenesSubmitted'],3)
        json.dumps(status)


@unittest.skipUnless(_tk_available(),'Tk is unavailable')
class SmokeTestTests(unittest.TestCase):
    def setUp(self):
        from control_center import ui
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.out=Path(temp.name)/'logs'
        patcher=patch.object(ui,'DATA_DIR',Path(temp.name)/'data');patcher.start();self.addCleanup(patcher.stop)

    def report(self):
        return json.loads((self.out/'smoke-test.json').read_text(encoding='utf-8'))

    def test_smoke_test_writes_enriched_results(self):
        # The overlay window check creates the knob's layered window hidden, never shown.
        self.assertEqual(run_smoke_test(self.out,ui_ms=150),0)
        report=self.report()
        self.assertTrue(report['passed'])
        self.assertEqual(report['pid'],os.getpid())
        self.assertEqual(report['executable'],sys.executable)
        self.assertIsInstance(report['timestamp'],float)
        self.assertIn('time',report)
        for name in ('art','lcd','icons','fontsPil','artwork2','overlay','overlayWindow','carouselRender',
                     'carouselWindow','fontsTk','imageTk','ui'):
            with self.subTest(check=name):
                self.assertTrue(report['checks'][name]['passed'],report['checks'][name])
        # The Windows carousel (CAROUSEL.md section 10): its windows hidden, never shown.
        carousel=report['checks']['carouselWindow']['detail']
        self.assertLessEqual(carousel['gdi'][1],carousel['gdi'][0],'GDI objects back to the baseline')
        self.assertLessEqual(carousel['user'][1],carousel['user'][0],'USER objects back to the baseline')
        windows=carousel['selfTest']['windows']   # carousel.self_test(hidden_windows=True)
        self.assertTrue(windows['thumbnail'],'one DWM thumbnail registered between hidden windows')
        self.assertTrue(windows['ulw'],'one composed chrome frame presented through the DIB path')
        self.assertTrue(windows['hidden'],'never shown')
        render=report['checks']['carouselRender']['detail']
        self.assertGreaterEqual(render['letterTile']['contrast'],3.0)
        self.assertEqual(set(render['label']),{'glass','none'})
        ui_detail=report['checks']['ui']['detail']
        self.assertGreaterEqual(ui_detail['lcdRenders'],1)
        self.assertGreaterEqual(ui_detail['scenes'],1,'the floating-knob UI handed scenes to the overlay')
        self.assertGreater(ui_detail['lcdPixels'],240)
        overlay=report['checks']['overlay']['detail']
        self.assertEqual((overlay['dpi100']['lcd'],overlay['dpi200']['lcd']),(302,604))
        self.assertEqual(overlay['hiresGlyphs'],72,'every button glyph at 16/20/26 px, @2x and @3x')
        self.assertTrue(report['checks']['appIcons']['detail']['appIconLoaded'])
        window=report['checks']['overlayWindow']['detail']
        self.assertLessEqual(window['gdi'][1],window['gdi'][0],'GDI objects back to the baseline')
        self.assertLessEqual(window['user'][1],window['user'][0],'USER objects back to the baseline')

    def test_smoke_test_fails_on_any_failed_check(self):
        missing=self.out.parent/'missing-art.rgb565'
        self.assertEqual(run_smoke_test(self.out,art_path=missing,ui=False),1)
        report=self.report()
        self.assertFalse(report['passed'])
        self.assertFalse(report['checks']['art']['passed'])
        self.assertFalse(report['checks']['lcd']['passed'])
        self.assertTrue(report['checks']['icons']['passed'])
        self.assertTrue(report['checks']['overlay']['passed'],report['checks']['overlay'])
        self.assertTrue(report['checks']['carouselRender']['passed'],report['checks']['carouselRender'])
        self.assertNotIn('ui',report['checks'])
        self.assertNotIn('overlayWindow',report['checks'],'no window without the UI checks')
        self.assertNotIn('carouselWindow',report['checks'],'no window without the UI checks')

    def test_smoke_test_fails_when_a_poll_stage_fails(self):
        # _poll_once swallows (and counts) a raising runtime.poll so the UI keeps
        # running; the smoke test must still report it.
        with patch('control_center.runtime.Runtime.poll',side_effect=RuntimeError('runtime broke')) as poll:
            self.assertEqual(run_smoke_test(self.out,ui_ms=150),1)
        self.assertGreater(poll.call_count,0)
        report=self.report()
        self.assertFalse(report['passed'])
        ui_check=report['checks']['ui']
        self.assertFalse(ui_check['passed'])
        self.assertIn("'runtime'",ui_check['error'])
        for name in ('art','lcd','icons','fontsPil','overlay','overlayWindow','carouselRender','carouselWindow',
                     'fontsTk','imageTk'):
            with self.subTest(check=name):
                self.assertTrue(report['checks'][name]['passed'],report['checks'][name])

class ListHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records=[]

    def emit(self,record):
        self.records.append(record)


def isolated_logger(test):
    logger=logging.getLogger(f'nanod.test.{id(test)}')
    handler=ListHandler()
    logger.addHandler(handler)
    logger.propagate=False
    logger.setLevel(logging.DEBUG)
    test.addCleanup(logger.removeHandler,handler)
    return logger,handler.records


class CrashLogTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.logs=Path(temp.name)

    def test_each_start_appends_a_header_with_time_and_pid(self):
        for _ in range(2):
            stream=standalone.open_crash_log(self.logs)
            self.assertIsNotNone(stream)
            stream.close()
        lines=(self.logs/'crash.log').read_text(encoding='utf-8').splitlines()
        self.assertEqual(len(lines),2)
        for line in lines:
            self.assertTrue(line.startswith('=== 20'),line)
            self.assertIn(f'pid={os.getpid()}',line)
            self.assertIn('exe=',line)

    def test_an_oversized_log_is_rotated_once(self):
        (self.logs/'crash.log').write_bytes(b'x'*50)
        with patch.object(standalone,'CRASH_LOG_LIMIT',10):
            standalone.open_crash_log(self.logs).close()
        self.assertEqual((self.logs/'crash.log.1').read_bytes(),b'x'*50)
        self.assertTrue((self.logs/'crash.log').read_text(encoding='utf-8').startswith('==='))

    def test_an_unwritable_log_is_not_fatal(self):
        blocked=self.logs/'blocked'
        blocked.write_text('a file, not a directory')
        self.assertIsNone(standalone.open_crash_log(blocked))
        with patch.object(standalone,'install_exception_hooks') as hooks, \
                patch.object(standalone.faulthandler,'enable') as enable:
            state=standalone.enable_crash_diagnostics(blocked)
        enable.assert_not_called()
        hooks.assert_called_once()
        self.assertEqual(state,{'crashLog':None,'faulthandler':False,'cStderr':False,'hooks':True})

    def test_failing_hooks_install_is_not_fatal(self):
        with patch.object(standalone,'install_exception_hooks',side_effect=RuntimeError('no')), \
                patch.object(standalone,'open_crash_log',return_value=None):
            self.assertFalse(standalone.enable_crash_diagnostics(self.logs)['hooks'])

    @unittest.skipIf(sys.stderr is None,'this runner has no stderr')
    def test_a_working_stderr_is_never_redirected(self):
        # The test runner's stderr is valid: without force nothing changes.
        self.assertFalse(standalone.redirect_c_stderr(self.logs/'crash.log'))
        self.assertFalse((self.logs/'crash.log').exists())


class ExceptionHookTests(unittest.TestCase):
    def setUp(self):
        self.logger,self.records=isolated_logger(self)
        saved=(sys.excepthook,threading.excepthook,sys.unraisablehook)
        def restore():
            sys.excepthook,threading.excepthook,sys.unraisablehook=saved
        self.addCleanup(restore)
        # Quiet previous hooks: the installed ones still chain to them.
        self.previous=Mock(),Mock(),Mock()
        sys.excepthook,threading.excepthook,sys.unraisablehook=self.previous
        self.restore=standalone.install_exception_hooks(self.logger)

    def test_uncaught_main_thread_exceptions_are_logged_and_chained(self):
        try:
            raise ValueError('main broke')
        except ValueError:
            sys.excepthook(*sys.exc_info())
        self.assertEqual(self.records[-1].levelno,logging.CRITICAL)
        self.assertIs(self.records[-1].exc_info[0],ValueError)
        self.previous[0].assert_called_once()

    def test_uncaught_thread_exceptions_are_logged_with_the_thread_name(self):
        def fail():
            raise KeyError('worker broke')
        thread=threading.Thread(target=fail,name='NanoD-test-worker')
        thread.start();thread.join()
        record=self.records[-1]
        self.assertEqual(record.levelno,logging.ERROR)
        self.assertIn('NanoD-test-worker',record.getMessage())
        self.assertIs(record.exc_info[0],KeyError)
        self.previous[1].assert_called_once()

    def test_system_exit_in_a_thread_is_not_an_error(self):
        thread=threading.Thread(target=lambda:sys.exit(0))
        thread.start();thread.join()
        self.assertEqual(self.records,[])

    def test_unraisable_exceptions_are_logged_at_a_limited_rate(self):
        class Finalizer:
            def __del__(self):
                raise RuntimeError('main thread is not in main loop')
        for _ in range(3):
            Finalizer()
        self.assertEqual(len(self.records),1,'one report per interval for one failure site')
        self.assertIn('Finalizer',self.records[0].getMessage())
        self.assertEqual(self.previous[2].call_count,3)

    def test_a_failing_logger_never_raises_or_recurses(self):
        broken=Mock()
        broken.critical.side_effect=OSError('disk full')
        broken.error.side_effect=OSError('disk full')
        self.restore()
        standalone.install_exception_hooks(broken)
        try:
            raise ValueError('x')
        except ValueError:
            sys.excepthook(*sys.exc_info())       # returns normally
        thread=threading.Thread(target=lambda:1/0)
        thread.start();thread.join()
        broken.critical.assert_called_once()
        broken.error.assert_called_once()

    def test_restore_puts_the_previous_hooks_back(self):
        self.restore()
        self.assertEqual((sys.excepthook,threading.excepthook,sys.unraisablehook),self.previous)


class CallbackReporterTests(unittest.TestCase):
    def failure(self,exc=ValueError):
        try:
            raise exc('tick failed')
        except Exception:
            return sys.exc_info()

    def test_a_repeating_failure_is_logged_once_per_interval_with_a_count(self):
        logger,records=isolated_logger(self)
        now=[0.0]
        reporter=standalone.CallbackErrorReporter(logger,interval=30,clock=lambda:now[0])
        error=self.failure()
        for moment in (0,1,2,31):
            now[0]=moment
            reporter(*error)
        self.assertEqual(len(records),2)
        self.assertIn('1 occurrence',records[0].getMessage())
        self.assertIn('3 occurrence',records[1].getMessage())
        self.assertIsNotNone(records[0].exc_info)
        reporter(*self.failure(KeyError))            # another failure is reported at once
        self.assertEqual(len(records),3)

    def test_the_reporter_never_raises(self):
        broken=Mock()
        broken.error.side_effect=OSError('disk full')
        standalone.CallbackErrorReporter(broken)(*self.failure())
        standalone.CallbackErrorReporter(broken)(None,None,None)


class PickerChromeWiringTests(unittest.TestCase):
    """CAROUSEL.md 12.4, WP7c-D11 (lead decision 2026-09-26): main installs the picker's GPU chrome once,
    right before ControlCenterApp builds the WindowsAdapter (and so its CarouselPresenter); a failing
    install leaves the CPU chrome and never stops the app. main itself runs in test_cc_tray.py
    (StartupCleanupTests, with a stand-in kernel32); here: its source, and what the install does to a
    presenter made after it. No Tk, no window, no device: the adapter runs on the adapter tests' fake
    root and native layer, and its presenter is the production CarouselPresenter inline on the headless
    backend."""

    def setUp(self):
        if str(ROOT/'tests') not in sys.path:sys.path.insert(0,str(ROOT/'tests'))
        from control_center import carousel
        self.carousel=carousel
        carousel.install_gpu_chrome(None)
        self.addCleanup(carousel.install_gpu_chrome,None)
        self.logger,self.records=isolated_logger(self)

    def adapter_factory(self,order,presenters):
        """What ControlCenterApp's live providers() builds for the picker: a WindowsAdapter whose
        PickerOverlay is the CarouselPresenter, which reads the installed factory when it is made."""
        import test_carousel_adapter as TA
        from control_center import windows as w
        from control_center.stage import picker_testing as PT
        carousel=self.carousel
        def picker(root,native,on_cancel):
            order.append('adapter')
            clock=PT.SharedClock()
            backend=PT.HeadlessBackend((0,0,2560,1440),(0,0,2560,1392))
            p=carousel.CarouselPresenter(root,native,on_cancel,backend=backend,capture=PT.NullCapture(),
                                         labels=PT.NoLabels(),clock=clock,inline=True,environ={})
            presenters.append((p,backend,clock))
            return p
        for patcher in (patch.object(w,'NativeWindows',lambda:TA.FakeNative([])),patch.object(w,'PickerOverlay',picker),
                        patch.object(w,'_window_labels',lambda:TA.LABELS)):
            patcher.start();self.addCleanup(patcher.stop)
        def make():
            adapter=w.WindowsAdapter(TA.FakeRoot(),lambda:None,lambda:None,lambda:None)
            self.addCleanup(adapter.close)
            return adapter
        return make

    def test_main_installs_once_right_before_the_app(self):
        """The one install_picker_chrome() call of main comes right before ControlCenterApp(live=True,
        chrome=False), whose runtime builds the WindowsAdapter; nothing else in this file installs or
        names the chrome."""
        import ast
        tree=ast.parse((ROOT/'standalone.py').read_text(encoding='utf-8'))
        funcs={node.name:node for node in tree.body if isinstance(node,ast.FunctionDef)}
        def names(node):
            out=[]
            for c in ast.walk(node):
                if isinstance(c,ast.Call):
                    out.append(getattr(c.func,'id',None) or getattr(c.func,'attr',None))
            return out
        main=names(funcs['main'])
        self.assertEqual(main.count('install_picker_chrome'),1)
        after=main[main.index('install_picker_chrome')+1]
        self.assertEqual(after,'ControlCenterApp')
        app=[c for c in ast.walk(funcs['main']) if isinstance(c,ast.Call) and getattr(c.func,'id',None)=='ControlCenterApp'
             and any(k.arg=='chrome' for k in c.keywords)]
        self.assertEqual(len(app),1)
        self.assertEqual({k.arg:ast.unparse(k.value) for k in app[0].keywords if k.arg in ('live','chrome')},
                         {'live':'True','chrome':'False'})
        self.assertLess(main.index('start_stage'),main.index('install_picker_chrome'))
        self.assertEqual([n for n,f in funcs.items() if n!='main' and 'install_picker_chrome' in names(f)],[])
        self.assertEqual([n for n,f in funcs.items() if 'picker_chrome.' in ast.unparse(f)
                          or 'import picker_chrome' in ast.unparse(f)],['install_picker_chrome'])

    def test_a_presenter_made_after_the_install_takes_the_gpu_chrome(self):
        from control_center.stage import picker_chrome as PC
        order,presenters=[],[]
        make=self.adapter_factory(order,presenters)
        make()                                               # before the install: the CPU chrome for its life
        real=PC.install
        def counted():
            order.append('install')
            return real()
        with patch.object(PC,'install',counted):
            self.assertTrue(standalone.install_picker_chrome(log=self.logger))
        adapter=make()
        self.assertEqual(order,['adapter','install','adapter'])
        self.assertIs(self.carousel.gpu_chrome_factory(),PC.factory)
        self.assertIsNone(presenters[0][0]._gpu,'a presenter made before the install keeps the CPU chrome')
        presenter=presenters[1][0]
        self.assertIs(adapter.overlay,presenter)
        self.assertIsInstance(presenter._gpu,PC.PickerChrome,'the presenter took the installed factory')
        self.assertIsNone(presenter._gpu.dev,'nothing of the device is made at startup')
        self.assertFalse(presenter._gpu.warming)
        self.assertEqual([r.levelno for r in self.records],[logging.INFO])

    def test_a_failing_install_falls_back_to_the_cpu_chrome_without_crashing(self):
        from control_center.stage import picker_chrome as PC
        from control_center.stage import picker_testing as PT
        def raising():
            raise OSError('no DirectComposition here')
        def half_way():
            self.carousel.install_gpu_chrome(PC.factory)
            raise RuntimeError('failed after registering')
        for install in (raising,half_way,lambda:False):
            with self.subTest(install=getattr(install,'__name__','')):
                self.records.clear()
                self.assertFalse(standalone.install_picker_chrome(install=install,log=self.logger))
                self.assertIsNone(self.carousel.gpu_chrome_factory(),'the CPU chrome: no factory left')
                self.assertEqual([r.levelno for r in self.records],[logging.WARNING])
                self.assertIn('CPU chrome',self.records[0].getMessage())
        # the real path with picker_chrome.install() raising: the adapter made next has no GPU chrome,
        # a knob touch warms nothing, and an open draws the CPU chrome
        order,presenters=[],[]
        make=self.adapter_factory(order,presenters)
        self.records.clear()
        with patch.object(PC,'install',raising):
            self.assertFalse(standalone.install_picker_chrome(log=self.logger))
        adapter=make()
        self.assertEqual([r.levelno for r in self.records],[logging.WARNING])
        presenter,backend,clock=presenters[0]
        self.assertIsNone(presenter._gpu)
        self.assertFalse(adapter.note_touch(),'a knob touch warms nothing')
        presenter.show(PT.snapshot(6,2))
        backend.activate()
        end=clock.t+self.carousel.CAPTURE_TIMEOUT_S+0.3
        while clock.t<end:
            alive,wait=presenter._iterate()
            if alive and wait is not None and wait<=0:presenter._engine.present()
            clock.advance(1/240)
        self.assertEqual(presenter.chrome,'cpu')

    def test_an_import_failure_is_a_failed_install_too(self):
        """A bundle without the stage package (or a DLL that cannot load at import) leaves the CPU
        chrome: the import sits inside the guarded block."""
        import control_center.stage as stage_pkg
        saved=stage_pkg.__dict__.pop('picker_chrome',None)
        def restore():
            if saved is not None:stage_pkg.picker_chrome=saved
        self.addCleanup(restore)
        with patch.dict(sys.modules,{'control_center.stage.picker_chrome':None}):
            self.assertFalse(standalone.install_picker_chrome(log=self.logger))
        self.assertIsNone(self.carousel.gpu_chrome_factory())
        self.assertEqual([r.levelno for r in self.records],[logging.WARNING])


PYTHONW=Path(sys.executable).with_name('pythonw.exe')
CRASH_CHILD=r"""
import ctypes, json, sys
ctypes.CDLL('ucrtbase')._set_abort_behavior(0, 3)   # abort(): quiet _exit(3), no WER report
ctypes.windll.kernel32.SetErrorMode(0x8003)
sys.path.insert(0, sys.argv[1])
import standalone
logs, mode = sys.argv[2], sys.argv[3]
state = standalone.enable_crash_diagnostics(logs)
with open(logs + '/state.json', 'w') as out:
    json.dump({'state': state, 'stderr': repr(sys.stderr)}, out)
if mode == 'fatal':
    ctypes.pythonapi.Py_FatalError(b'nanod crash-diagnostics probe')
else:
    import faulthandler
    faulthandler._sigabrt()
"""


@unittest.skipUnless(sys.platform=='win32' and PYTHONW.exists(),'windowed pythonw.exe unavailable')
class WindowedCrashCaptureTests(unittest.TestCase):
    """A windowed interpreter (no stderr, like the frozen build) that aborts: the
    crash log gets the header and the fatal-error text or faulthandler dump."""
    def run_child(self,mode):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        logs=Path(temp.name)
        script=logs/'child.py'
        script.write_text(CRASH_CHILD,encoding='utf-8')
        # No standard handles at all, as for the frozen --windowed build.
        startup=subprocess.STARTUPINFO()
        startup.dwFlags|=subprocess.STARTF_USESTDHANDLES
        startup.hStdInput=startup.hStdOutput=startup.hStdError=0
        child=subprocess.run([str(PYTHONW),str(script),str(ROOT),str(logs),mode],timeout=120,
                             startupinfo=startup)
        state=json.loads((logs/'state.json').read_text())
        return child.returncode,state,(logs/'crash.log').read_text(encoding='utf-8',errors='replace')

    def test_a_fatal_python_error_reaches_the_crash_log(self):
        code,state,log=self.run_child('fatal')
        self.assertEqual(code,3,log)
        self.assertEqual(state['stderr'],'None','windowed: Python has no stderr')
        self.assertTrue(state['state']['faulthandler'] and state['state']['cStderr'],state)
        self.assertIn(f'pid=',log)
        self.assertIn('Fatal Python error',log)
        self.assertIn('nanod crash-diagnostics probe',log)
        self.assertIn('child.py',log,'the Python traceback of the failing thread')

    def test_an_abort_is_dumped_by_faulthandler(self):
        code,state,log=self.run_child('abort')
        self.assertEqual(code,3,log)
        self.assertIn('Fatal Python error: Aborted',log)
        self.assertIn('child.py',log)


if __name__=='__main__':unittest.main()
