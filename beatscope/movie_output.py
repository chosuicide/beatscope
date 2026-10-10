"""Validated render dimensions shared by admission and persisted jobs."""


def movie_output(value=None):
    value = {} if value is None else value
    if not isinstance(value, dict) or set(value) - {'aspect', 'resolution'}:
        raise ValueError('output/invalid')
    aspect = value.get('aspect', '1:1')
    resolution = value.get('resolution', 1080)
    if aspect not in ('1:1', '16:9', '9:16') or type(resolution) is not int or resolution not in (720, 1080):
        raise ValueError('output/invalid')
    long = 1280 if resolution == 720 else 1920
    width, height = {'1:1': (resolution, resolution), '16:9': (long, resolution),
                     '9:16': (resolution, long)}[aspect]
    return {'aspect': aspect, 'resolution': resolution, 'width': width, 'height': height, 'fps': 30}
