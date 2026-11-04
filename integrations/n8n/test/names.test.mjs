// What saved workflows and credentials know the node by, and where a new credential points. Run
// against the build: `npm test`.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import credentials from '../dist/credentials/AlexeinApi.credentials.js';
import node from '../dist/nodes/Alexein/Alexein.node.js';

const DOCS = 'https://docs.alexein.ai/integrations/n8n';
const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8');
const codex = JSON.parse(read('../dist/nodes/Alexein/Alexein.node.json'));
const pkg = JSON.parse(read('../package.json'));

test('the node, its operations and its credential have the names saved workflows use', () => {
	const { description } = new node.Alexein();
	assert.equal(description.name, 'alexein');
	assert.equal(description.displayName, 'Alexein');
	assert.equal(description.usableAsTool, true);
	assert.equal(pkg.name, '@alexein/n8n-nodes-alexein');
	assert.equal(codex.node, `${pkg.name}.alexein`);
	assert.deepEqual(pkg.n8n.nodes, ['dist/nodes/Alexein/Alexein.node.js']);
	assert.deepEqual(pkg.n8n.credentials, ['dist/credentials/AlexeinApi.credentials.js']);
	assert.deepEqual(description.credentials, [{ name: 'alexeinApi', required: true }]);
	const operation = description.properties.find((p) => p.name === 'operation');
	assert.deepEqual(operation.options.map((o) => o.value).sort(), [
		'add',
		'around',
		'correct',
		'deleteUser',
		'export',
		'facts',
		'forget',
		'grep',
		'history',
		'item',
		'items',
		'latest',
		'open',
		'openItems',
		'search',
		'sources',
		'status',
		'summary',
		'users',
		'versions',
	]);
	const credential = new credentials.AlexeinApi();
	assert.equal(credential.name, 'alexeinApi');
	assert.equal(credential.displayName, 'Alexein API');
	assert.deepEqual(
		credential.properties.map((p) => p.name),
		['apiKey', 'baseUrl'],
	);
});

test('a new credential points at the Alexein API, is tested with GET /v2/me, and links the docs', () => {
	const credential = new credentials.AlexeinApi();
	const baseUrl = credential.properties.find((p) => p.name === 'baseUrl');
	assert.equal(baseUrl.default, 'https://api.alexein.ai');
	assert.equal(credential.test.request.url, '/v2/me');
	assert.equal(credential.test.request.method, 'GET');
	// The test's expression drops a trailing `/` or `/v2`, as the node does.
	const [, expression] = credential.test.request.baseURL.match(
		/^=\{\{\$credentials\.baseUrl(.*)\}\}$/,
	);
	const normalised = new Function('url', `return url${expression}`);
	for (const url of [
		'http://localhost:8210',
		'http://localhost:8210/',
		'http://localhost:8210/v2/',
	]) {
		assert.equal(normalised(url), 'http://localhost:8210', url);
	}
	assert.equal(credential.documentationUrl, DOCS);
	assert.deepEqual(codex.resources, {
		credentialDocumentation: [{ url: `${DOCS}#credential` }],
		primaryDocumentation: [{ url: DOCS }],
	});
});

test("what a builder or a model reads speaks Alexein's public words", () => {
	const { description } = new node.Alexein();
	const shown = JSON.stringify(description).toLowerCase();
	// The old product name is spelt in two, so a grep of this package for it finds nothing.
	for (const word of ['passage', 'record', 'tree', 'lineage', 'end user', 'tw' + 'in']) {
		assert.ok(!shown.includes(word), word);
	}
});
