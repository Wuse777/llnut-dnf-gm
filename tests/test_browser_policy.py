"""Exercise the production middleware and SPA response without a game database."""
import re
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.testclient import TestClient

from dnfgm.browser_policy import Guard, content_security_policy, new_style_nonce, static_response


@pytest.fixture
def browser(tmp_path):
    document = b'<!doctype html><html><head><meta property="csp-nonce" nonce="__DNFGM_STYLE_NONCE__" /></head><body>GM</body></html>'
    (tmp_path / 'index.html').write_bytes(document)
    (tmp_path / 'assets').mkdir()
    (tmp_path / 'assets' / 'main.css').write_bytes(b'/* __DNFGM_STYLE_NONCE__ stays a static asset */')
    code = b'const item = "public build code";\n' * 200
    for name in ('main-Abcd1234.js', 'main-Abcd1234.css', 'font-Abcd1234.woff2'):
        (tmp_path / 'assets' / name).write_bytes(code)
    app = FastAPI()
    app.add_middleware(Guard, settings=SimpleNamespace(origins=['https://gm.example']))

    @app.get('/dnf-gm/api/v1/private-Abcd1234.js')
    def private():
        return Response(code, media_type='text/javascript', headers={'Cache-Control': 'public'})

    @app.api_route('/dnf-gm/{path:path}', methods=['GET', 'HEAD'])
    def static(path: str, request: Request):
        return static_response(tmp_path, path, request.state.style_nonce, head=request.method == 'HEAD')

    with TestClient(app, base_url='https://gm.example') as client:
        yield client, tmp_path, document


def nonce(response):
    return re.search(r"style-src 'self' 'nonce-([A-Za-z0-9_-]{43})'", response.headers['content-security-policy']).group(1)


@pytest.mark.parametrize('path', ['/dnf-gm/', '/dnf-gm/index.html', '/dnf-gm/home', '/dnf-gm/characters/123'])
def test_spa_entry_header_and_meta_share_nonce(browser, path):
    client, _, original = browser
    response = client.get(path)
    assert response.status_code == 200
    token = nonce(response)
    assert f'nonce="{token}"'.encode() in response.content
    assert b'__DNFGM_STYLE_NONCE__' not in response.content
    assert int(response.headers['content-length']) == len(response.content)
    assert len(response.content) == len(original) - len(b'__DNFGM_STYLE_NONCE__') + len(token)
    assert response.headers['content-type'] == 'text/html; charset=utf-8'
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['x-content-type-options'] == 'nosniff'
    policy = response.headers['content-security-policy']
    assert "script-src 'self';" in policy
    assert 'unsafe-inline' not in policy and 'unsafe-eval' not in policy


def test_nonce_is_per_request_and_cannot_be_selected_by_client(browser):
    client, root, original = browser
    first = client.get('/dnf-gm/')
    second = client.get('/dnf-gm/?nonce=' + nonce(first), headers={'X-Style-Nonce': nonce(first)})
    assert nonce(first) != nonce(second)
    assert (root / 'index.html').read_bytes() == original


def test_head_matches_get_representation_length_without_document_body(browser):
    client, _, _ = browser
    get = client.get('/dnf-gm/login')
    head = client.head('/dnf-gm/login')
    assert head.status_code == 200 and head.content == b''
    assert head.headers['content-length'] == get.headers['content-length']
    assert nonce(head) != nonce(get)


def test_static_assets_are_not_rewritten(browser):
    client, _, _ = browser
    response = client.get('/dnf-gm/assets/main.css')
    assert response.status_code == 200
    assert response.content == b'/* __DNFGM_STYLE_NONCE__ stays a static asset */'
    assert response.headers['content-type'].startswith('text/css')
    assert client.head('/dnf-gm/assets/main.css').content == b''
    assert response.headers['cache-control'] == 'no-store'
    assert 'content-encoding' not in response.headers


@pytest.mark.parametrize('name', ['main-Abcd1234.js', 'main-Abcd1234.css', 'font-Abcd1234.woff2'])
def test_only_existing_hashed_public_build_files_are_immutable(browser, name):
    client, root, _ = browser
    response = client.get('/dnf-gm/assets/' + name, headers={'Accept-Encoding': 'identity'})
    assert response.content == (root / 'assets' / name).read_bytes()
    assert response.headers.get_list('cache-control') == ['public, max-age=31536000, immutable']
    assert 'content-encoding' not in response.headers
    assert "script-src 'self';" in response.headers['content-security-policy']


