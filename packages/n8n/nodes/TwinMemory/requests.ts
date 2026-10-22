// What each operation sends, and what the node makes of the answer. Pure functions over the node's
// parameters, so they are tested without n8n; `TwinMemory.node.ts` only sends and collects.

import type { IDataObject } from 'n8n-workflow';

// A parameter of the current item, with its default when unset.
export type Get = (name: string, fallback?: unknown) => unknown;

export interface Request {
	path: string;
	body: IDataObject;
}

// The API takes at most this many items in one add.
export const BATCH = 500;

// What the API accepts as an end user ID, checked before a round trip.
const USER_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;

export function checkedUser(value: unknown): string {
	const user = String(value ?? '').trim();
	if (!USER_ID.test(user)) {
		throw new Error(
			`End User "${user}" is not a usable ID: letters, digits, '.', '_' and '-', starting with a letter or digit, up to 64 characters`,
		);
	}
	return user;
}

const text = (value: unknown) => String(value ?? '').trim();

const list = (value: unknown) =>
	text(value)
		.split(',')
		.map((part) => part.trim())
		.filter(Boolean);

// Unset fields are left out, so the API applies its own defaults.
function present(body: IDataObject): IDataObject {
	return Object.fromEntries(
		Object.entries(body).filter(
			([, v]) => v !== undefined && v !== '' && !(Array.isArray(v) && v.length === 0),
		),
	);
}

function metadata(value: unknown): IDataObject | undefined {
	if (value === undefined || value === '' || value === '{}') return undefined;
	const parsed: unknown = typeof value === 'string' ? JSON.parse(value) : value;
	if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
		throw new Error('Metadata must be a JSON object');
	}
	return parsed as IDataObject;
}

// One item for /v1/memory/add, from one input item's parameters.
export function item(get: Get): IDataObject {
	const extra = (get('additionalFields', {}) ?? {}) as IDataObject;
	const said = text(get('text'));
	if (!said) throw new Error('Text is empty: there is nothing to remember');
	return present({
		text: said,
		kind: get('kind', 'message') as string,
		id: text(extra.id),
		session: text(extra.session),
		role: text(extra.role),
		author: text(extra.author),
		title: text(extra.title),
		about: list(extra.about),
		at: text(extra.at),
		expires: text(extra.expires),
		metadata: metadata(extra.metadata),
	});
}

// Every operation but add: one request per input item.
export function request(operation: string, get: Get): Request {
	const post = (path: string, body: IDataObject): Request => ({ path, body: present(body) });
	switch (operation) {
		case 'search': {
			const options = (get('searchOptions', {}) ?? {}) as IDataObject;
			return post('search', {
				query: text(get('query')),
				fast: Boolean(get('fast', false)),
				before: text(options.before),
				after: text(options.after),
				scope: text(options.scope),
			});
		}
		case 'history':
			return post('history', { subject: text(get('subject')), attribute: text(get('attribute')) });
		case 'latest': {
			const options = (get('latestOptions', {}) ?? {}) as IDataObject;
			return post('latest', {
				k: get('k', 10) as number,
				place: text(options.place),
				after: text(options.after),
				before: text(options.before),
			});
		}
		case 'grep':
			return post('grep', {
				pattern: text(get('pattern')),
				limit: get('limit', 50) as number,
				scope: text(get('scope')),
			});
		case 'read':
			return post('read', { path: text(get('path')) });
		case 'ls':
			return { path: 'ls', body: { path: text(get('path', '')) } };
		case 'around':
			return post('around', {
				passage_id: text(get('passageId')),
				width: get('width', 2) as number,
			});
		case 'overview':
			return { path: 'overview', body: {} };
		case 'versions':
			return post('versions', { id: text(get('itemId')) });
		case 'lineage':
			return post('lineage', { id: text(get('lineageId')) });
		case 'status': {
			const ids = list(get('ids'));
			if (!ids.length) throw new Error('IDs is empty: name at least one item or event');
			return post('status', { ids });
		}
		case 'forget': {
			const named = present({
				items: list(get('items', '')),
				sessions: list(get('sessions', '')),
				threads: list(get('threads', '')),
				events: list(get('events', '')),
			});
			if (!Object.keys(named).length) {
				throw new Error('Nothing to forget: name at least one item, session, thread or event');
			}
			return { path: 'forget', body: named };
		}
		case 'correct':
			return post('correct', {
				record_id: text(get('recordId')),
				replacement: text(get('replacement')),
			});
		default:
			throw new Error(`Unknown operation "${operation}"`);
	}
}

const strings = (value: unknown): string[] =>
	Array.isArray(value) ? value.map((v) => String(v)) : [];

const texts = (value: unknown): string[] =>
	Array.isArray(value) ? value.map((v) => String((v as IDataObject)?.text ?? '')) : [];

// A block to paste into a prompt: known lines, worked-out lines, dated facts, then passages,
// whole entries only, at most `maxChars` long. The same text the Python SDK's
// `SearchResult.context()` gives, so a prompt reads the same from either.
export function context(answer: IDataObject, maxChars: number): string {
	const sections: Array<[string, string[]]> = [
		['What is known', strings(answer.known)],
		['Worked out', strings(answer.worked_out)],
		['Facts', texts(answer.facts)],
		['Passages', texts(answer.hits)],
	];
	let out: string[] = [];
	for (const [title, lines] of sections) {
		let heading = out.length ? ['', `${title}:`] : [`${title}:`];
		for (const line of lines) {
			const grown = [...out, ...heading, `- ${line.split(/\s+/).filter(Boolean).join(' ')}`];
			if (grown.join('\n').length > maxChars) return out.join('\n');
			out = grown;
			heading = [];
		}
	}
	return out.join('\n');
}

// What one input item's output is: the API's answer, and for a search the context first.
export function shaped(operation: string, answer: IDataObject, get: Get): IDataObject {
	if (operation !== 'search') return answer;
	const options = (get('searchOptions', {}) ?? {}) as IDataObject;
	const length = Number(options.contextLength ?? 4000) || 4000;
	return { context: context(answer, length), ...answer };
}
