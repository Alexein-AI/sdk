import { createHash } from 'crypto';
import type {
	IDataObject,
	IExecuteFunctions,
	IHttpRequestOptions,
	INodeExecutionData,
	INodeType,
	INodeTypeDescription,
	JsonObject,
} from 'n8n-workflow';
import { NodeApiError, NodeConnectionTypes, NodeOperationError } from 'n8n-workflow';

import { fields, operations } from './fields';
import {
	BATCH,
	checkedUser,
	host,
	item,
	merged,
	page,
	PAGED,
	request,
	shaped,
	UNNAMED,
	type Get,
} from './requests';

// Programmatic rather than declarative: Add sends every input item for one app user as one request
// of up to 500 items, Search builds a context string from the whole answer, and Return All follows
// `next` from page to page. None maps onto one declarative request per item.
export class Alexein implements INodeType {
	description: INodeTypeDescription = {
		displayName: 'Alexein',
		name: 'alexein',
		icon: {
			light: 'file:../../icons/alexein.svg',
			dark: 'file:../../icons/alexein.dark.svg',
		},
		group: ['transform'],
		version: 1,
		subtitle: '={{$parameter["operation"]}}',
		description: 'Long-term memory for your users and agents: add what they say, search it later',
		defaults: { name: 'Alexein' },
		usableAsTool: true,
		inputs: [NodeConnectionTypes.Main],
		outputs: [NodeConnectionTypes.Main],
		credentials: [{ name: 'alexeinApi', required: true }],
		properties: [...operations, ...fields],
	};

	async execute(this: IExecuteFunctions): Promise<INodeExecutionData[][]> {
		const operation = this.getNodeParameter('operation', 0) as string;
		const answers = operation === 'add' ? await added(this) : await answered(this, operation);
		return [answers];
	}
}

const getter =
	(context: IExecuteFunctions, index: number): Get =>
	(name, fallback) =>
		context.getNodeParameter(name, index, fallback);

interface Sent {
	path: string;
	body: IDataObject;
	// The app user; none for the routes that name none.
	user?: string;
	// An add's Idempotency-Key.
	key?: string;
}

async function send(context: IExecuteFunctions, sent: Sent, index: number): Promise<IDataObject> {
	const credentials = await context.getCredentials('alexeinApi');
	const headers: IDataObject = {};
	if (sent.user !== undefined) headers['X-Alexein-User'] = sent.user;
	if (sent.key !== undefined) headers['Idempotency-Key'] = sent.key;
	const options: IHttpRequestOptions = {
		method: 'POST',
		url: `${host(credentials.baseUrl)}/v2/memory/${sent.path}`,
		headers,
		body: sent.body,
		json: true,
		returnFullResponse: true,
		ignoreHttpStatusErrors: true,
	};
	const response = (await context.helpers.httpRequestWithAuthentication.call(
		context,
		'alexeinApi',
		options,
	)) as { statusCode: number; body: unknown };
	const { statusCode: status, body: answer } = response;
	if (status < 400) return answer as IDataObject;
	// The API's own words: `detail` is a sentence; on a 422, `errors` names each field.
	const refused = (answer ?? {}) as IDataObject;
	const errors = Array.isArray(refused.errors) ? (refused.errors as IDataObject[]) : [];
	const said = typeof refused.detail === 'string' ? refused.detail : String(answer ?? '');
	throw new NodeApiError(context.getNode(), refused as JsonObject, {
		httpCode: String(status),
		message: said || `The Alexein API answered ${status}`,
		description:
			status === 429 || status === 503
				? 'Turn on Retry On Fail in the node settings to try again.'
				: errors.map((e) => `${e.field}: ${e.message}`).join('; ') || undefined,
		itemIndex: index,
	});
}

function failed(
	context: IExecuteFunctions,
	error: unknown,
	index: number,
): NodeApiError | NodeOperationError {
	if (error instanceof NodeApiError || error instanceof NodeOperationError) return error;
	return new NodeOperationError(context.getNode(), error as Error, { itemIndex: index });
}

// One input item's answer. With Return All, every page, followed by `next`, as one answer.
async function answer(
	context: IExecuteFunctions,
	operation: string,
	get: Get,
	index: number,
): Promise<IDataObject> {
	const user = UNNAMED.has(operation) ? undefined : checkedUser(get('user'));
	if (!(operation in PAGED && get('returnAll', false))) {
		return await send(context, { ...request(operation, get), user }, index);
	}
	const pages: IDataObject[] = [];
	let cursor: string | null = null;
	do {
		const got = await send(context, { ...page(operation, get, cursor), user }, index);
		pages.push(got);
		cursor = typeof got.next === 'string' && got.next ? got.next : null;
	} while (cursor);
	return merged(operation, pages);
}

async function answered(
	context: IExecuteFunctions,
	operation: string,
): Promise<INodeExecutionData[]> {
	const out: INodeExecutionData[] = [];
	const items = context.getInputData();
	for (let index = 0; index < items.length; index++) {
		try {
			const get = getter(context, index);
			const json = shaped(operation, await answer(context, operation, get, index), get);
			out.push({ json, pairedItem: { item: index } });
		} catch (error) {
			if (!context.continueOnFail()) throw failed(context, error, index);
			out.push({ json: { error: (error as Error).message }, pairedItem: { item: index } });
		}
	}
	return out;
}

// An add's Idempotency-Key: the same for the same items sent again in the same execution, as Retry
// On Fail sends them, so a retry never saves an item twice; a new one in the next execution.
function idempotencyKey(context: IExecuteFunctions, sent: unknown, batch: number): string {
	const node = context.getNode();
	const named = JSON.stringify([context.getExecutionId(), node.id, node.name, sent]);
	return `${createHash('sha256').update(named).digest('hex')}-${batch}`;
}

// Input items for one app user, in order, go as one request of up to BATCH items; each comes back
// as the API's answer for its own item.
async function added(context: IExecuteFunctions): Promise<INodeExecutionData[]> {
	const items = context.getInputData();
	const out: Array<INodeExecutionData | undefined> = new Array(items.length);
	const failure = (index: number, error: unknown) => {
		if (!context.continueOnFail()) throw failed(context, error, index);
		out[index] = { json: { error: (error as Error).message }, pairedItem: { item: index } };
	};

	const groups = new Map<string, Array<{ index: number; item: IDataObject }>>();
	for (let index = 0; index < items.length; index++) {
		try {
			const get = getter(context, index);
			const key = JSON.stringify([
				checkedUser(get('user')),
				Boolean(get('wait', false)),
				Boolean(get('redact', false)),
			]);
			groups.set(key, [...(groups.get(key) ?? []), { index, item: item(get) }]);
		} catch (error) {
			failure(index, error);
		}
	}

	for (const [group, members] of groups) {
		const [user, wait, redact] = JSON.parse(group) as [string, boolean, boolean];
		for (let at = 0; at < members.length; at += BATCH) {
			const batch = members.slice(at, at + BATCH);
			try {
				const body: IDataObject = { items: batch.map((m) => m.item), wait };
				if (redact) body.redact = true;
				const key = idempotencyKey(context, [user, body], at / BATCH);
				const answer = await send(context, { path: 'add', body, user, key }, batch[0].index);
				const each = (answer.items as IDataObject[] | undefined) ?? [];
				batch.forEach((member, k) => {
					const json = { ...(each[k] ?? {}), waiting: answer.waiting };
					out[member.index] = { json, pairedItem: { item: member.index } };
				});
			} catch (error) {
				for (const member of batch) failure(member.index, error);
			}
		}
	}
	return out.filter((entry): entry is INodeExecutionData => entry !== undefined);
}
