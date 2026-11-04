// The node's execute against a fake n8n: what it sends, how it batches adds, how it pages, and what
// a failure becomes. Run against the build: `npm test`.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import node from '../dist/nodes/Alexein/Alexein.node.js';

const NODE = {
	id: '1',
	name: 'Alexein',
	type: '@alexein/n8n-nodes-alexein.alexein',
	typeVersion: 1,
	position: [0, 0],
	parameters: {},
};

function fake(items, answer, { continueOnFail = false, execution = 'ex-1' } = {}) {
	const sent = [];
	const context = {
		getInputData: () => items.map(() => ({ json: {} })),
		getNodeParameter: (name, index, fallback) => items[index][name] ?? fallback,
		getCredentials: async () => ({ apiKey: 'tm_test', baseUrl: 'https://api.example/v2/' }),
		getExecutionId: () => execution,
		continueOnFail: () => continueOnFail,
		getNode: () => NODE,
		helpers: {
			async httpRequestWithAuthentication(credential, options) {
				sent.push({ credential, ...options });
				return answer(options);
			},
		},
	};
	return { context, sent };
}

const ok = (body) => ({ statusCode: 200, body });
const run = (context) => new node.Alexein().execute.call(context);
const addedOk = (options) =>
	ok({
		items: options.body.items.map((i) => ({ id: `id-${i.text}`, status: 'stored' })),
		waiting: 0,
	});

test('a search goes to its v2 route as the app user and comes back with a context', async () => {
	const answer = {
		query: 'Where?',
		answerable: null,
		notes: [],
		memories: [{ type: 'excerpt', ref: 'mem_1', text: 'I moved to Lisbon.', date: null }],
	};
	const { context, sent } = fake(
		[{ operation: 'search', user: 'dana', query: 'Where?', fast: true }],
		() => ok(answer),
	);
	const [[out]] = await run(context);
	assert.equal(sent[0].credential, 'alexeinApi');
	assert.equal(sent[0].url, 'https://api.example/v2/memory/search');
	assert.equal(sent[0].method, 'POST');
	assert.deepEqual(sent[0].headers, { 'X-Alexein-User': 'dana' });
	assert.deepEqual(sent[0].body, { query: 'Where?', fast: true });
	assert.equal(out.json.context, '- I moved to Lisbon.');
	assert.deepEqual(out.pairedItem, { item: 0 });
});

test('List App Users names no app user', async () => {
	const { context, sent } = fake([{ operation: 'users', limit: 50 }], () =>
		ok({ users: [{ user: 'dana', items: 2, facts: 1, last_write: null }], next: null }),
	);
	const [[out]] = await run(context);
	assert.equal(sent[0].url, 'https://api.example/v2/memory/users');
	assert.deepEqual(sent[0].headers, {});
	assert.equal(out.json.users[0].user, 'dana');
});

test('Delete App User posts to users/delete as that app user', async () => {
	const { context, sent } = fake([{ operation: 'deleteUser', user: 'dana' }], () =>
		ok({ deleted: true }),
	);
	await run(context);
	assert.equal(sent[0].url, 'https://api.example/v2/memory/users/delete');
	assert.deepEqual(sent[0].headers, { 'X-Alexein-User': 'dana' });
	assert.deepEqual(sent[0].body, {});
});

test('Return All follows next and answers every page as one item', async () => {
	const pages = {
		'': { facts: [{ ref: 'mem_1' }], next: 'c2' },
		c2: { facts: [{ ref: 'mem_2' }], next: 'c3' },
		c3: { facts: [{ ref: 'mem_3' }], next: null },
	};
	const { context, sent } = fake(
		[{ operation: 'facts', user: 'dana', returnAll: true }],
		(options) => ok(pages[options.body.cursor ?? '']),
	);
	const [[out]] = await run(context);
	assert.deepEqual(
		sent.map((s) => s.body),
		[{ limit: 100 }, { limit: 100, cursor: 'c2' }, { limit: 100, cursor: 'c3' }],
	);
	assert.deepEqual(out.json, {
		facts: [{ ref: 'mem_1' }, { ref: 'mem_2' }, { ref: 'mem_3' }],
		next: null,
	});
});

