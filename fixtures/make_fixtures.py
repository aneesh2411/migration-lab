"""Generate the toy fixture tree (idempotent). Run before tests.

    python fixtures/make_fixtures.py
"""
from pathlib import Path

FILES = {
    'client_app/client_app/__init__.py': '',
    'client_app/client_app/titles.py': 'import textkit\n\n\ndef title_slug(title):\n    return textkit.slugify(title, sep="_")\n\n\ndef title_stats(title):\n    return {"slug": textkit.slugify(title),\n            "words": textkit.word_count(title)}\n',
    'client_app/snapshot.py': '"""Prints behavior samples; diffed across versions by the evaluator."""\nfrom client_app.titles import title_slug, title_stats\n\nfor t in ["Hello World", "The Quick Brown Fox", "a  b"]:\n    print(title_slug(t), title_stats(t))\n',
    'client_app/tests/test_titles.py': 'from client_app.titles import title_slug, title_stats\n\n\ndef test_title_slug():\n    assert title_slug("Hello World") == "hello_world"\n\n\ndef test_title_stats():\n    assert title_stats("One Two") == {"slug": "one-two", "words": 2}\n',
    'guides/textkit-1-to-2.md': '# textkit 1.x -> 2.0 migration guide\n\n## Breaking changes\n\n1. `textkit.slugify` moved to `textkit.text.slugify`.\n2. The `sep` keyword of `slugify` was renamed to `delimiter`.\n3. `textkit.word_count` moved to `textkit.text.word_count`.\n',
    'guides/textkit-unparseable.md': '# guide\n\n1. Ask the database nicely to migrate itself.\n',
    'textkit_v1/build/lib/textkit/__init__.py': '"""textkit v1: flat API."""\n\n\ndef slugify(text, sep="-"):\n    return sep.join(text.lower().split())\n\n\ndef word_count(text):\n    return len(text.split())\n',
    'textkit_v1/setup.py': 'from setuptools import setup\n\nsetup(name="textkit", version="1.0.0", packages=["textkit"])\n',
    'textkit_v1/textkit/__init__.py': '"""textkit v1: flat API."""\n\n\ndef slugify(text, sep="-"):\n    return sep.join(text.lower().split())\n\n\ndef word_count(text):\n    return len(text.split())\n',
    'textkit_v1/textkit.egg-info/PKG-INFO': 'Metadata-Version: 2.1\nName: textkit\nVersion: 1.0.0\nSummary: UNKNOWN\nHome-page: UNKNOWN\nLicense: UNKNOWN\nPlatform: UNKNOWN\n\nUNKNOWN\n\n',
    'textkit_v1/textkit.egg-info/SOURCES.txt': 'setup.py\ntextkit/__init__.py\ntextkit.egg-info/PKG-INFO\ntextkit.egg-info/SOURCES.txt\ntextkit.egg-info/dependency_links.txt\ntextkit.egg-info/top_level.txt',
    'textkit_v1/textkit.egg-info/dependency_links.txt': '\n',
    'textkit_v1/textkit.egg-info/top_level.txt': 'textkit\n',
    'textkit_v2/build/lib/textkit/__init__.py': '"""textkit v2: namespaced API."""\n',
    'textkit_v2/build/lib/textkit/text/__init__.py': 'def slugify(text, delimiter="-"):\n    return delimiter.join(text.lower().split())\n\n\ndef word_count(text):\n    return len(text.split())\n',
    'textkit_v2/setup.py': 'from setuptools import setup\n\nsetup(name="textkit", version="2.0.0",\n      packages=["textkit", "textkit.text"])\n',
    'textkit_v2/textkit/__init__.py': '"""textkit v2: namespaced API."""\n',
    'textkit_v2/textkit/text/__init__.py': 'def slugify(text, delimiter="-"):\n    return delimiter.join(text.lower().split())\n\n\ndef word_count(text):\n    return len(text.split())\n',
    'textkit_v2/textkit.egg-info/PKG-INFO': 'Metadata-Version: 2.1\nName: textkit\nVersion: 2.0.0\nSummary: UNKNOWN\nHome-page: UNKNOWN\nLicense: UNKNOWN\nPlatform: UNKNOWN\n\nUNKNOWN\n\n',
    'textkit_v2/textkit.egg-info/SOURCES.txt': 'setup.py\ntextkit/__init__.py\ntextkit.egg-info/PKG-INFO\ntextkit.egg-info/SOURCES.txt\ntextkit.egg-info/dependency_links.txt\ntextkit.egg-info/top_level.txt\ntextkit/text/__init__.py',
    'textkit_v2/textkit.egg-info/dependency_links.txt': '\n',
    'textkit_v2/textkit.egg-info/top_level.txt': 'textkit\n',
    'textkit_v2b/build/lib/textkit/__init__.py': '"""textkit v2: namespaced API."""\n',
    'textkit_v2b/build/lib/textkit/text/__init__.py': 'def slugify(text, delimiter="-"):\n    return delimiter.join(text.lower().split())\n\n\ndef word_count(text):\n    # subtle behavior change: counts runs of whitespace differently\n    return len(text.split(" "))  # naive: double spaces count\n',
    'textkit_v2b/setup.py': 'from setuptools import setup\n\nsetup(name="textkit", version="2.0.0",\n      packages=["textkit", "textkit.text"])\n',
    'textkit_v2b/textkit/__init__.py': '"""textkit v2: namespaced API."""\n',
    'textkit_v2b/textkit/text/__init__.py': 'def slugify(text, delimiter="-"):\n    return delimiter.join(text.lower().split())\n\n\ndef word_count(text):\n    # subtle behavior change: counts runs of whitespace differently\n    return len(text.split(" "))  # naive: double spaces count\n',
    'textkit_v2b/textkit.egg-info/PKG-INFO': 'Metadata-Version: 2.1\nName: textkit\nVersion: 2.0.0\nSummary: UNKNOWN\nHome-page: UNKNOWN\nLicense: UNKNOWN\nPlatform: UNKNOWN\n\nUNKNOWN\n\n',
    'textkit_v2b/textkit.egg-info/SOURCES.txt': 'setup.py\ntextkit/__init__.py\ntextkit.egg-info/PKG-INFO\ntextkit.egg-info/SOURCES.txt\ntextkit.egg-info/dependency_links.txt\ntextkit.egg-info/top_level.txt\ntextkit/text/__init__.py',
    'textkit_v2b/textkit.egg-info/dependency_links.txt': '\n',
    'textkit_v2b/textkit.egg-info/top_level.txt': 'textkit\n',
}


def main():
    root = Path(__file__).resolve().parent
    for rel, content in FILES.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    print(f"wrote {len(FILES)} fixture files")


if __name__ == "__main__":
    main()
