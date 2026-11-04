// What each operation sends, and the context a search gives. Run against the build: `npm test`.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import requests from '../dist/nodes/Alexein/requests.js';

const { checkedUser, context, host, item, merged, page, request, route, shaped } = requests;
const params = (values) => (name, fallback) => values[name] ?? fallback;
const contract = JSON.parse(
	readFileSync(new URL('../../../contract/openapi.json', import.meta.url), 'utf8'),
);

test('an item keeps what was set and leaves out what was not', () => {
	const got = item(
		params({
			text: '  I moved to Lisbon.  ',
			kind: 'note',
			additionalFields: {
				id: 'move',
				session: '',
				about: 'project:atlas, customer:acme ,',
				expires: '2026-12-31T00:00:00',
				metadata: '{"source": "telegram"}',
			},
		}),
	);
	assert.deepEqual(got, {
		text: 'I moved to Lisbon.',
		kind: 'note',
		id: 'move',
		about: ['project:atlas', 'customer:acme'],
		expires: '2026-12-31T00:00:00',
		metadata: { source: 'telegram' },
	});
});

test('an item with no text, or metadata that is not an object, is refused', () => {
	assert.throws(() => item(params({ text: '  ' })), /nothing to remember/);
	for (const metadata of ['[1]', '{nope']) {
		assert.throws(
			() => item(params({ text: 'x', additionalFields: { metadata } })),
			/Metadata must be a JSON object/,
		);
	}
	assert.equal(
		item(params({ text: 'x', additionalFields: { metadata: '{}' } })).metadata,
		undefined,
	);
});

const CASES = [
	[
		'search',
		{
			query: 'Where?',
			fast: true,
			searchOptions: {
				after: '2026-01-01',
				provider: 'github',
				source: 'acme/atlas',
				kind: 'issue, pull_request',
				filters: '{"metadata": {"priority": {"gte": 3}}}',
			},
		},
		'search',
		{
			query: 'Where?',
			fast: true,
			after: '2026-01-01',
			provider: 'github',
			source: 'acme/atlas',
			kind: ['issue', 'pull_request'],
			filters: { metadata: { priority: { gte: 3 } } },
		},
	],
	[
		'search',
		{ query: 'Where?', searchOptions: { filters: '{}' } },
		'search',
		{ query: 'Where?', fast: false },
	],
	['history', { subject: 'Dana', attribute: '' }, 'history', { subject: 'Dana' }],
	[
		'latest',
		{
			k: 3,
			latestOptions: { place: 'slack', kind: 'message', filters: { mentions: 'project:x' } },
		},
		'latest',
		{ k: 3, place: 'slack', kind: ['message'], filters: { mentions: 'project:x' } },
	],
	[
		'grep',
		{ pattern: 'Lisbon', limit: 5, grepOptions: { provider: 'slack' } },
		'grep',
		{ pattern: 'Lisbon', limit: 5, provider: 'slack' },
	],
	['open', { ref: ' mem_1 ' }, 'open', { ref: 'mem_1' }],
	['around', { ref: 'mem_1' }, 'around', { ref: 'mem_1', width: 2 }],
	['summary', {}, 'summary', {}],
	['sources', {}, 'sources', {}],
	['facts', { limit: 20 }, 'facts', { limit: 20 }],
	['facts', { limit: 20, cursor: 'c1' }, 'facts', { limit: 20, cursor: 'c1' }],
	[
		'items',
		{ limit: 10, itemsOptions: { filters: '{"author": "dana"}' } },
		'items',
		{ limit: 10, filters: { author: 'dana' } },
	],
	['item', { itemId: 'move' }, 'item', { id: 'move' }],
	[
		'openItems',
		{ limit: 5, openItemsOptions: { mine: false, withinDays: 30, kind: 'issue' } },
		'open_items',
		{ limit: 5, mine: false, within_days: 30, kind: ['issue'] },
	],
	['versions', { itemId: 'move' }, 'versions', { id: 'move' }],
	['status', { ids: 'move, tea' }, 'status', { items: ['move', 'tea'] }],
	[
		'forget',
		{ items: 'move', sessions: 'trip', refs: 'mem_1, mem_2' },
		'forget',
		{ items: ['move'], sessions: ['trip'], refs: ['mem_1', 'mem_2'] },
	],
	[
		'correct',
		{ ref: 'mem_1', replacement: 'Porto' },
		'correct',
		{ ref: 'mem_1', replacement: 'Porto' },
	],
	['export', { limit: 100 }, 'export', { limit: 100 }],
	['users', { limit: 50 }, 'users', { limit: 50 }],
	['deleteUser', {}, 'users/delete', {}],
];

test('each operation posts to its v2 route with its fields', () => {
	for (const [operation, values, path, body] of CASES) {
		assert.deepEqual(request(operation, params(values)), { path, body }, operation);
	}
});

