"""Merge complete Codex model metadata without changing provider/default settings."""
import argparse
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import tempfile


def model_entries(value):
    entries = value.get('models') if isinstance(value, dict) else value
    if not isinstance(entries, list) or not entries:
        raise ValueError('Expected a nonempty Codex models array, not an OpenAI /v1/models data list')
    seen = set()
    for entry in entries:
        slug = entry.get('slug') if isinstance(entry, dict) else None
        if not isinstance(slug, str) or not slug.strip():
            raise ValueError('Every model needs a nonempty slug')
        if slug in seen:
            raise ValueError('Duplicate model slug: ' + slug)
        seen.add(slug)
    return entries


def merge_catalog(base, extra):
    base_entries, extra_entries = model_entries(base), model_entries(extra)
    collisions = {m['slug'] for m in base_entries} & {m['slug'] for m in extra_entries}
    if collisions:
        raise ValueError('Custom IDs already exist in the base catalog: ' + ', '.join(sorted(collisions)))
    # A cache may include identity/etag metadata. Only the ModelsResponse wrapper
    # belongs in the generated catalog; preserve the model definitions verbatim.
    return {'models': copy.deepcopy(base_entries + extra_entries)}


def write_catalog(path, catalog, overwrite=False):
    path = Path(path).expanduser().absolute()
    if path.is_symlink():
        raise ValueError('Refusing to replace a catalog symlink')
    if path.exists() and not overwrite:
        raise FileExistsError('Output exists; use --overwrite to back it up and replace it')
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', newline='\n', dir=path.parent,
                                         prefix='.' + path.name + '.', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(catalog, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        if path.exists():
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            backup = path.with_name(path.name + '.before-' + stamp)
            shutil.copy2(path, backup)
        os.replace(temporary, path)
        return backup
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', required=True, help='Fresh full Codex catalog, model cache, or bundled export')
    parser.add_argument('--extra', required=True, help='Custom ModelsResponse JSON')
    parser.add_argument('--output', required=True)
    parser.add_argument('--overwrite', action='store_true', help='Back up an existing output before replacing it')
    args = parser.parse_args()
    try:
        base_path, extra_path, output = (Path(p).expanduser().absolute() for p in
                                        (args.base, args.extra, args.output))
        if output.resolve() in (base_path.resolve(), extra_path.resolve()):
            raise ValueError('Output must differ from both input files')
        base = json.loads(base_path.read_text(encoding='utf-8-sig'))
        extra = json.loads(extra_path.read_text(encoding='utf-8-sig'))
        result = merge_catalog(base, extra)
        backup = write_catalog(output, result, args.overwrite)
        print(f'Wrote {len(result["models"])} models to {output}')
        if backup:
            print('Previous output backed up to ' + str(backup))
    except (OSError, ValueError) as exc:
        parser.exit(1, str(exc) + '\n')


if __name__ == '__main__':
    main()
