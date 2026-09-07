import os
import shutil
import sys


def _source_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource_dir():
    if getattr(sys, 'frozen', False):
        return getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    return _source_root()


def app_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return _source_root()


def settings_path():
    path = os.path.join(app_dir(), 'setting.ini')
    if not os.path.exists(path):
        bundled = os.path.join(resource_dir(), 'setting.ini')
        if os.path.exists(bundled) and os.path.abspath(bundled) != os.path.abspath(path):
            try:
                shutil.copyfile(bundled, path)
            except OSError:
                return bundled
    return path
