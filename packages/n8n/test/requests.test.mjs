// What each operation sends, and the context a search gives. Run against the build: `npm test`.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import requests from '../dist/nodes/TwinMemory/requests.js';

const { checkedUser, context, item, request, shaped } = requests;
const params = (values) => (name, fallback) => values[name] ?? fallback;

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
	assert.throws(
		() => item(params({ text: 'x', additionalFields: { metadata: '[1]' } })),
		/JSON object/,
	);
});

test('each operation posts to its route with its fields', () => {
	const cases = [
		[
			'search',
			{ query: 'Where?', fast: true, searchOptions: { after: '2026-01-01' } },
			{ query: 'Where?', fast: true, after: '2026-01-01' },
		],
		['search', { query: 'Where?' }, { query: 'Where?', fast: false }],
		['history', { subject: 'Dana', attribute: '' }, { subject: 'Dana' }],
		['latest', { k: 3, latestOptions: { place: 'slack' } }, { k: 3, place: 'slack' }],
		['grep', { pattern: 'Lisbon', limit: 5 }, { pattern: 'Lisbon', limit: 5 }],
		['read', { path: 'a/b.md' }, { path: 'a/b.md' }],
		['ls', {}, { path: '' }],
		['around', { passageId: 'th_1/p_0001' }, { passage_id: 'th_1/p_0001', width: 2 }],
		['overview', {}, {}],
		['versions', { itemId: 'move' }, { id: 'move' }],
		['lineage', { lineageId: 'ev_1' }, { id: 'ev_1' }],
		['status', { ids: 'move, ev_2' }, { ids: ['move', 'ev_2'] }],
		['forget', { items: 'move', sessions: 'trip' }, { items: ['move'], sessions: ['trip'] }],
		[
			'correct',
			{ recordId: 'th_1#r1', replacement: 'Porto' },
			{ record_id: 'th_1#r1', replacement: 'Porto' },
		],
	];
	for (const [operation, values, body] of cases) {
		assert.deepEqual(request(operation, params(values)), { path: operation, body }, operation);
	}
});

test('forget and status refuse to name nothing', () => {
	assert.throws(() => request('forget', params({})), /Nothing to forget/);
	assert.throws(() => request('status', params({ ids: ' , ' })), /IDs is empty/);
});

test('an end user ID is checked before a round trip', () => {
	assert.equal(checkedUser(' 1234567 '), '1234567');
	for (const bad of ['', '-dana', 'dana smith', 'x'.repeat(65)]) {
		assert.throws(() => checkedUser(bad), /not a usable ID/, bad);
	}
});

const SEARCHED = {
	known: ['Dana lives in Lisbon (since 2026-10-01).'],
	facts: [{ text: '2026-10-01: Dana moved to Lisbon for a job at Acme.' }],
	hits: [{ text: '**Dana** 00:00 · I moved to Lisbon\nfor the job at Acme.' }],
};

test('context is known lines, then facts, then passages, as the Python SDK gives it', () => {
	assert.equal(
		context(SEARCHED, 4000),
		'What is known:\n- Dana lives in Lisbon (since 2026-10-01).\n\n' +
			'Facts:\n- 2026-10-01: Dana moved to Lisbon for a job at Acme.\n\n' +
			'Passages:\n- **Dana** 00:00 · I moved to Lisbon for the job at Acme.',
	);
	assert.equal(context(SEARCHED, 60), 'What is known:\n- Dana lives in Lisbon (since 2026-10-01).');
	assert.equal(context({ hits: [] }, 4000), '');
});

test('a search answer comes back with its context first; others as the API sent them', () => {
	const answer = { ...SEARCHED, filtered: true };
	const got = shaped('search', answer, params({ searchOptions: { contextLength: 60 } }));
	assert.deepEqual(Object.keys(got)[0], 'context');
	assert.equal(got.filtered, true);
	assert.equal(shaped('grep', { total: 1 }, params({})).total, 1);
});
