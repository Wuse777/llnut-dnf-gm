"""Exercise the production middleware and SPA response without a game database."""
import re
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from dnfgm.browser_policy import Guard, content_security_policy, new_style_nonce, static_response


@pytest.fixture
def browser(tmp_path):
    document = b'<!doctype html><html><head><meta property="csp-nonce" nonce="__DNFGM_STYLE_NONCE__" /></head><body>GM</body></html>'
    (tmp_path / 'index.html').write_bytes(document)
    (tmp_path / 'assets').mkdir()
    (tmp_path / 'assets' / 'main.css').write_bytes(b'/* __DNFGM_STYLE_NONCE__ stays a static asset */')
    app = FastAPI()
    app.add_middleware(Guard, settings=SimpleNamespace(origins=['https://gm.example']))

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
