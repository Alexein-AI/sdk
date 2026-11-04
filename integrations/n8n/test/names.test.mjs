// What saved workflows and credentials know the node by, and where a new credential points. Run
// against the build: `npm test`.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import credentials from '../dist/credentials/TwinMemoryApi.credentials.js';
import node from '../dist/nodes/TwinMemory/TwinMemory.node.js';

const DOCS = 'https://docs.alexein.ai/integrations/n8n';
const codex = JSON.parse(
	readFileSync(new URL('../dist/nodes/TwinMemory/TwinMemory.node.json', import.meta.url), 'utf8'),
);

test('the node, its operations and its credential keep the names saved workflows use', () => {
	const { description } = new node.TwinMemory();
	assert.equal(description.name, 'twinMemory');
	assert.equal(description.displayName, 'Twin Memory');
	assert.equal(codex.node, 'n8n-nodes-twinmemory.twinMemory');
	assert.deepEqual(description.credentials, [{ name: 'twinMemoryApi', required: true }]);
	const operation = description.properties.find((p) => p.name === 'operation');
	assert.deepEqual(operation.options.map((o) => o.value).sort(), [
		'add',
		'around',
		'correct',
		'forget',
		'grep',
		'history',
		'latest',
		'lineage',
		'ls',
		'overview',
		'read',
		'search',
		'status',
		'versions',
	]);
	const credential = new credentials.TwinMemoryApi();
	assert.equal(credential.name, 'twinMemoryApi');
	assert.equal(credential.displayName, 'Twin Memory API');
	assert.deepEqual(
		credential.properties.map((p) => p.name),
		['apiKey', 'baseUrl'],
	);
});

test('a new credential points at the Alexein API, and every link at the docs', () => {
	const credential = new credentials.TwinMemoryApi();
	const baseUrl = credential.properties.find((p) => p.name === 'baseUrl');
	assert.equal(baseUrl.default, 'https://api.alexein.ai');
	assert.equal(credential.documentationUrl, DOCS);
	assert.deepEqual(codex.resources, {
		credentialDocumentation: [{ url: `${DOCS}#credential` }],
		primaryDocumentation: [{ url: DOCS }],
	});
});