def test_public_code_gzip_negotiates_encoding_and_keeps_nonce_policy(browser):
    client, root, _ = browser
    path = '/dnf-gm/assets/main-Abcd1234.js'
    response = client.get(path, headers={'Accept-Encoding': 'gzip'})
    assert response.headers['content-encoding'] == 'gzip'
    assert response.headers['vary'] == 'Accept-Encoding'
    assert response.headers['etag'].startswith('W/')
    assert int(response.headers['content-length']) < len(response.content)
    assert response.content == (root / 'assets/main-Abcd1234.js').read_bytes()
    assert 'unsafe-inline' not in response.headers['content-security-policy']
    for encoding in ('identity', 'gzip;q=0, br', 'x-gzip', 'gzip;q=bad'):
        identity = client.get(path, headers={'Accept-Encoding': encoding})
        assert identity.content == response.content
        assert identity.headers['vary'] == 'Accept-Encoding'
        assert 'content-encoding' not in identity.headers


def test_public_code_head_and_range_keep_identity_lengths(browser):
    client, root, _ = browser
    path = '/dnf-gm/assets/main-Abcd1234.js'
    head = client.head(path, headers={'Accept-Encoding': 'gzip'})
    assert head.content == b''
    assert 'content-encoding' not in head.headers
    assert int(head.headers['content-length']) == (root / 'assets/main-Abcd1234.js').stat().st_size
    partial = client.get(path, headers={'Accept-Encoding': 'gzip', 'Range': 'bytes=0-9'})
    assert partial.status_code == 206
    assert partial.content == (root / 'assets/main-Abcd1234.js').read_bytes()[:10]
    assert 'content-encoding' not in partial.headers
    assert int(partial.headers['content-length']) == 10
    assert partial.headers['cache-control'] == 'public, max-age=31536000, immutable'


def test_large_public_code_gzip_preserves_streamed_body(browser):
    client, root, _ = browser
    content = b'const item = "large public build code";\n' * 20000
    (root / 'assets/large-Abcd1234.js').write_bytes(content)
    response = client.get('/dnf-gm/assets/large-Abcd1234.js', headers={'Accept-Encoding': 'gzip'})
    assert response.content == content
    assert response.headers['content-encoding'] == 'gzip'
    assert response.headers['vary'] == 'Accept-Encoding'
    # Streaming encodes chunks without buffering the entire bundle to compute its size.
    assert 'content-length' not in response.headers


@pytest.mark.parametrize('extension', ['webp', 'png', 'jpg', 'jpeg', 'avif', 'svg'])
def test_hashed_public_images_are_immutable_without_gzip(browser, extension):
    client, root, _ = browser
    content = b'public image bytes' * 200
    name = 'background-Abcd1234.' + extension
    (root / 'assets' / name).write_bytes(content)
    response = client.get('/dnf-gm/assets/' + name, headers={'Accept-Encoding': 'gzip'})
    assert response.content == content
    assert response.headers.get_list('cache-control') == ['public, max-age=31536000, immutable']
    assert 'content-encoding' not in response.headers
    assert int(response.headers['content-length']) == len(content)


@pytest.mark.parametrize('path', ['/dnf-gm/assets/missing-Abcd1234.js', '/dnf-gm/api/v1/private-Abcd1234.js'])
def test_asset_shaped_errors_and_private_api_never_gain_public_cache_or_gzip(browser, path):
    client, _, _ = browser
    response = client.get(path, headers={'Accept-Encoding': 'gzip'})
    assert response.headers['cache-control'] == 'no-store'
    assert 'content-encoding' not in response.headers


def test_gzip_is_not_applied_to_nonce_documents_or_fonts(browser):
    client, _, _ = browser
    for path in ('/dnf-gm/home', '/dnf-gm/assets/font-Abcd1234.woff2'):
        response = client.get(path, headers={'Accept-Encoding': 'gzip'})
        assert 'content-encoding' not in response.headers


@pytest.mark.parametrize('path', ['assets/missing.js', 'missing.css', 'api/unknown', '../outside'])
def test_missing_assets_api_and_outside_paths_do_not_return_spa(browser, path):
    _, root, _ = browser
    with pytest.raises(HTTPException) as error:
        static_response(root, path, new_style_nonce())
    assert error.value.status_code == 404


def test_guard_keeps_host_origin_and_body_limits(browser):
    client, _, _ = browser
    assert client.get('/dnf-gm/', headers={'Host': 'evil.example'}).status_code == 400
    assert client.post('/dnf-gm/', headers={'Origin': 'https://evil.example'}).status_code == 403
    assert client.post('/dnf-gm/', headers={'Origin': 'https://gm.example'}, content=b'x' * 65537).status_code == 413


@pytest.mark.parametrize('value', ['', '__DNFGM_STYLE_NONCE__', "bad' ; script-src *", '<style>', 'a' * 42, None])
def test_arbitrary_nonce_is_not_accepted(value):
    with pytest.raises(ValueError):
        content_security_policy(value)
