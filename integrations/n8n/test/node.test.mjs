// The node's execute against a fake n8n: what it sends, how it batches adds, and what a failure
// becomes. Run against the build: `npm test`.
import assert from 'node:assert/strict';
import { test } from 'node:test';

import node from '../dist/nodes/TwinMemory/TwinMemory.node.js';

const NODE = {
	id: '1',
	name: 'Twin Memory',
	type: 'n8n-nodes-twinmemory.twinMemory',
	typeVersion: 1,
	position: [0, 0],
	parameters: {},
};

function fake(items, answer, { continueOnFail = false } = {}) {
	const sent = [];
	const context = {
		getInputData: () => items.map(() => ({ json: {} })),
		getNodeParameter: (name, index, fallback) => items[index][name] ?? fallback,
		getCredentials: async () => ({ apiKey: 'tm_test', baseUrl: 'https://api.example/' }),
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
const run = (context) => new node.TwinMemory().execute.call(context);

test('a search goes to its route as the end user and comes back with a context', async () => {
	const answer = {
		query: 'Where?',
		found: 1,
		hits: [{ text: 'I moved to Lisbon.' }],
		filtered: false,
	};
	const { context, sent } = fake(
		[{ operation: 'search', endUser: 'dana', query: 'Where?', fast: true }],
		() => ok(answer),
	);
	const [[out]] = await run(context);
	assert.equal(sent[0].credential, 'twinMemoryApi');
	assert.equal(sent[0].url, 'https://api.example/v1/memory/search');
	assert.equal(sent[0].method, 'POST');
	assert.deepEqual(sent[0].headers, { 'X-Twin-Account': 'dana' });
	assert.deepEqual(sent[0].body, { query: 'Where?', fast: true });
	assert.equal(out.json.context, 'Passages:\n- I moved to Lisbon.');
	assert.deepEqual(out.pairedItem, { item: 0 });
});

test('adds for one end user go together, and each item gets its own answer in input order', async () => {
	const items = [
		{ operation: 'add', endUser: 'dana', text: 'one' },
		{ operation: 'add', endUser: 'sam', text: 'two' },
		{ operation: 'add', endUser: 'dana', text: 'three' },
	];
	const { context, sent } = fake(items, (options) =>
		ok({
			items: options.body.items.map((i) => ({ id: `id-${i.text}`, event_id: `ev_${i.text}` })),
			queued: 0,
			pending: 0,
		}),
	);
	const [out] = await run(context);
	assert.deepEqual(
		sent.map((s) => [s.headers['X-Twin-Account'], s.body.items.map((i) => i.text)]),
		[
			['dana', ['one', 'three']],
			['sam', ['two']],
		],
	);
	assert.deepEqual(
		out.map((o) => [o.json.id, o.pairedItem.item]),
		[
			['id-one', 0],
			['id-two', 1],
			['id-three', 2],
		],
	);
});

test('more than 500 adds for one end user go 500 at a time', async () => {
	const items = Array.from({ length: 1201 }, (_, k) => ({
		operation: 'add',
		endUser: 'dana',
		text: `fact ${k}`,
	}));
	const { context, sent } = fake(items, (options) =>
		ok({ items: options.body.items.map((_, k) => ({ id: `${k}` })), queued: 0, pending: 0 }),
	);
	const [out] = await run(context);
	assert.deepEqual(
		sent.map((s) => s.body.items.length),
		[500, 500, 201],
	);
	assert.equal(out.length, 1201);
});

test("an API refusal is a node error in the API's words", async () => {
	const { context } = fake([{ operation: 'search', endUser: 'nobody', query: 'x' }], () => ({
		statusCode: 404,
		body: { detail: "no memory for end user 'nobody' yet" },
	}));
	await assert.rejects(run(context), (error) => {
		assert.equal(error.constructor.name, 'NodeApiError');
		assert.equal(error.message, "no memory for end user 'nobody' yet");
		assert.equal(error.httpCode, '404');
		return true;
	});
});

test('with Continue On Fail, a bad item is an error output and the rest go on', async () => {
	const items = [
		{ operation: 'add', endUser: 'dana smith', text: 'bad user' },
		{ operation: 'add', endUser: 'dana', text: 'fine' },
	];
	const { context, sent } = fake(
		items,
		(options) => ok({ items: options.body.items.map(() => ({ id: 'x' })), queued: 0, pending: 0 }),
		{ continueOnFail: true },
	);
	const [out] = await run(context);
	assert.equal(sent.length, 1);
	assert.match(out[0].json.error, /not a usable ID/);
	assert.equal(out[1].json.id, 'x');
});

test('a validation error names the field', async () => {
	const detail = [{ loc: ['body', 'query'], msg: 'String should have at most 2000 characters' }];
	const { context } = fake([{ operation: 'search', endUser: 'dana', query: 'x' }], () => ({
		statusCode: 422,
		body: { detail },
	}));
	await assert.rejects(run(context), /body\.query: String should have at most 2000 characters/);
});