test('adds for one app user go together, and each item gets its own answer in input order', async () => {
	const items = [
		{ operation: 'add', user: 'dana', text: 'one' },
		{ operation: 'add', user: 'sam', text: 'two' },
		{ operation: 'add', user: 'dana', text: 'three', redact: true },
		{ operation: 'add', user: 'dana', text: 'four' },
	];
	const { context, sent } = fake(items, addedOk);
	const [out] = await run(context);
	assert.deepEqual(
		sent.map((s) => [s.headers['X-Alexein-User'], s.body.items.map((i) => i.text), s.body.redact]),
		[
			['dana', ['one', 'four'], undefined],
			['sam', ['two'], undefined],
			['dana', ['three'], true],
		],
	);
	assert.ok(sent.every((s) => s.url === 'https://api.example/v2/memory/add'));
	assert.deepEqual(
		out.map((o) => [o.json.id, o.json.status, o.json.waiting, o.pairedItem.item]),
		[
			['id-one', 'stored', 0, 0],
			['id-two', 'stored', 0, 1],
			['id-three', 'stored', 0, 2],
			['id-four', 'stored', 0, 3],
		],
	);
});

test('an add carries an Idempotency-Key: the same on a retry in one execution, new in the next', async () => {
	const items = [{ operation: 'add', user: 'dana', text: 'one' }];
	const keys = async (execution) => {
		const { context, sent } = fake(items, addedOk, { execution });
		await run(context);
		return sent.map((s) => s.headers['Idempotency-Key']);
	};
	const [first] = await keys('ex-1');
	assert.match(first, /^[0-9a-f]{64}-0$/);
	assert.deepEqual(await keys('ex-1'), [first]);
	assert.notDeepEqual(await keys('ex-2'), [first]);
});

test('more than 500 adds for one app user go 500 at a time, each batch with its own key', async () => {
	const items = Array.from({ length: 1201 }, (_, k) => ({
		operation: 'add',
		user: 'dana',
		text: `fact ${k}`,
	}));
	const { context, sent } = fake(items, addedOk);
	const [out] = await run(context);
	assert.deepEqual(
		sent.map((s) => s.body.items.length),
		[500, 500, 201],
	);
	assert.deepEqual(
		sent.map((s) => s.headers['Idempotency-Key'].split('-').pop()),
		['0', '1', '2'],
	);
	assert.equal(out.length, 1201);
});

test("an API refusal is a node error in the API's words", async () => {
	const { context } = fake([{ operation: 'open', user: 'dana', ref: 'mem_x' }], () => ({
		statusCode: 404,
		body: { detail: 'memory holds nothing by this ref' },
	}));
	await assert.rejects(run(context), (error) => {
		assert.equal(error.constructor.name, 'NodeApiError');
		assert.equal(error.message, 'memory holds nothing by this ref');
		assert.equal(error.httpCode, '404');
		return true;
	});
});

test('with Continue On Fail, a bad item is an error output and the rest go on', async () => {
	const items = [
		{ operation: 'add', user: 'dana smith', text: 'bad user' },
		{ operation: 'add', user: 'dana', text: 'fine' },
	];
	const { context, sent } = fake(items, addedOk, { continueOnFail: true });
	const [out] = await run(context);
	assert.equal(sent.length, 1);
	assert.match(out[0].json.error, /not a usable ID/);
	assert.equal(out[1].json.id, 'id-fine');
});

test('a validation error says what the API said, and names each field', async () => {
	const body = {
		detail:
			'`query` must not be empty. See https://docs.alexein.ai/api/search for what this route takes.',
		errors: [{ field: 'query', message: '`query` must not be empty' }],
	};
	const { context } = fake([{ operation: 'search', user: 'dana', query: 'x' }], () => ({
		statusCode: 422,
		body,
	}));
	await assert.rejects(run(context), (error) => {
		assert.match(error.message, /`query` must not be empty/);
		assert.equal(error.description, 'query: `query` must not be empty');
		return true;
	});
});
