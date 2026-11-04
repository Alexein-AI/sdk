// What each operation sends, and what the node makes of the answer. Pure functions over the node's
// parameters, so they are tested without n8n; `Alexein.node.ts` only sends and collects.

import type { IDataObject } from 'n8n-workflow';

// A parameter of the current item, with its default when unset.
export type Get = (name: string, fallback?: unknown) => unknown;

export interface Request {
	// The route under /v2/memory/.
	path: string;
	body: IDataObject;
}

// The API takes at most this many items in one add.
export const BATCH = 500;

// The routes whose name is not the operation's value. Every other operation's value is its route.
const ROUTES: Record<string, string> = { openItems: 'open_items', deleteUser: 'users/delete' };

export const route = (operation: string) => ROUTES[operation] ?? operation;

// The operations that name no app user: they send no X-Alexein-User.
export const UNNAMED = new Set(['users']);

// The paged operations, the list each page holds, and the most one page may hold.
export const PAGED: Record<string, { key: string; max: number }> = {
	facts: { key: 'facts', max: 100 },
	items: { key: 'items', max: 200 },
	export: { key: 'records', max: 500 },
	users: { key: 'users', max: 500 },
};

// The host of the API: the credential's Base URL without a trailing `/` or `/v2`, which the node
// adds itself, so `http://localhost:8210/v2/` and `http://localhost:8210` are the same.
export const host = (baseUrl: unknown) => String(baseUrl ?? '').replace(/(?:\/v2)?\/*$/, '');

// An app user ID: 1-35 letters, digits, '.', '_' and '-', beginning with a letter or digit. Checked
// before a round trip, so the mistake shows on the item that made it.
const USER_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,34}$/;

export function checkedUser(value: unknown): string {
	const user = String(value ?? '').trim();
	if (!USER_ID.test(user)) {
		throw new Error(
			`App User "${user}" is not a usable ID: 1 to 35 letters, digits, '.', '_' and '-', beginning with a letter or digit`,
		);
	}
	return user;
}

const text = (value: unknown) => String(value ?? '').trim();

const list = (value: unknown) =>
	(Array.isArray(value) ? value.map(String) : text(value).split(','))
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

function parsedJson(value: string): unknown {
	try {
		return JSON.parse(value);
	} catch {
		return undefined;
	}
}

// A JSON object field (Metadata, Filters): left out when empty.
function object(value: unknown, field: string): IDataObject | undefined {
	if (value === undefined || value === null || value === '') return undefined;
	const parsed = typeof value === 'string' ? parsedJson(value) : value;
	if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
		throw new Error(`${field} must be a JSON object`);
	}
	return Object.keys(parsed).length ? (parsed as IDataObject) : undefined;
}

// One item for an add, from one input item's parameters.
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
		metadata: object(extra.metadata, 'Metadata'),
	});
}

// What narrows a read: where a memory came from, and which items it came from.
function narrowed(options: IDataObject): IDataObject {
	return {
		provider: text(options.provider),
		source: text(options.source),
		kind: list(options.kind),
		filters: object(options.filters, 'Filters'),
	};
}

// One page of a paged operation. With Return All, each page is as long as the API allows and
// `cursor` is the `next` of the page before.
export function page(operation: string, get: Get, cursor?: string | null): Request {
	const returnAll = Boolean(get('returnAll', false));
	const options = (get('itemsOptions', {}) ?? {}) as IDataObject;
	return {
		path: route(operation),
		body: present({
			limit: returnAll ? PAGED[operation].max : (get('limit', 50) as number),
			cursor: returnAll ? (cursor ?? '') : text(get('cursor', '')),
			filters: operation === 'items' ? object(options.filters, 'Filters') : undefined,
		}),
	};
}

// Every operation but add: one request per input item (Return All follows `next` from here).
export function request(operation: string, get: Get): Request {
	if (operation in PAGED) return page(operation, get);
	const post = (body: IDataObject): Request => ({ path: route(operation), body: present(body) });
	switch (operation) {
		case 'search': {
			const options = (get('searchOptions', {}) ?? {}) as IDataObject;
			return post({
				query: text(get('query')),
				fast: Boolean(get('fast', false)),
				before: text(options.before),
				after: text(options.after),
				...narrowed(options),
			});
		}
		case 'latest': {
			const options = (get('latestOptions', {}) ?? {}) as IDataObject;
			return post({
				k: get('k', 10) as number,
				place: text(options.place),
				after: text(options.after),
				before: text(options.before),
				...narrowed(options),
			});
		}
		case 'grep': {
			const { provider, source, kind } = narrowed((get('grepOptions', {}) ?? {}) as IDataObject);
			return post({
				pattern: text(get('pattern')),
				limit: get('limit', 50) as number,
				provider,
				source,
				kind,
			});
		}
		case 'open':
			return post({ ref: text(get('ref')) });
		case 'around':
			return post({ ref: text(get('ref')), width: get('width', 2) as number });
		case 'history':
			return post({ subject: text(get('subject')), attribute: text(get('attribute')) });
		case 'openItems': {
			const options = (get('openItemsOptions', {}) ?? {}) as IDataObject;
			return post({
				limit: get('limit', 50) as number,
				mine: options.mine as boolean | undefined,
				within_days: options.withinDays as number | undefined,
				place: text(options.place),
				provider: text(options.provider),
				kind: list(options.kind),
			});
		}
		case 'item':
		case 'versions':
			return post({ id: text(get('itemId')) });
		case 'status': {
			const items = list(get('ids'));
			if (!items.length) throw new Error('Item IDs is empty: name at least one item');
			return post({ items });
		}
		case 'forget': {
			const named = present({
				items: list(get('items', '')),
				sessions: list(get('sessions', '')),
				refs: list(get('refs', '')),
			});
			if (!Object.keys(named).length) {
				throw new Error('Nothing to forget: name at least one item, session or ref');
			}
			return post(named);
		}
		case 'correct':
			return post({ ref: text(get('ref')), replacement: text(get('replacement')) });
		case 'summary':
		case 'sources':
		case 'deleteUser':
			return post({});
		default:
			throw new Error(`Unknown operation "${operation}"`);
	}
}

// Pages of a paged operation as one answer: the first page's fields, every page's list, no `next`.
export function merged(operation: string, pages: IDataObject[]): IDataObject {
	const { key } = PAGED[operation];
	const all = pages.flatMap((p) => (Array.isArray(p[key]) ? (p[key] as IDataObject[]) : []));
	return { ...pages[0], [key]: all, next: null };
}

const oneLine = (value: unknown) =>
	String(value ?? '')
		.split(/\s+/)
		.filter(Boolean)
		.join(' ');

// A block to paste into a prompt: the notes, then each memory on a line of its own - `- ` and its
// text, an excerpt's prefixed with its date when known - whole lines only, at most `maxChars`
// long, and empty when memory found nothing. The text the SDKs' `SearchResult.context()` gives.
export function context(answer: IDataObject, maxChars: number): string {
	const memories = Array.isArray(answer.memories) ? (answer.memories as IDataObject[]) : [];
	if (!memories.length) return '';
	const notes = Array.isArray(answer.notes) ? answer.notes.map(oneLine).filter(Boolean) : [];
	const lines = memories.map((memory) => {
		const date = memory.type === 'excerpt' && memory.date ? String(memory.date).slice(0, 10) : '';
		return `- ${date ? `${date}: ` : ''}${oneLine(memory.text)}`;
	});
	let out = '';
	for (const line of [...notes, ...lines]) {
		const grown = out ? `${out}\n${line}` : line;
		if (grown.length > maxChars) break;
		out = grown;
	}
	return out;
}

// What one input item's output is: the API's answer, and for a search the context first.
export function shaped(operation: string, answer: IDataObject, get: Get): IDataObject {
	if (operation !== 'search') return answer;
	const options = (get('searchOptions', {}) ?? {}) as IDataObject;
	const length = Number(options.contextLength ?? 4000) || 4000;
	return { context: context(answer, length), ...answer };
}