test('every route and every field sent is one the contract has', () => {
	const resolve = (schema) =>
		schema?.$ref ? contract.components.schemas[schema.$ref.split('/').pop()] : schema;
	for (const [operation, values] of CASES) {
		const { path, body } = request(operation, params(values));
		const route = contract.paths[`/memory/${path}`]?.post;
		assert.ok(route, `${operation}: /memory/${path} is in the contract`);
		const schema = resolve(route.requestBody?.content['application/json'].schema);
		for (const field of Object.keys(body)) {
			assert.ok(
				schema?.properties?.[field],
				`${operation}: ${field} is a field of /memory/${path}`,
			);
		}
	}
	const add = resolve(
		contract.paths['/memory/add'].post.requestBody.content['application/json'].schema,
	);
	const one = item(
		params({
			text: 'x',
			additionalFields: {
				id: 'i',
				session: 's',
				role: 'user',
				author: 'dana',
				title: 't',
				about: 'a:b',
				at: '2026-01-01',
				expires: '2026-02-01',
				metadata: '{"k":1}',
			},
		}),
	);
	const itemFields = contract.components.schemas.Item.properties;
	for (const field of Object.keys(one)) assert.ok(itemFields[field], `add item: ${field}`);
	for (const field of ['items', 'wait', 'redact'])
		assert.ok(add.properties[field], `add: ${field}`);
	const headers = contract.paths['/memory/add'].post.parameters.map((p) => p.name);
	assert.ok(headers.includes('X-Alexein-User') && headers.includes('Idempotency-Key'));
	assert.ok(contract.paths['/me'].get);
});

test('a paged operation with Return All asks for the longest pages and follows next', () => {
	const all = params({ returnAll: true, limit: 5, cursor: 'ignored' });
	assert.deepEqual(page('facts', all), { path: 'facts', body: { limit: 100 } });
	assert.deepEqual(page('facts', all, 'c2'), { path: 'facts', body: { limit: 100, cursor: 'c2' } });
	assert.deepEqual(page('export', all).body, { limit: 500 });
	assert.deepEqual(page('items', all).body, { limit: 200 });
	assert.deepEqual(page('users', all).body, { limit: 500 });
	const pages = [
		{ user: 'dana', exported_at: 'now', records: [{ a: 1 }], next: 'c2', withheld: [] },
		{ user: 'dana', exported_at: 'later', records: [{ a: 2 }], next: null, withheld: [] },
	];
	assert.deepEqual(merged('export', pages), {
		user: 'dana',
		exported_at: 'now',
		records: [{ a: 1 }, { a: 2 }],
		next: null,
		withheld: [],
	});
});

test('forget and status refuse to name nothing', () => {
	assert.throws(() => request('forget', params({})), /Nothing to forget/);
	assert.throws(() => request('status', params({ ids: ' , ' })), /Item IDs is empty/);
	assert.throws(() => request('ls', params({})), /Unknown operation/);
});

test('an app user ID is checked before a round trip', () => {
	assert.equal(checkedUser(' 1234567 '), '1234567');
	assert.equal(checkedUser('x'.repeat(35)), 'x'.repeat(35));
	for (const bad of ['', '-dana', 'dana smith', 'dana/smith', 'x'.repeat(36)]) {
		assert.throws(() => checkedUser(bad), /not a usable ID/, bad);
	}
});

test('the base URL is the host: a trailing / or /v2 means the same', () => {
	for (const url of [
		'https://api.alexein.ai',
		'https://api.alexein.ai/',
		'https://api.alexein.ai/v2',
		'https://api.alexein.ai/v2/',
	]) {
		assert.equal(host(url), 'https://api.alexein.ai', url);
	}
	assert.equal(route('openItems'), 'open_items');
});

const SEARCHED = {
	query: 'Where does Alice live?',
	answerable: true,
	notes: ['Values are listed  newest first.'],
	memories: [
		{ type: 'known', text: 'Alice Chen · home city: Lisbon (said 2026-10-01)' },
		{
			type: 'fact',
			ref: 'mem_5',
			text: '(said 2026-10-01) Alice lives in Lisbon',
			source: 'mem_9',
		},
		{
			type: 'excerpt',
			ref: 'mem_9',
			text: 'I just moved to Lisbon\nfrom Berlin.',
			date: '2026-10-01T09:30:00+00:00',
		},
		{ type: 'excerpt', ref: 'mem_8', text: 'Undated.', date: null },
	],
};

test('context is the notes, then each memory on a line, excerpts dated, as the SDKs give it', () => {
	assert.equal(
		context(SEARCHED, 4000),
		'Values are listed newest first.\n' +
			'- Alice Chen · home city: Lisbon (said 2026-10-01)\n' +
			'- (said 2026-10-01) Alice lives in Lisbon\n' +
			'- 2026-10-01: I just moved to Lisbon from Berlin.\n' +
			'- Undated.',
	);
	assert.equal(
		context(SEARCHED, 90),
		'Values are listed newest first.\n- Alice Chen · home city: Lisbon (said 2026-10-01)',
	);
	assert.equal(context({ notes: ['Nothing found.'], memories: [] }, 4000), '');
});

test('a search answer comes back with its context first; others as the API sent them', () => {
	const got = shaped('search', SEARCHED, params({ searchOptions: { contextLength: 90 } }));
	assert.deepEqual(Object.keys(got)[0], 'context');
	assert.equal(got.answerable, true);
	assert.equal(shaped('grep', { total: 1 }, params({})).total, 1);
});
