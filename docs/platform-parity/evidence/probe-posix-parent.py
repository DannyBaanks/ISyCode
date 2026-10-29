from pathlib import Path
from tempfile import TemporaryDirectory
from isycode.platform_storage import storage
with TemporaryDirectory() as temp:
    root = Path(temp)
    outside = root / 'outside'
    storage.ensure_directory(outside)
    (root / 'link').symlink_to(outside, target_is_directory=True)
    try:
        storage.ensure_directory(root / 'link' / 'inside')
    except ValueError:
        print('LINKED_PARENT_REFUSED=PASS')
    else:
        raise AssertionError('created private state through a linked parent')
