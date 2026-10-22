// End to end: real n8n (e2e/docker-compose.yml) with this package, against a running memory API.
//
//   TWIN_MEMORY_API_KEY=tm_... node e2e/run.mjs
//
// Builds the package, starts n8n, creates the owner, the credential (and runs its Test), imports a
// workflow - Webhook -> Add -> Search -> Respond -> Forget - and calls it. Then asks the memory API
// itself that the item was forgotten. It asks no model: the search is fast, and the MCP check greps.
//
// TWIN_MEMORY_BASE_URL is the API as this machine reaches it (default http://localhost:8210);
// n8n, in Docker, reaches the same port on host.docker.internal.

import { execSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { cpSync, mkdirSync, readFileSync, rmSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..');
const N8N = `http://localhost:${process.env.N8N_PORT ?? 5679}`;
const API = (process.env.TWIN_MEMORY_BASE_URL ?? 'http://localhost:8210').replace(/\/+$/, '');
const FROM_N8N = API.replace(/\/\/(localhost|127\.0\.0\.1)/, '//host.docker.internal');
const KEY = process.env.TWIN_MEMORY_API_KEY;
if (!KEY) throw new Error('Set TWIN_MEMORY_API_KEY to a key that writes');

const sh = (command, cwd = root) => execSync(command, { cwd, stdio: 'inherit' });
const step = (said) => console.log(`\n- ${said}`);

let cookie = '';
async function n8n(path, body, method = body === undefined ? 'GET' : 'POST') {
	const response = await fetch(`${N8N}${path}`, {
		method,
		headers: { 'content-type': 'application/json', cookie },
		body: body === undefined ? undefined : JSON.stringify(body),
	});
	cookie = response.headers.get('set-cookie')?.split(';')[0] ?? cookie;
	const text = await response.text();
	if (!response.ok) throw new Error(`${method} ${path}: ${response.status} ${text.slice(0, 500)}`);
	return text ? JSON.parse(text) : {};
}

// A workflow's webhook, called. Activation answers before the webhook is registered, and a call
// meanwhile is a 404, so it is called until it is not.
async function hook(path, body) {
	for (let tries = 0; ; tries++) {
		const called = await fetch(`${N8N}/webhook/${path}`, {
			method: 'POST',
			headers: { 'content-type': 'application/json' },
			body: JSON.stringify(body),
		});
		if (called.status !== 404 || tries === 30) return called.json();
		await new Promise((resolve) => setTimeout(resolve, 1000));
	}
}

function check(condition, said, seen) {
	if (!condition) throw new Error(`${said}\n${JSON.stringify(seen, null, 1).slice(0, 2000)}`);
	console.log(`  ok: ${said}`);
}

step('build, and start n8n with the package');
sh('npm run build');
rmSync(join(here, '.package'), { recursive: true, force: true });
mkdirSync(join(here, '.package'));
cpSync(join(root, 'package.json'), join(here, '.package', 'package.json'));
cpSync(join(root, 'dist'), join(here, '.package', 'dist'), { recursive: true });
sh('docker compose up -d --force-recreate', here);
for (let tries = 0; !(await fetch(`${N8N}/healthz/readiness`).catch(() => ({}))).ok; tries++) {
	if (tries === 90) throw new Error('n8n never became ready');
	await new Promise((resolve) => setTimeout(resolve, 2000));
}

step('owner, and the node types n8n loaded');
try {
	await n8n('/rest/owner/setup', {
		email: 'e2e@example.com',
		firstName: 'E2E',
		lastName: 'Test',
		password: 'E2e-test-password-1',
	});
} catch {
	await n8n('/rest/login', {
		emailOrLdapLoginId: 'e2e@example.com',
		password: 'E2e-test-password-1',
	});
}
const types = await n8n('/types/nodes.json');
const node = types.find((t) => t.name.endsWith('.twinMemory'));
const tool = types.find((t) => t.name.endsWith('.twinMemoryTool'));
check(
	node && tool,
	'Twin Memory and its AI tool variant are loaded',
	types.map((t) => t.name).filter((n) => /twin/i.test(n)),
);
check(
	tool.properties.some((p) => p.name === 'toolDescription'),
	'the tool variant has a Description a builder can set',
	tool.properties.map((p) => p.name),
);

step('credential, and its Test');
const data = { apiKey: KEY, baseUrl: FROM_N8N };
const credential = (
	await n8n('/rest/credentials', { name: 'twin memory e2e', type: 'twinMemoryApi', data })
).data;
const tested = (await n8n('/rest/credentials/test', { credentials: { ...credential, data } })).data;
check(tested.status === 'OK', 'the credential Test passes (GET /v1/me)', tested);
const bad = (
	await n8n('/rest/credentials/test', {
		credentials: { ...credential, data: { ...data, apiKey: 'tm_wrong' } },
	})
).data;
console.log(`  a wrong key's Test: ${bad.status} ${bad.message ?? ''}`);

step('workflow: Webhook -> Add -> Search -> Respond -> Forget');
const user = `n8n-e2e-${randomUUID().slice(0, 8)}`;
const path = `twin-e2e-${randomUUID().slice(0, 8)}`;
const creds = { twinMemoryApi: { id: credential.id, name: credential.name } };
const body = "$('Webhook').item.json.body";
const workflow = {
	name: 'twin memory e2e',
	nodes: [
		{
			id: randomUUID(),
			name: 'Webhook',
			type: 'n8n-nodes-base.webhook',
			typeVersion: 2,
			position: [0, 0],
			webhookId: randomUUID(),
			parameters: { httpMethod: 'POST', path, responseMode: 'responseNode', options: {} },
		},
		{
			id: randomUUID(),
			name: 'Add',
			type: node.name,
			typeVersion: 1,
			position: [220, 0],
			credentials: creds,
			parameters: {
				resource: 'memory',
				operation: 'add',
				endUser: `={{ ${body}.user }}`,
				text: `={{ ${body}.text }}`,
				kind: 'note',
				wait: true,
				additionalFields: { id: `={{ ${body}.id }}` },
			},
		},
		{
			id: randomUUID(),
			name: 'Search',
			type: node.name,
			typeVersion: 1,
			position: [440, 0],
			credentials: creds,
			parameters: {
				resource: 'memory',
				operation: 'search',
				endUser: `={{ ${body}.user }}`,
				query: `={{ ${body}.question }}`,
				fast: true,
			},
		},
		{
			id: randomUUID(),
			name: 'Respond',
			type: 'n8n-nodes-base.respondToWebhook',
			typeVersion: 1.1,
			position: [660, 0],
			parameters: {
				respondWith: 'json',
				responseBody: '={{ JSON.stringify($json) }}',
				options: {},
			},
		},
		{
			id: randomUUID(),
			name: 'Forget',
			type: node.name,
			typeVersion: 1,
			position: [880, 0],
			credentials: creds,
			parameters: {
				resource: 'memory',
				operation: 'forget',
				endUser: `={{ ${body}.user }}`,
				items: `={{ ${body}.id }}`,
			},
		},
	],
	connections: {
		Webhook: { main: [[{ node: 'Add', type: 'main', index: 0 }]] },
		Add: { main: [[{ node: 'Search', type: 'main', index: 0 }]] },
		Search: { main: [[{ node: 'Respond', type: 'main', index: 0 }]] },
		Respond: { main: [[{ node: 'Forget', type: 'main', index: 0 }]] },
	},
	settings: { executionOrder: 'v1' },
};
const created = (await n8n('/rest/workflows', workflow)).data;
await n8n(`/rest/workflows/${created.id}/activate`, { versionId: created.versionId });

step('call the workflow');
const sent = {
	user,
	id: 'tea',
	text: 'Prefers green tea over coffee.',
	question: 'Which tea does she prefer?',
};
const answer = await hook(path, sent);
check(
	typeof answer.context === 'string' && answer.context.includes('green tea'),
	'search found what Add saved, with a context',
	answer,
);
check(answer.filtered === false, 'a fast search was not filtered', answer);

step('memory itself says the item was forgotten');
let state = '';
for (let tries = 0; tries < 20 && state !== 'forgotten'; tries++) {
	await new Promise((resolve) => setTimeout(resolve, 500));
	const versions = await fetch(`${API}/v1/memory/versions`, {
		method: 'POST',
		headers: {
			Authorization: `Bearer ${KEY}`,
			'X-Twin-Account': user,
			'content-type': 'application/json',
		},
		body: JSON.stringify({ id: 'tea' }),
	});
	state = (await versions.json()).state;
}
check(state === 'forgotten', 'Forget erased it', { state });

step("n8n's own MCP Client reaches /v1/mcp with the key and the end user as headers");
const mcpUser = `n8n-mcp-${randomUUID().slice(0, 8)}`;
const added = await fetch(`${API}/v1/memory/add`, {
	method: 'POST',
	headers: {
		Authorization: `Bearer ${KEY}`,
		'X-Twin-Account': mcpUser,
		'content-type': 'application/json',
	},
	body: JSON.stringify({
		wait: true,
		items: [{ id: 'tea', kind: 'note', text: 'Prefers green tea over coffee.' }],
	}),
});
check(added.ok, 'an item added over HTTP for the MCP check', await added.json());
const headers = (
	await n8n('/rest/credentials', {
		name: 'twin memory MCP e2e',
		type: 'httpMultipleHeadersAuth',
		data: {
			headers: {
				values: [
					{ name: 'Authorization', value: `Bearer ${KEY}` },
					{ name: 'X-Twin-Account', value: mcpUser },
				],
			},
		},
	})
).data;
const mcpPath = `twin-mcp-${randomUUID().slice(0, 8)}`;
const mcpFlow = (
	await n8n('/rest/workflows', {
		name: 'twin memory MCP e2e',
		nodes: [
			{
				id: randomUUID(),
				name: 'Webhook',
				type: 'n8n-nodes-base.webhook',
				typeVersion: 2,
				position: [0, 0],
				webhookId: randomUUID(),
				parameters: { httpMethod: 'POST', path: mcpPath, responseMode: 'lastNode', options: {} },
			},
			{
				id: randomUUID(),
				name: 'MCP Client',
				type: '@n8n/n8n-nodes-langchain.mcpClient',
				typeVersion: 1.1,
				position: [220, 0],
				credentials: { httpMultipleHeadersAuth: { id: headers.id, name: headers.name } },
				parameters: {
					serverTransport: 'httpStreamable',
					endpointUrl: `${FROM_N8N}/v1/mcp`,
					authentication: 'multipleHeadersAuth',
					tool: { __rl: true, mode: 'id', value: 'memory_grep' },
					inputMode: 'json',
					jsonInput: '{"pattern": "green tea"}',
					options: {},
				},
			},
		],
		connections: { Webhook: { main: [[{ node: 'MCP Client', type: 'main', index: 0 }]] } },
		settings: { executionOrder: 'v1' },
	})
).data;
await n8n(`/rest/workflows/${mcpFlow.id}/activate`, { versionId: mcpFlow.versionId });
const viaMcp = await hook(mcpPath, {});
check(
	JSON.stringify(viaMcp).includes('green tea'),
	"memory_grep over MCP finds this end user's item",
	viaMcp,
);

step('the Telegram template imports, and every node in it is one n8n knows');
const template = JSON.parse(
	readFileSync(join(root, 'templates', 'telegram-assistant-memory.json'), 'utf8'),
);
// Installed from npm the node is n8n-nodes-twinmemory.*; mounted here, n8n names it CUSTOM.*.
const local = JSON.parse(
	JSON.stringify(template).replaceAll('n8n-nodes-twinmemory.', `${node.name.split('.')[0]}.`),
);
const imported = (await n8n('/rest/workflows', local)).data;
const known = new Set(types.flatMap((t) => [t.version].flat().map((v) => `${t.name}@${v}`)));
const unknown = imported.nodes
	.filter((n) => !known.has(`${n.type}@${n.typeVersion}`))
	.map((n) => `${n.type}@${n.typeVersion}`);
check(unknown.length === 0, 'every template node and version exists in n8n 2.44.6', unknown);
const saving = imported.nodes.find((n) => n.name === 'Save to Memory');
check(
	saving.parameters.descriptionType === 'manual' &&
		saving.parameters.toolDescription.includes('When in doubt, save.'),
	'the save tool carries the save policy',
	saving.parameters,
);

console.log('\nall passed. Stop n8n with: docker compose -f e2e/docker-compose.yml down -v');
