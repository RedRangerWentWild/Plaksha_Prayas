#!/usr/bin/env python3
"""Serve the app, and hold the API key so the browser never does.

Everything this tool measures happens client side and stays that way. The one
thing a browser cannot do safely is hold an API key, so this process does: it
serves the same static directory `python3 -m http.server` did, plus a single
POST /ask endpoint that forwards an evidence pack to Claude and returns the
structured answer.

An absent key is a supported way to run this, not an error. /ask then answers
503 and the page stays on the deterministic answer it has already rendered, so
the demo works identically with the network unplugged.

Usage:
    python3 server.py                          # no model, offline answers only
    ANTHROPIC_API_KEY=... python3 server.py    # Claude
    GEMINI_API_KEY=... python3 server.py       # Gemini
    VBG_PROVIDER=gemini VBG_MODEL=gemini-2.5-pro GEMINI_API_KEY=... python3 server.py
    python3 server.py --port 8000 --host 0.0.0.0

The provider follows VBG_PROVIDER, or whichever key is present. Retrieval,
the arithmetic and the verdict never involve either one: without a key the
page answers from the corpus alone, which is the supported default.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
# Two providers, because the key is the only part of this that is anyone's
# property. Whichever is configured, the contract is identical: the model is
# handed the evidence pack and must return the one structured shape the client
# validates. It narrates numbers it cannot change.
ANTHROPIC_API = 'https://api.anthropic.com/v1/messages'
GEMINI_API = ('https://generativelanguage.googleapis.com/v1beta/models/'
              '%s:generateContent')

DEFAULT_MODEL = {'anthropic': 'claude-opus-5', 'gemini': 'gemini-2.5-flash'}
MAX_BODY = 1 << 20          # an evidence pack is a few KB; this is generous

# Both defaults now think before they answer, and thinking is drawn from the
# SAME output budget as the reply. At the 900 this used to send, a reasoning
# model could spend the entire allowance thinking and return a truncated
# message carrying no tool call at all — which arrived here as
# "the model did not return a structured answer", a message that named the
# symptom and hid the cause. The answer itself is ~180 words plus four short
# arrays, so the generous ceiling costs nothing when it is not used: billing
# is on tokens produced, not on the cap.
MAX_OUTPUT_TOKENS = 8000

# Thinking also takes wall-clock. Eight seconds was never a budget a reasoning
# model could meet, and the deadline is nearly free here: tier 0 is already on
# screen before this request is made, so a slow model costs the reader nothing
# but a late paragraph.
UPSTREAM_TIMEOUT = 25


def key():
    """The configured key, or '' when the server runs answer-less on purpose."""
    return os.environ.get(
        'ANTHROPIC_API_KEY' if provider() == 'anthropic' else 'GEMINI_API_KEY',
        '').strip()


def provider():
    """Which API to call. Explicit setting wins, otherwise whichever key exists.

    Anthropic is preferred on a tie only because it was here first; nothing in
    the pipeline depends on the choice.
    """
    p = os.environ.get('VBG_PROVIDER', '').strip().lower()
    if p in ('anthropic', 'gemini'):
        return p
    if os.environ.get('ANTHROPIC_API_KEY', '').strip():
        return 'anthropic'
    if os.environ.get('GEMINI_API_KEY', '').strip():
        return 'gemini'
    return 'anthropic'


def model():
    return os.environ.get('VBG_MODEL', '').strip() or DEFAULT_MODEL[provider()]


def gemini_schema(node):
    """Strip a JSON Schema down to the OpenAPI subset Gemini accepts.

    Anthropic takes a full JSON Schema; Gemini rejects the request outright on
    keywords it does not know, $schema and additionalProperties among them.
    Dropping the unknown keys leaves the same contract, because the fields the
    client validates are all expressible in both.
    """
    if not isinstance(node, dict):
        return node
    keep = ('type', 'description', 'enum', 'nullable', 'format')
    out = {k: node[k] for k in keep if k in node}
    if 'properties' in node:
        out['properties'] = {k: gemini_schema(v)
                             for k, v in node['properties'].items()}
    if 'required' in node:
        out['required'] = node['required']
    if 'items' in node:
        out['items'] = gemini_schema(node['items'])
    return out


def build_request(payload):
    """Assemble the Messages call from the pack the client sent.

    The contract is static across every question and the pack is not, so the
    contract gets the cache breakpoint and the pack sits after it. Forced tool
    use rather than prose parsing: the shape then comes back guaranteed, and
    the client's validator only has to check that it is true.
    """
    pack = payload['pack']
    chunks = '\n\n'.join(
        '[%s] %s\n(%s — %s%s)\n%s' % (
            c['id'], c['title'], c['authority'], c.get('source') or 'repo',
            '; DRAFTED, NOT YET CHECKED AGAINST THE ORIGINAL' if c.get('verify') else '',
            c['body'])
        for c in pack['chunks'])

    facts = json.dumps({'site': pack['site'], 'verdict': pack['verdict'],
                        'facts': pack['facts'], 'params': pack['params']},
                       ensure_ascii=False, indent=1)

    user = (
        '<site_facts>\n%s\n</site_facts>\n\n'
        '<chunks>\n%s\n</chunks>\n\n'
        '<verdict_code>%s</verdict_code>\n'
        '<intent>%s</intent>\n'
        '<question>%s</question>'
        % (facts, chunks, pack['verdict']['code'], pack['intent'], pack['question'])
    )

    if provider() == 'gemini':
        # Gemini reaches the same guarantee through a response schema rather
        # than a forced tool call, so the answer arrives as JSON text.
        tool = payload['tool']
        return {
            'systemInstruction': {'parts': [{'text': payload['contract']}]},
            'contents': [{'role': 'user', 'parts': [{'text': user}]}],
            'generationConfig': {
                'temperature': 0,
                'maxOutputTokens': MAX_OUTPUT_TOKENS,
                'responseMimeType': 'application/json',
                'responseSchema': gemini_schema(
                    tool.get('input_schema') or tool.get('parameters') or {}),
            },
        }

    # No temperature, top_p or top_k: sampling parameters are rejected outright
    # with a 400 on Opus 5 and the rest of the 4.7-and-later family.
    #
    # No explicit thinking block either. Thinking is on by default on Opus 5,
    # and it is deliberately left on: with thinking disabled these models will
    # occasionally write the tool call into visible prose instead of emitting a
    # tool_use block, which is precisely the failure this endpoint must not
    # have. Effort is turned down instead — narrating an evidence pack under a
    # contract is not a reasoning problem, and low effort buys back the latency.
    return {
        'model': model(),
        'max_tokens': MAX_OUTPUT_TOKENS,
        'output_config': {'effort': 'low'},
        'system': [
            {'type': 'text', 'text': payload['contract'],
             'cache_control': {'type': 'ephemeral'}},
        ],
        'messages': [{'role': 'user', 'content': user}],
        'tools': [payload['tool']],
        'tool_choice': {'type': 'tool', 'name': payload['tool']['name']},
    }


def upstream_request(payload):
    """The provider-shaped HTTP request, key included."""
    body = json.dumps(build_request(payload)).encode()
    if provider() == 'gemini':
        # Gemini takes the key in a header too, which keeps it out of the URL
        # and therefore out of any proxy or server log along the way.
        return urllib.request.Request(
            GEMINI_API % model(), data=body,
            headers={'content-type': 'application/json',
                     'x-goog-api-key': key()})
    return urllib.request.Request(
        ANTHROPIC_API, data=body,
        headers={'content-type': 'application/json',
                 'x-api-key': key(),
                 'anthropic-version': '2023-06-01'})


def structured_answer(out):
    """Pull the one structured object out, whatever shape the provider used.

    Returns (answer, why_not). Only the answer crosses back to the page —
    forwarding a whole response would hand the client fields it has no business
    reading — but a failure has to say what actually came back instead. The
    old version returned a bare None, so every one of these failures reached
    the officer as the same sentence and reached the log as nothing at all.
    """
    if provider() == 'gemini':
        cands = out.get('candidates', [])
        if not cands:
            fb = (out.get('promptFeedback') or {}).get('blockReason')
            return None, ('the request was blocked upstream: %s' % fb if fb
                          else 'the model returned no candidates')
        for cand in cands:
            for part in cand.get('content', {}).get('parts', []):
                if 'text' in part:
                    try:
                        return json.loads(part['text']), None
                    except ValueError:
                        return None, 'the model returned text that is not JSON'
        reason = cands[0].get('finishReason') or 'unknown'
        if reason == 'MAX_OUTPUT_TOKENS' or reason == 'MAX_TOKENS':
            return None, ('the model used its whole output budget before '
                          'answering (finishReason MAX_TOKENS) — raise '
                          'MAX_OUTPUT_TOKENS')
        return None, 'the model returned no text part (finishReason %s)' % reason

    blocks = out.get('content', [])
    for block in blocks:
        if block.get('type') == 'tool_use':
            return block.get('input') or {}, None
    kinds = ', '.join(sorted({b.get('type', '?') for b in blocks})) or 'nothing'
    stop = out.get('stop_reason') or 'unknown'
    if stop == 'max_tokens':
        return None, ('the model used its whole output budget before calling '
                      'the tool (stop_reason max_tokens, returned %s) — raise '
                      'MAX_OUTPUT_TOKENS' % kinds)
    if stop == 'refusal':
        return None, 'the model declined the request (stop_reason refusal)'
    return None, ('no tool call in the reply (stop_reason %s, returned %s)'
                  % (stop, kinds))


class Handler(SimpleHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def log_message(self, fmt, *args):
        if self.path == '/ask' or not self.path.endswith(('.png', '.json')):
            sys.stderr.write('%s %s\n' % (self.command, self.path))

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header('content-type', 'application/json')
        self.send_header('content-length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _drain(self):
        """Read the request body whether or not we intend to use it.

        This is keep-alive hygiene, and skipping it is not a cosmetic bug: an
        unread body stays in the socket, the next request on that connection
        starts mid-JSON, the server answers 400 with an HTML error page, and
        the client reports a model failure that never happened. The 503 path is
        the one that tempts you to skip it and the one where it matters most,
        because with no key every single request takes it.
        """
        try:
            n = int(self.headers.get('content-length') or 0)
        except ValueError:
            return None
        if n <= 0 or n > MAX_BODY:
            return None
        try:
            return self.rfile.read(n)
        except OSError:
            return None

    def do_POST(self):
        raw = self._drain()
        if self.path != '/ask':
            self.send_error(404)
            return
        if not key():
            # First-class state, not a failure. The client renders its own
            # answer before it ever calls here.
            self._json(503, {'reason': 'no %s set on the server'
                             % ('ANTHROPIC_API_KEY' if provider() == 'anthropic'
                                else 'GEMINI_API_KEY')})
            return
        if raw is None:
            self._json(400, {'reason': 'bad request size'})
            return
        try:
            payload = json.loads(raw)
            for f in ('pack', 'contract', 'tool'):
                if f not in payload:
                    self._json(400, {'reason': 'missing %s' % f})
                    return
        except ValueError as e:
            self._json(400, {'reason': 'unreadable request: %s' % e})
            return

        req = upstream_request(payload)
        try:
            with urllib.request.urlopen(req, timeout=UPSTREAM_TIMEOUT) as r:
                out = json.loads(r.read())
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors='replace')[:300]
            sys.stderr.write('upstream %s: %s\n' % (e.code, detail))
            self._json(502, {'reason': 'the model API answered %s' % e.code})
            return
        except Exception as e:                                   # noqa: BLE001
            sys.stderr.write('upstream failed: %r\n' % e)
            self._json(502, {'reason': 'the model API could not be reached'})
            return

        answer, why_not = structured_answer(out)
        if answer is None:
            # Named on the page and in the log. A failure the operator cannot
            # diagnose from either one is a failure they will re-run forever.
            sys.stderr.write('no structured answer: %s\n' % why_not)
            self._json(502, {'reason': why_not})
            return
        self._json(200, answer)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--port', type=int, default=8000)
    ap.add_argument('--host', default='127.0.0.1',
                    help='default loopback; a hall LAN is not a trusted network')
    a = ap.parse_args()

    if a.host not in ('127.0.0.1', 'localhost'):
        sys.stderr.write(
            '\n  WARNING: binding %s exposes this server to the network it is on.\n'
            '  Anyone who can reach it can spend your API key. Loopback plus an\n'
            '  SSH tunnel is the safe way to show this on someone else\'s machine.\n\n'
            % a.host)

    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    print('serving %s on http://%s:%d' % (os.path.basename(ROOT), a.host, a.port))
    print('model: %s' % ('%s via %s' % (model(), provider()) if key() else
                         'none — no API key set, answers stay local'))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print()


if __name__ == '__main__':
    main()
