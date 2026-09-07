import os

block_cipher = None

EXCLUDES = [
    'requests', 'urllib3', 'certifi', 'charset_normalizer', 'idna',
    'cryptography', '_cffi_backend', 'ssl', '_ssl', 'http', 'email',
    'socket', '_socket', 'select', 'netrc', 'ftplib', 'mimetypes',
    # qtnetwork is not excluded: pyqt5.qtmultimedia imports it, and both its
    # .pyd and qt5multimedia.dll link against it.
    'PyQt5.QtQuick', 'PyQt5.QtQml', 'PyQt5.QtDBus',
    'PyQt5.QtWebSockets', 'PyQt5.QtSvg', 'PyQt5.QtTest', 'PyQt5.QtSql',
    'PyQt5.QtPrintSupport', 'PyQt5.QtOpenGL',
    # qtmultimedia is required - the output preview plays the audio.
    # zipfile and logging must not be excluded - pyinstaller's own
    # pyi_rth_inspect runtime hook imports them.
    'decimal', '_decimal', 'bz2', '_bz2', 'lzma', '_lzma',
    'tarfile', 'csv', 'argparse', 'pydoc',
    'unittest', 'doctest', 'pdb', 'difflib', 'tracemalloc',
    'multiprocessing', 'asyncio', 'concurrent', 'xml', 'sqlite3',
    'tkinter', 'PIL', 'numpy',
    '_hashlib',
]

# the worker needs numpy/onnxruntime/pyav to run the pipeline and
# ssl+socket+http to fetch the models on first use. none of that comes back
# for the main exe. pyqt5 is excluded outright here rather than merely
# unimported: the whole point of this second analysis is the ABSENCE of qt
# (qt loaded before onnxruntime breaks ort's dll init), so assert it.
# decimal is not optional here: pyav imports fractions at module load and
# fractions imports decimal at the top. csv comes back for
# importlib.metadata, which onnxruntime reaches through.
WORKER_KEEP = {'ssl', '_ssl', 'http', 'email', 'socket', '_socket', 'select',
               'mimetypes', 'numpy', 'decimal', '_decimal', 'csv'}
WORKER_EXCLUDES = [name for name in EXCLUDES if name not in WORKER_KEEP]
WORKER_EXCLUDES += ['PyQt5', 'PyQt5.sip', 'PyQt5.QtCore', 'PyQt5.QtWidgets',
                    'PyQt5.QtGui', 'PyQt5.QtMultimedia']

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('setting.ini', '.'), ('rdyd.ico', '.'), ('rdyd.png', '.'),
           ('questionmark.opus', '.')],
    hiddenimports=['chardet'],
    hookspath=[],
    runtime_hooks=[],
    excludes=EXCLUDES,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# the auto-sync worker is its own executable, not a flag on the main one.
# pyinstaller's own runtime hook for pyqt5 does
# importlib.import_module('PyQt5.QtCore') unconditionally at frozen startup
# (_pyi_rth_utils/qt.py, create_embedded_qt_conf), before any entry-script
# code runs, so sharing the main exe can never keep qt out of this process -
# confirmed empirically, not a guess. see worker/run.py.
w = Analysis(
    ['worker_entry.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['numpy', 'onnxruntime', 'av'],
    hookspath=[],
    runtime_hooks=[],
    excludes=WORKER_EXCLUDES,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# qt5network.dll must not be dropped - qt5multimedia.dll links against it, and
# the output preview needs qtmultimedia.
DROP_BINARIES = {
    'opengl32sw.dll',
    'd3dcompiler_47.dll',
    'libGLESv2.dll',
    'libEGL.dll',
    'Qt5Quick.dll',
    'Qt5Qml.dll',
    'Qt5QmlModels.dll',
    'Qt5DBus.dll',
    'Qt5WebSockets.dll',
    'Qt5Svg.dll',
    'libcrypto-3.dll',
}


# libcrypto-3.dll cannot be dropped from the worker: _ssl.pyd and
# libssl-3.dll both link against it, and the worker fetches its models
# over https. dropping it produced a silent 'could not download' with
# no traceback, because the import failure happened inside the fetch.
WORKER_DROP = DROP_BINARIES - {'libcrypto-3.dll'}


def _keep(entry, drop):
    name = entry[0].split('/')[-1].split('\\')[-1]
    if name in drop:
        return False
    if 'translations' in entry[0].replace('\\', '/'):
        return False
    return True


a.binaries = TOC([e for e in a.binaries if _keep(e, DROP_BINARIES)])
a.datas = TOC([e for e in a.datas if _keep(e, DROP_BINARIES)])
w.binaries = TOC([e for e in w.binaries if _keep(e, WORKER_DROP)])
w.datas = TOC([e for e in w.datas if _keep(e, WORKER_DROP)])

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
wpyz = PYZ(w.pure, w.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='intro no jutsu',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon='rdyd.ico',
)

# console=True: it only ever talks over stdout/exit code, and a console
# subsystem sidesteps the "sys.stdout may not exist" gotchas of --windowed.
wexe = EXE(
    wpyz,
    w.scripts,
    [],
    exclude_binaries=True,
    name='inj-worker',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    # the worker exe is collected into _internal (below), so its dependencies
    # sit beside it rather than one level down. '.' drops the
    # pyi-contents-directory option from the exe and the bootloader then looks
    # in its own directory. leave it out and the worker looks for
    # _internal/_internal and dies before it can report anything.
    contents_directory='.',
)

# collect the worker as a data entry rather than passing it to COLLECT as an
# EXE. COLLECT always writes EXECUTABLE entries to the top level, so as an EXE
# it lands beside the app where users trip over it; as data it goes into
# _internal with everything else. COLLECT also takes its own contents
# directory from the FIRST exe it is handed, so the app has to stay first.
assert os.path.exists(wexe.name), wexe.name
WORKER_EXE = [('inj-worker.exe', wexe.name, 'DATA')]

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    WORKER_EXE,
    w.binaries,
    w.zipfiles,
    w.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='intro no jutsu',
)
