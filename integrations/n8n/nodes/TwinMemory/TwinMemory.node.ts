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
import { BATCH, checkedUser, item, request, shaped, type Get } from './requests';

// Programmatic rather than declarative: Add sends every input item for one end user as a single
// request of up to 500 items, and Search builds a context string from the whole answer. Neither
// maps onto one declarative request per item.
export class TwinMemory implements INodeType {
	description: INodeTypeDescription = {
		displayName: 'Twin Memory',
		name: 'twinMemory',
		icon: {
			light: 'file:../../icons/twinmemory.svg',
			dark: 'file:../../icons/twinmemory.dark.svg',
		},
		group: ['transform'],
		version: 1,
		subtitle: '={{$parameter["operation"]}}',
		description: 'Long-term memory for your users and agents: add what they say, search it later',
		defaults: { name: 'Twin Memory' },
		usableAsTool: true,
		inputs: [NodeConnectionTypes.Main],
		outputs: [NodeConnectionTypes.Main],
		credentials: [{ name: 'twinMemoryApi', required: true }],
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

async function send(
	context: IExecuteFunctions,
	path: string,
	body: IDataObject,
	user: string,
	index: number,
): Promise<IDataObject> {
	const credentials = await context.getCredentials('twinMemoryApi');
	const base = String(credentials.baseUrl ?? '').replace(/\/+$/, '');
	const options: IHttpRequestOptions = {
		method: 'POST',
		url: `${base}/v1/memory/${path}`,
		headers: { 'X-Twin-Account': user },
		body,
		json: true,
		returnFullResponse: true,
		ignoreHttpStatusErrors: true,
	};
	const response = (await context.helpers.httpRequestWithAuthentication.call(
		context,
		'twinMemoryApi',
		options,
	)) as { statusCode: number; body: unknown };
	const { statusCode: status, body: answer } = response;
	if (status < 400) return answer as IDataObject;
	// The API's own words: `detail` is a sentence, or a list of fields for a 422.
	const detail = (answer as IDataObject | undefined)?.detail;
	const said = Array.isArray(detail)
		? (detail as IDataObject[])
				.map((e) => `${(e.loc as string[] | undefined)?.join('.')}: ${e.msg}`)
				.join('; ')
		: String(detail ?? answer ?? '');
	throw new NodeApiError(context.getNode(), (answer ?? {}) as JsonObject, {
		httpCode: String(status),
		message: said || `The memory API answered ${status}`,
		description:
			status === 429 || status === 503
				? 'Turn on Retry On Fail in the node settings to try again.'
				: undefined,
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

async function answered(
	context: IExecuteFunctions,
	operation: string,
): Promise<INodeExecutionData[]> {
	const out: INodeExecutionData[] = [];
	const items = context.getInputData();
	for (let index = 0; index < items.length; index++) {
		try {
			const get = getter(context, index);
			const user = checkedUser(get('endUser'));
			const { path, body } = request(operation, get);
			const answer = await send(context, path, body, user, index);
			out.push({ json: shaped(operation, answer, get), pairedItem: { item: index } });
		} catch (error) {
			if (!context.continueOnFail()) throw failed(context, error, index);
			out.push({ json: { error: (error as Error).message }, pairedItem: { item: index } });
		}
	}
	return out;
}

// Input items for one end user, in order, go as one request of up to BATCH items; each comes
// back as the API's answer for its own item.
async function added(context: IExecuteFunctions): Promise<INodeExecutionData[]> {
	const items = context.getInputData();
	const out: Array<INodeExecutionData | undefined> = new Array(items.length);
	const failure = (index: number, error: unknown) => {
		if (!context.continueOnFail()) throw failed(context, error, index);
		out[index] = { json: { error: (error as Error).message }, pairedItem: { item: index } };
	};

	const batches = new Map<string, Array<{ index: number; item: IDataObject }>>();
	for (let index = 0; index < items.length; index++) {
		try {
			const get = getter(context, index);
			const key = JSON.stringify([checkedUser(get('endUser')), Boolean(get('wait', false))]);
			batches.set(key, [...(batches.get(key) ?? []), { index, item: item(get) }]);
		} catch (error) {
			failure(index, error);
		}
	}

	for (const [key, members] of batches) {
		const [user, wait] = JSON.parse(key) as [string, boolean];
		for (let at = 0; at < members.length; at += BATCH) {
			const batch = members.slice(at, at + BATCH);
			try {
				const body = { items: batch.map((m) => m.item), wait };
				const answer = await send(context, 'add', body, user, batch[0].index);
				const each = (answer.items as IDataObject[] | undefined) ?? [];
				batch.forEach((member, k) => {
					const json = { ...(each[k] ?? {}), pending: answer.pending, queued: answer.queued };
					out[member.index] = { json, pairedItem: { item: member.index } };
				});
			} catch (error) {
				for (const member of batch) failure(member.index, error);
			}
		}
	}
	return out.filter((entry): entry is INodeExecutionData => entry !== undefined);
}
