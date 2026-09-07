"""where the auto-sync models live on disk and what they must hash to."""

import os

CTC_VOCAB = {
    '<pad>': 0, '<s>': 1, '</s>': 2, '<unk>': 3, '|': 4,
    'E': 5, 'T': 6, 'A': 7, 'O': 8, 'N': 9, 'I': 10, 'H': 11, 'S': 12,
    'R': 13, 'D': 14, 'L': 15, 'U': 16, 'M': 17, 'W': 18, 'C': 19, 'F': 20,
    'G': 21, 'Y': 22, 'P': 23, 'B': 24, 'V': 25, 'K': 26, "'": 27, 'X': 28,
    'J': 29, 'Q': 30, 'Z': 31,
}

BLANK = CTC_VOCAB['<pad>']
SEPARATOR = CTC_VOCAB['|']
VOCAB_SIZE = 32

MODELS = {
    'w2v2': {
        'name': 'wav2vec2-base-960h-fp16.onnx',
        'size': 189192204,
        'sha256': '378348ee38b739cc77e77e3fb8502f0f40ed53da0dbf7401b24c25c8fafe03de',
        'urls': (
            'https://huggingface.co/Xenova/wav2vec2-base-960h/resolve/'
            'a19f851b3d42865797e410752b4c570c871e4825/onnx/model_fp16.onnx',
        ),
    },
    'mdx': {
        'name': 'UVR-MDX-NET-Voc_FT.onnx',
        'size': 66762490,
        'sha256': '534b2070fcc7df514b13ef660dc8cbb328679c2374d04354a5c42bb14ecce111',
        'urls': (
            'https://github.com/TRvlvr/model_repo/releases/download/'
            'all_public_uvr_models/UVR-MDX-NET-Voc_FT.onnx',
            'https://huggingface.co/Politrees/UVR_resources/resolve/main/'
            'models/MDXNet/UVR-MDX-NET-Voc_FT.onnx',
        ),
    },
}

ORDER = ('w2v2', 'mdx')


def model_dir():
    base = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
    return os.path.join(base, 'intro no jutsu', 'models')


def model_path(key):
    return os.path.join(model_dir(), MODELS[key]['name'])


def present(key):
    path = model_path(key)
    try:
        return os.path.getsize(path) == MODELS[key]['size']
    except OSError:
        return False


def missing():
    return [key for key in ORDER if not present(key)]


def missing_bytes():
    return sum(MODELS[key]['size'] for key in missing())


def download_urls():
    seen = []
    for key in missing():
        for url in MODELS[key]['urls']:
            host = url.split('/')[2]
            if host not in seen:
                seen.append(host)
    return seen
